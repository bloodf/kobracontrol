"""Upload-and-Print bridge (opt-in, off by default): a minimal OctoPrint-compatible HTTP server on 127.0.0.1 only,
so OrcaSlicer's OctoPrint host type can Upload and Upload-and-Print to the Kobra X through this plugin. Free of the
`orca` module.

OrcaSlicer's client (src/slic3r/Utils/OctoPrint.cpp): GET /api/version must answer JSON with "api" and a "text"
starting with "OctoPrint"; POST /api/files/local is multipart/form-data with the fields "print" ("true"/"false"),
"path", "plateindex" (optional) and the "file" part; both send the key in the X-Api-Key header. A failed request's
body is shown to the user, so refusals say why in plain words.

Guards: bound to 127.0.0.1 (never all interfaces); every request needs the key (compared in constant time) and a
Host header naming 127.0.0.1 or localhost (DNS rebinding); no CORS headers, so a web page can't send the key;
one request at a time, a request budget per minute and a lockout after repeated wrong keys; uploads capped at
UPLOAD_MAX. The log names files and outcomes only, never the key or headers."""

import collections
import glob
import hmac
import http.server
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import tempfile
import threading
import time

from i18n import tr

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
KEY_FILE = "bridge_key.txt"
UPLOAD_MAX = 1024 ** 3          # the G-code limit of a print job (jobs.GCODE_MAX)
FIELD_MAX = 1024                # bytes of a form field other than the file
REQUESTS_PER_MINUTE = 30
WRONG_KEYS_PER_MINUTE = 5
SOCKET_TIMEOUT = 30.0           # s per read once the request is admitted
HEADER_TIMEOUT = 5.0            # s per read before that
HEADER_DEADLINE = 10.0          # s for the request line and all headers together
DRAIN_MAX = 64 * 1024           # bytes of a refused request's body read before answering
PARTS_MAX = 16
VERSION = {"api": "0.1", "server": "1.0.0", "text": "OctoPrint 1.0.0 (Kobra Control bridge)"}
CHUNK = 64 * 1024


class Refused(Exception):
    """An upload refused with an HTTP status and a message for the user."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------------- the key

def new_key():
    return secrets.token_urlsafe(24)


def read_key(folder):
    try:
        with open(os.path.join(folder, KEY_FILE), encoding="ascii") as f:
            key = f.read().strip()
    except (OSError, ValueError):
        return ""
    return key if re.fullmatch(r"[\w-]{20,}", key) else ""


def write_key(folder, key):
    """The key in its own file, readable by the user only (0600; created that way, never widened)."""
    fd, tmp = tempfile.mkstemp(prefix="bridge_key-", dir=folder)   # created 0600
    try:
        try:   # os.write, not os.fdopen: a file object on a descriptor is an audited "open" without a path
            os.write(fd, key.encode("ascii"))
        finally:
            os.close(fd)
        os.replace(tmp, os.path.join(folder, KEY_FILE))   # a reader sees the old key or the new one, never an empty file
    except BaseException:
        os.remove(tmp)
        raise
    return key


def key_for(folder):
    """The saved key, a new saved one when there is none."""
    return read_key(folder) or write_key(folder, new_key())


# ---------------------------------------------------------------------- multipart, streamed

class _Body:
    """The request body: at most `length` bytes of rfile, with bytes pushed back."""

    def __init__(self, rfile, length):
        self.rfile, self.left, self.back, self.at = rfile, length, b"", 0

    def push(self, data):
        self.back, self.at = data + self.back[self.at:], 0

    def read(self, n):
        if self.at < len(self.back):
            out = self.back[self.at:self.at + n]
            self.at += len(out)
            return out
        data = self.rfile.read(min(n, self.left)) if self.left > 0 else b""
        self.left -= len(data)
        return data

    def readline(self, limit):
        out = b""
        while not out.endswith(b"\n") and len(out) < limit:
            data = self.read(1)
            if not data:
                break
            out += data
        return out


def _disposition(headers):
    text = headers.get("content-disposition", "")
    name = re.search(r'\bname="([^"]*)"', text)
    filename = re.search(r'\bfilename="([^"]*)"', text)
    return (name.group(1) if name else ""), (filename.group(1) if filename else None)


def _part_headers(body):
    headers = {}
    for _ in range(16):
        line = body.readline(FIELD_MAX)
        if line in (b"\r\n", b"\n"):
            return headers
        if not line.endswith(b"\n"):
            break
        key, _, value = line.decode("utf-8", "replace").partition(":")
        headers[key.strip().lower()] = value.strip()
    raise Refused(400, tr("malformed upload"))


def _copy_part(body, delim, sink, cap):
    """Copy the part's data to sink up to the delimiter; returns the bytes written."""
    buf, written = b"", 0
    while True:
        chunk = body.read(CHUNK)
        if not chunk:
            raise Refused(400, tr("the upload ended early"))
        buf += chunk
        i = buf.find(delim)
        if i >= 0:
            written += i
            if written > cap:
                raise Refused(413, tr("the upload is too large"))
            sink(buf[:i])
            body.push(buf[i + len(delim):])
            return written
        keep = len(buf) - len(delim) + 1
        if keep > 0:
            written += keep
            if written > cap:
                raise Refused(413, tr("the upload is too large"))
            sink(buf[:keep])
            buf = buf[keep:]


def parse_upload(rfile, length, boundary, open_file):
    """(fields, filename) of a multipart body; the "file" part streams to open_file(), a writable binary file."""
    body = _Body(rfile, length)
    marker = b"--" + boundary
    if body.readline(len(marker) + 4).rstrip(b"\r\n") != marker:
        raise Refused(400, tr("malformed upload"))
    fields, filename, delim = {}, None, b"\r\n" + marker
    for _ in range(PARTS_MAX):
        name, part_file = _disposition(_part_headers(body))
        if name == "file" and part_file is not None and filename is None:
            filename, out = part_file, open_file()
            _copy_part(body, delim, out.write, UPLOAD_MAX)
        else:
            value = []
            _copy_part(body, delim, value.append, FIELD_MAX)
            fields[name] = b"".join(value).decode("utf-8", "replace")
        tail = body.read(2)
        if tail == b"--":
            return fields, filename
        if tail != b"\r\n":
            break
    raise Refused(400, tr("malformed upload"))


# ---------------------------------------------------------------------- the server

class _Limiter:
    def __init__(self, clock=time.monotonic):
        self.clock, self.requests, self.wrong = clock, collections.deque(), collections.deque()

    def _recent(self, events):
        while events and self.clock() - events[0] > 60.0:
            events.popleft()
        return events

    def allow(self):
        if len(self._recent(self.wrong)) >= WRONG_KEYS_PER_MINUTE or len(self._recent(self.requests)) >= REQUESTS_PER_MINUTE:
            return False
        self.requests.append(self.clock())
        return True

    def wrong_key(self):
        self.wrong.append(self.clock())


class _Server(http.server.HTTPServer):
    allow_reuse_address = os.name != "nt"   # on Windows SO_REUSEADDR would let another program take the port

    log = print

    def handle_error(self, request, client_address):   # one line in the plugin log, not a traceback on stderr
        self.log("kobracontrol: upload bridge request ended early: %r" % (sys.exc_info()[1],))

    def server_bind(self):   # HTTPServer's own also looks up the host name (socket.getfqdn): not needed here
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = HOST, self.server_address[1]


class Bridge:
    """The server. on_upload(path, filename, plate_index, start) stores the file on the printer and returns a
    message for OrcaSlicer, or raises Refused. key() returns the current key. start() binds on the caller's
    thread (OrcaSlicer asks for the network permission there) and serves on a thread of its own."""

    def __init__(self, port, key, on_upload, work_dir, log=print):
        self.port, self.key, self.on_upload, self.work_dir, self.log = port, key, on_upload, work_dir, log
        self.limiter = _Limiter()
        self.server = None
        self.thread = None

    def start(self):
        for stale in glob.glob(os.path.join(glob.escape(self.work_dir), "bridge-*.part")):   # left by a crash
            try:
                os.remove(stale)
            except OSError:
                pass
        bridge = self

        class Handler(_Handler):
            owner = bridge
        self.server = _Server((HOST, self.port), Handler)   # one request at a time
        self.server.log = self.log
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="kobracontrol-bridge", daemon=True)
        self.thread.start()
        self.log("kobracontrol: upload bridge listening on %s:%d" % (HOST, self.port))
        return self

    def stop(self):
        server, self.server = self.server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        self.log("kobracontrol: upload bridge stopped")


class _Handler(http.server.BaseHTTPRequestHandler):
    owner = None
    timeout = HEADER_TIMEOUT
    server_version = "KobraControlBridge"
    sys_version = ""

    def log_message(self, fmt, *args):   # the default logs every request line and address to stderr
        pass

    def setup(self):
        super().setup()
        # one deadline for the whole request line and headers: a client sending a byte every few seconds can't hold
        # the only slot; cancelled once the request is admitted
        self._deadline = threading.Timer(HEADER_DEADLINE, self._expire)
        self._deadline.daemon = True
        self._deadline.start()

    def _expire(self):
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def finish(self):
        self._deadline.cancel()
        super().finish()

    def _drain(self):
        """Read (and drop) up to DRAIN_MAX of a refused request's body, so the client reads the answer instead of a
        connection reset."""
        try:
            left = min(int(self.headers.get("Content-Length") or 0), DRAIN_MAX)
            while left > 0:
                data = self.rfile.read(min(left, CHUNK))
                if not data:
                    break
                left -= len(data)
        except (OSError, ValueError):
            pass

    def _answer(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _refuse(self, status, message):
        if self.command == "POST" and not getattr(self, "_reading", False):
            self._drain()
        self._answer(status, {"error": message})

    def _admitted(self):
        """Host, rate and key checks for every request; answers the refusal itself."""
        owner = self.owner
        if self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"):   # a browser; OrcaSlicer sends neither
            self._refuse(403, tr("requests from web pages are not accepted"))
            return False
        host = (self.headers.get("Host") or "").strip().lower()
        if host not in ("%s:%d" % (HOST, owner.port), "localhost:%d" % owner.port):
            self._refuse(403, tr("use http://127.0.0.1:%d as the OctoPrint host") % owner.port)
            return False
        if not owner.limiter.allow():
            self._refuse(429, tr("too many requests; wait a minute"))
            return False
        key = (self.headers.get("X-Api-Key") or "").encode()
        expected = (owner.key() or "").encode()
        if not expected or not hmac.compare_digest(key, expected):
            owner.limiter.wrong_key()
            self._refuse(403, tr("invalid API key: copy it from Kobra Control > Settings > Upload bridge"))
            return False
        self._deadline.cancel()
        self.connection.settimeout(SOCKET_TIMEOUT)
        return True

    def do_GET(self):
        if not self._admitted():
            return
        if self.path.split("?", 1)[0] == "/api/version":
            self._answer(200, VERSION)
        else:
            self._refuse(404, tr("not found"))

    def do_POST(self):
        if not self._admitted():
            return
        if self.path.split("?", 1)[0] != "/api/files/local":
            self._refuse(404, tr("not found"))
            return
        try:
            self._answer(201, self._upload())
        except Refused as e:
            self.owner.log("kobracontrol: upload bridge refused an upload (%d): %s" % (e.status, e))
            self._refuse(e.status, str(e))
        except Exception as e:   # never leave OrcaSlicer without an answer; details to the log
            self.owner.log("kobracontrol: upload bridge failed: %r" % e)
            self._refuse(500, tr("upload failed: %s") % tr("see the OrcaSlicer log"))

    def _upload(self):
        owner = self.owner
        try:
            length = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            length = -1
        if length < 0:
            raise Refused(411, tr("the upload needs a Content-Length"))
        if length > UPLOAD_MAX + 64 * 1024:
            raise Refused(413, tr("the upload is too large"))
        m = re.match(r'multipart/form-data;.*\bboundary="?([^";]{1,70})"?', self.headers.get("Content-Type") or "", re.I)
        if not m:
            raise Refused(415, tr("expected multipart/form-data"))
        fd, path = tempfile.mkstemp(prefix="bridge-", suffix=".part", dir=owner.work_dir)
        os.close(fd)   # reopened by path: os.fdopen would be an audited "open" without a path OrcaSlicer can show
        self._reading = True   # the body is being read: a refusal from here on can't drain what is left
        try:
            with open(path, "wb") as out:
                fields, filename = parse_upload(self.rfile, length, m.group(1).encode(), lambda: out)
            if not filename:
                raise Refused(400, tr("the upload has no file"))
            start = fields.get("print", "").strip().lower() == "true"
            plate = fields.get("plateindex", "").strip()
            plate = plate if re.fullmatch(r"[0-9]{1,3}", plate) else ""
            owner.log("kobracontrol: upload bridge received %r (%d bytes, print %s)" % (filename, os.path.getsize(path),
                                                                                      "asked" if start else "no"))
            result = owner.on_upload(path, os.path.basename(filename.replace("\\", "/")),
                                     int(plate) if plate else 1, start)
        finally:
            os.remove(path)
        return {"done": True, "files": {"local": {"name": result["name"], "origin": "local"}}, **result}
