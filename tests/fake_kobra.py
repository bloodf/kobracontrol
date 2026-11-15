"""FakeKobra: a local fake Anycubic Kobra X for tests (HTTP on :18910-like port, MQTT broker on :9883-like port).

    with FakeKobra() as fake:            # or FakeKobra(tls=make_tls_files(tmpdir)) for mutual TLS
        creds = kobra.fetch_credentials(fake.host, port=fake.http_port)
        fake.reply("info", "query", {"printerName": "K"})   # scripted answer to info/query
        ...

Addresses: `host` ("127.0.0.1"), `http_port`, `mqtt_port` (random free ports).
Identity: `token` (/info token, 32 chars), `username`, `password`, `device_id`, `mode_id`, `model`
  (all encrypted into the /ctrl answer); `upload_token`, `upload_url` (announce it in info/report urls).
HTTP knobs: `info_redirect` (URL: /info answers 302 to it), `info_answer` (dict or raw bytes served by
  /info, default {"token": token}), `ctrl_answer` (dict served
  verbatim by /ctrl instead of the real encrypted answer), `upload_answer` (dict, default code 200).
  Recorded: `ctrl_calls` (query dicts), `uploads` (list of {"filename", "data", "headers"}).
MQTT knobs: `connack_code` (None = check username/password, else forced CONNACK code), `connack_delay`
  (seconds before CONNACK, to stretch a handshake), `suback_code`
  (0), `answer_pings` (True), `chunk_size` (None, or int: outgoing packets are dribbled in chunks so the
  client sees split reads).
Answers behave like real firmware 2.0.2.8 by default: every request is acknowledged at once on
  `<deviceId>/response` with `{"type": "", "action": "", "state": "", "code": 0, "msg": "", "data": null,
  "timestamp": 0, "msgid": <the request's>}`; a scripted reply then goes to `<type>/report` with a FRESH
  msgid. Scripted replies: `reply(type, action, data=None, state="done", code=200, **fields)` (action in
  the report = the request's, except info/query -> "report"; code=None leaves it out) or
  `replies[(type, action)] = callable(request_msg) -> dict | None` (published as returned, plus a fresh
  msgid unless it sets "msgid"). Knobs: `send_ack` (True), `ack_only` (False: True sends the ack and never
  the scripted reply), `echo_msgid` (False: True = legacy firmware, the report carries the request's msgid
  unless the reply sets one). `print_start` (None): "ok", "abnormal" or "quiet" answers print/start with
  the real firmware sequence instead of a scripted reply: ok = start/checking, start/printing,
  start/hotbed_heating; abnormal (what a wrong filepath gives) = start/checking, start/printing,
  stop/stopping, stop/stoped code 10111 "abnormal end of task"; quiet = start/checking, start/printing.
  Uploads answer {"code": 200, "data": {"gcode": <filename>}, "message": "success"} unless
  `upload_answer` is set. Spontaneous traffic: `report(suffix, payload)` (dict or bytes,
  e.g. "print/report"), `publish_raw(topic, payload_bytes)`. `drop_clients()` closes every connection.
  Recorded: `requests` (list of {"topic", "raw", "msg"}; msg is the parsed JSON or None), `client_ids`,
  `subscriptions`, `disconnects` (DISCONNECT packets seen), `pings`. `wait_request(type, action)` blocks
  until such a request arrives and returns its msg.
TLS: `make_tls_files(folder)` runs the `openssl` CLI to create a throwaway self-signed server pair and a
  client pair with CN=AnycubicSlicer; tests needing it skip without openssl.
"""

import base64
import hashlib
import json
import os
import socket
import ssl
import subprocess
import threading
import time
import urllib.parse
import uuid
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aes

TlsFiles = namedtuple("TlsFiles", "server_cert server_key client_cert client_key")


def make_tls_files(folder):
    def pair(name, cn):
        crt, key = os.path.join(folder, name + ".pem"), os.path.join(folder, name + "_key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-noenc", "-days", "2", "-subj", "/CN=" + cn,
                        "-keyout", key, "-out", crt], check=True, capture_output=True)
        return crt, key
    return TlsFiles(*pair("server", "kobra-fake"), *pair("client", "AnycubicSlicer"))


def _read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("eof")
        buf += chunk
    return buf


def _read_packet(sock):
    head = _read_exact(sock, 1)[0]
    length, mult = 0, 1
    while True:
        b = _read_exact(sock, 1)[0]
        length += (b & 0x7F) * mult
        mult *= 128
        if not b & 0x80:
            break
    return head >> 4, head & 0x0F, _read_exact(sock, length)


def _packet(head, body):
    n, out = len(body), bytearray([head])
    while True:
        b, n = n % 128, n // 128
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out) + body


def _s(text):
    raw = text.encode() if isinstance(text, str) else text
    return len(raw).to_bytes(2, "big") + raw


def _take_str(body, i):
    n = int.from_bytes(body[i:i + 2], "big")
    return body[i + 2:i + 2 + n], i + 2 + n


class _Session:
    def __init__(self, fake, sock):
        self.fake, self.sock, self.lock, self.subscribed = fake, sock, threading.Lock(), False

    def send(self, data):
        size = self.fake.chunk_size or len(data) or 1
        with self.lock:
            for i in range(0, len(data), size):
                self.sock.sendall(data[i:i + size])
                if self.fake.chunk_size:
                    time.sleep(0.002)

    def run(self):
        try:
            if self.connect():
                while self.handle(*_read_packet(self.sock)):
                    pass
        except (OSError, ConnectionError, ssl.SSLError):
            pass
        finally:
            self.fake._forget(self)
            try:
                self.sock.close()
            except OSError:
                pass

    def connect(self):
        ptype, _, body = _read_packet(self.sock)
        if ptype != 1:
            return False
        _, i = _take_str(body, 0)
        flags = body[i + 1]
        client_id, i = _take_str(body, i + 4)
        user, i = _take_str(body, i) if flags & 0x80 else (b"", i)
        pw, i = _take_str(body, i) if flags & 0x40 else (b"", i)
        self.fake.client_ids.append(client_id.decode())
        time.sleep(self.fake.connack_delay)
        code = self.fake.connack_code
        if code is None:
            code = 0 if (user.decode(), pw.decode()) == (self.fake.username, self.fake.password) else 4
        self.send(_packet(0x20, bytes([0, code])))
        return code == 0

    def handle(self, ptype, flags, body):
        if ptype == 8:  # SUBSCRIBE
            topic, _ = _take_str(body, 2)
            self.fake.subscriptions.append(topic.decode())
            self.subscribed = True
            self.send(_packet(0x90, body[:2] + bytes([self.fake.suback_code])))
        elif ptype == 3:
            topic, i = _take_str(body, 0)
            if (flags >> 1) & 3:
                i += 2
            self.fake._on_publish(topic.decode(), body[i:])
        elif ptype == 12:
            self.fake.pings += 1
            if self.fake.answer_pings:
                self.send(_packet(0xD0, b""))
        elif ptype == 14:
            self.fake.disconnects += 1
            return False
        return True


class FakeKobra:
    def __init__(self, tls=None):
        self.host, self.tls = "127.0.0.1", tls
        self.token = os.urandom(16).hex()
        self.username, self.password = "userX", "pw-" + os.urandom(6).hex()
        self.device_id, self.mode_id, self.model = "dev" + os.urandom(4).hex(), "20030", "Anycubic Kobra X"
        self.upload_token = os.urandom(8).hex()
        self.info_answer = self.ctrl_answer = self.info_redirect = None
        self.upload_answer = None
        self.print_start = None
        self.connack_code, self.suback_code, self.answer_pings, self.chunk_size = None, 0, True, None
        self.connack_delay = 0.0
        self.send_ack, self.ack_only, self.echo_msgid = True, False, False
        self.replies, self.requests, self.uploads, self.ctrl_calls = {}, [], [], []
        self.client_ids, self.subscriptions, self.disconnects, self.pings = [], [], 0, 0
        self._sessions, self._cond = [], threading.Condition()

    # lifecycle -----------------------------------------------------------------------------
    def start(self):
        self._http = ThreadingHTTPServer((self.host, 0), self._handler())
        self._http.daemon_threads = True
        self.http_port = self._http.server_address[1]
        self._listener = socket.create_server((self.host, 0))
        self.mqtt_port = self._listener.getsockname()[1]
        for target in (lambda: self._http.serve_forever(0.05), self._accept):
            threading.Thread(target=target, daemon=True, name="kobracontrol-fake").start()
        return self

    def stop(self):
        self._http.shutdown()
        self._http.server_close()
        self._listener.close()
        self.drop_clients()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def upload_url(self):
        return "http://%s:%d/gcode_upload?s=%s" % (self.host, self.http_port, self.upload_token)

    # MQTT ------------------------------------------------------------------------------------
    def _accept(self):
        ctx = None
        if self.tls:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(self.tls.server_cert, self.tls.server_key)
            ctx.verify_mode = ssl.CERT_REQUIRED
            ctx.load_verify_locations(self.tls.client_cert)
        while True:
            try:
                sock, _ = self._listener.accept()
            except OSError:
                return
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(target=self._serve, args=(sock, ctx), daemon=True, name="kobracontrol-fake-conn").start()

    def _serve(self, sock, ctx):
        try:
            sock = ctx.wrap_socket(sock, server_side=True) if ctx else sock
        except (OSError, ssl.SSLError):
            sock.close()
            return
        session = _Session(self, sock)
        with self._cond:
            self._sessions.append(session)
        session.run()

    def _forget(self, session):
        with self._cond:
            if session in self._sessions:
                self._sessions.remove(session)

    def _on_publish(self, topic, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            msg = None
        with self._cond:
            self.requests.append({"topic": topic, "raw": raw, "msg": msg})
            self._cond.notify_all()
        if not isinstance(msg, dict):
            return
        if self.send_ack:
            self.report("response", {"type": "", "action": "", "state": "", "code": 0, "msg": "", "data": None,
                                     "timestamp": 0, "msgid": msg.get("msgid")})
        if (msg.get("type"), msg.get("action")) == ("print", "start") and self.print_start:
            threading.Thread(target=self._print_sequence, args=(msg,), daemon=True, name="kobracontrol-fake-print").start()
            return
        reply = self.replies.get((msg.get("type"), msg.get("action")))
        out = reply(msg) if callable(reply) else reply
        if out is not None and not self.ack_only:
            msgid = out["msgid"] if "msgid" in out else (msg.get("msgid") if self.echo_msgid else str(uuid.uuid4()))
            self.report("%s/report" % msg["type"], {**out, "msgid": msgid})

    PRINT_SEQUENCES = {
        "ok": [("start", "checking", 200, "done"), ("start", "printing", 200, "done"),
               ("start", "hotbed_heating", 200, "done")],
        "abnormal": [("start", "checking", 200, "done"), ("start", "printing", 200, "done"),
                     ("stop", "stopping", 200, "done"), ("stop", "stoped", 10111, "abnormal end of task")],
        "quiet": [("start", "checking", 200, "done"), ("start", "printing", 200, "done")],
    }

    def _print_sequence(self, msg):
        name = "/" + str((msg.get("data") or {}).get("filename", ""))
        for action, state, code, text in self.PRINT_SEQUENCES[self.print_start]:
            time.sleep(0.05)
            self.report("print/report", {"type": "print", "action": action, "state": state, "code": code, "msg": text,
                                         "msgid": str(uuid.uuid4()),
                                         "data": {"filename": name, "file_root_path": name, "progress": 0, "taskid": "-1"}})

    def reply(self, type_, action, data=None, state="done", code=200, **fields):
        reported = "report" if (type_, action) == ("info", "query") else action
        body = {"type": type_, "action": reported, "state": state, "data": data, "msg": "done", **fields}
        if code is not None:
            body["code"] = code
        self.replies[(type_, action)] = body

    def report(self, suffix, payload):
        raw = payload if isinstance(payload, bytes) else json.dumps(
            {"timestamp": int(time.time() * 1000), **payload}).encode()
        self.publish_raw("anycubic/anycubicCloud/v1/printer/public/%s/%s/%s" % (self.mode_id, self.device_id, suffix), raw)

    def publish_raw(self, topic, payload):
        packet = _packet(0x30, _s(topic) + payload)
        with self._cond:
            targets = [s for s in self._sessions if s.subscribed]
        for session in targets:
            try:
                session.send(packet)
            except OSError:
                pass

    def drop_clients(self):
        with self._cond:
            sessions = list(self._sessions)
        for session in sessions:
            try:
                session.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def wait_request(self, type_, action, timeout=5):
        def find():
            return next((r["msg"] for r in self.requests if isinstance(r["msg"], dict)
                         and (r["msg"].get("type"), r["msg"].get("action")) == (type_, action)), None)
        with self._cond:
            self._cond.wait_for(lambda: find() is not None, timeout)
            return find()

    def wait_subscribed(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._cond:
                if any(s.subscribed for s in self._sessions):
                    return True
            time.sleep(0.01)
        return False

    # HTTP ------------------------------------------------------------------------------------
    def _ctrl(self, query):
        self.ctrl_calls.append(query)
        if self.ctrl_answer is not None:
            return 200, self.ctrl_answer
        sign = hashlib.md5((hashlib.md5(self.token[:16].encode()).hexdigest() + query.get("ts", "") +
                            query.get("nonce", "")).encode()).hexdigest()
        if query.get("sign") != sign:
            return 403, {"code": 403, "msg": "bad sign"}
        iv = os.urandom(8).hex()
        plain = json.dumps({"ip": self.host, "username": self.username, "password": self.password,
                            "deviceId": self.device_id, "modeId": self.mode_id, "modelName": self.model}).encode()
        enc = aes.encrypt_cbc(self.token[16:32].encode(), iv.encode(), plain)
        return 200, {"code": 200, "data": {"info": base64.b64encode(enc).decode(), "token": iv}}

    def _upload(self, query, headers, body):
        if query.get("s") != self.upload_token:
            return 403, {"code": 403, "message": "bad token"}
        boundary = headers.get("Content-Type", "").split("boundary=")[-1].encode()
        fields = {}
        for part in body.split(b"--" + boundary)[1:-1]:
            head, _, content = part[2:].partition(b"\r\n\r\n")
            name = head.split(b'name="')[1].split(b'"')[0].decode()
            fields[name] = content[:-2]
        self.uploads.append({"filename": fields.get("filename", b"").decode(), "data": fields.get("gcode"),
                             "headers": dict(headers)})
        if self.upload_answer is not None:
            return 200, self.upload_answer
        return 200, {"code": 200, "data": {"gcode": self.uploads[-1]["filename"]}, "message": "success"}

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle(self):
                # A client that gave up (a test's short timeout, a refused redirect) may be gone before the
                # answer is written; on Windows that is WinError 10054 printed by socketserver. Not a failure.
                try:
                    super().handle()
                except ConnectionError:
                    pass

            def answer(self, status, body):
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == "/info" and fake.info_redirect:
                    self.send_response(302)
                    self.send_header("Location", fake.info_redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.path == "/info":
                    self.answer(200, fake.info_answer if fake.info_answer is not None else {"token": fake.token})
                else:
                    self.answer(404, {"code": 404})

            def do_POST(self):
                url = urllib.parse.urlsplit(self.path)
                query = dict(urllib.parse.parse_qsl(url.query))
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                if len(body) < length:  # client gave up mid-upload
                    return
                if url.path == "/ctrl":
                    self.answer(*fake._ctrl(query))
                elif url.path == "/gcode_upload":
                    self.answer(*fake._upload(query, self.headers, body))
                else:
                    self.answer(404, {"code": 404})

        return Handler
