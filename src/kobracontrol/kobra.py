"""Anycubic Kobra X LAN protocol (ported from Kobralink, GPL-3.0): credentials, MQTT commands, upload, state.

`fetch_credentials(ip)` -> Credentials; `Printer(creds, ssl_context=certs.context(...))` talks MQTT;
`Printer.upload(...)` + `Printer.start_print(print_file_payload(...))` print a file; `State` folds reports.

State.view() returns one JSON-serialisable dict with exactly these keys (VIEW_KEYS):
  connected        bool, set by the owner through `State.connected`
  state            "offline|idle|printing|paused|finished|cancelled|error|busy" (normalised)
  kobra_state      raw printer state ("free", "printing", "pause", "stoped", ...; "" before any report)
  printer_name, model, firmware                       str ("" when unknown; model from the constructor
                                                      unless info/report carries model/modelName)
  filename         str, current job ("" when idle or after a terminal state)
  progress         number 0-100 as reported (pre-print phases keep the previous value)
  layer, total_layers, elapsed_s, remaining_s         numbers (printer reports minutes; converted to s)
  task_id          str ("" unknown; pass it to pause/resume/stop and print/update helpers)
  nozzle_temp, nozzle_target, bed_temp, bed_target    numbers, deg C
  fan_pct          number 0-100; light_on bool; light_brightness number; speed_mode number (printer's code)
  multi_color_box  raw list from multiColorBox/report (ACE units and slots); head_tools_model raw value
  files            [{"filename", "size", "timestamp"}] newest first (file/report listLocal, code 200)
  file_details     raw dict of the last file/report file_details (thumbnail, objects_skip_parts, ...)
  upload_url       info urls.fileUploadurl ("" until announced); camera_url urls.rtspUrl
  camera_urls      every info url except fileUploadurl; camera_active bool (video/report, unconfirmed)
  storage          {"total", "used"} from info storage or buried/report storage_total/used, else {}
  skipped_objects  [str]; pause_reason {"code", "msg"} or None; last_error {"report", "action",
                   "code", "msg"} of the last report with state "failed", or None
  updated_at       time.time() of the last applied report (0.0 before)
"""

import base64
import copy
import hashlib
import http.client
import json
import logging
import math
import os
import secrets
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass

import aes
import mqtt

log = logging.getLogger(__name__)
UPLOAD_CHUNK = 256 * 1024
BOUNDARY = "------------------------a3a050b927d92a4c"
PRE_PRINT = {"preheating", "auto_leveling", "checking", "updated", "init", "hotbed_heating", "nozzle_heating",
             "nozzle_cooling", "nozzle_cooling_off", "hotbed_cooling_off", "nozzle_purging", "nozzle_wiping",
             "frequency_sweeping", "z_offset_calibrating", "extfilbox_filament_feeding"}
PRINTING = PRE_PRINT | {"printing", "resuming", "resumed"}
PAUSED = {"pausing", "paused", "pause"}
TERMINAL = {"finished", "stoped", "canceled"}


class KobraError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Cancelled(KobraError):
    pass


@dataclass(frozen=True)
class Credentials:
    ip: str
    username: str
    password: str
    device_id: str
    mode_id: str = "20030"
    model: str = "Anycubic Kobra"

    def __repr__(self):
        return "Credentials(ip=%r, username=%r, password='***', device_id=%r, mode_id=%r, model=%r)" % (
            self.ip, self.username, self.device_id, self.mode_id, self.model)


# credentials ----------------------------------------------------------------------------------
def _http_json(url, timeout, what, post=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # LAN only: never via a proxy
    req = urllib.request.Request(url, data=b"" if post else None, method="POST" if post else "GET")
    try:
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        e.close()
        raise KobraError("%s answered HTTP %d" % (what, e.code)) from None
    except (urllib.error.URLError, OSError) as e:
        host = urllib.parse.urlsplit(url).netloc
        raise KobraError("printer not reachable at %s (%s)" % (host, getattr(e, "reason", e))) from None
    try:
        return json.loads(body)
    except ValueError:
        raise KobraError("bad answer from %s (not JSON)" % what) from None


def fetch_credentials(ip, port=18910, timeout=10):
    base = "http://%s:%d" % (ip, port)
    info = _http_json(base + "/info", timeout, "/info")
    token = info.get("token") if isinstance(info, dict) else None
    if not isinstance(token, str) or len(token) < 32:
        raise KobraError("/info gave no token: is LAN mode enabled on the printer?")
    ts = str(int(time.time() * 1000))
    nonce = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(6))
    sign = _md5(_md5(token[:16]) + ts + nonce)
    query = urllib.parse.urlencode({"ts": ts, "nonce": nonce, "sign": sign, "did": "random"})
    ctrl = _http_json(base + "/ctrl?" + query, timeout, "/ctrl", post=True)
    data = ctrl.get("data") if isinstance(ctrl, dict) else None
    if not (isinstance(data, dict) and isinstance(data.get("info"), str) and isinstance(data.get("token"), str)):
        raise KobraError("unexpected /ctrl answer from the printer")
    try:
        plain = aes.decrypt_cbc(token[16:32].encode(), data["token"].encode(), base64.b64decode(data["info"]))
        result = json.loads(plain.decode("utf-8"))
    except (ValueError, UnicodeError):
        result = None
    if not isinstance(result, dict):
        raise KobraError("could not decrypt the printer credentials")
    if result.get("error"):
        raise KobraError("printer refused LAN access: %s" % result["error"])
    return Credentials(str(result.get("ip") or ip), str(result.get("username", "")), str(result.get("password", "")),
                       str(result.get("deviceId", "")), str(result.get("modeId") or "20030"),
                       str(result.get("modelName") or "Anycubic Kobra"))


def _md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def _round(x):
    return math.floor(x + 0.5)  # JavaScript Math.round, as Kobralink sends


# printer ------------------------------------------------------------------------------------------
class _Pending:
    def __init__(self, msgid, report_key, action):
        self.msgid, self.report_key, self.action = msgid, report_key, action
        self.event, self.reply = threading.Event(), None


class Printer:
    def __init__(self, creds, ssl_context=None, mqtt_port=9883, http_port=18910, on_report=None,
                 on_disconnect=None, timeout=8):
        """ssl_context: certs.context(...) for a real printer; None means plain TCP (tests only)."""
        self.creds, self.ssl_context, self.mqtt_port, self.http_port = creds, ssl_context, mqtt_port, http_port
        self.on_report, self.on_disconnect, self.timeout = on_report, on_disconnect, timeout
        self.client_id = "kobracontrol_" + secrets.token_hex(4)
        self._client = None
        self._lock = threading.Lock()
        self._by_id, self._by_report = {}, {}

    @property
    def connected(self):
        client = self._client
        return bool(client and client.connected)

    def _topic(self, kind, type_):
        return "anycubic/anycubicCloud/v1/%s/printer/%s/%s/%s" % (kind, self.creds.mode_id, self.creds.device_id, type_)

    def connect(self):
        self.close()
        c = self.creds
        client = mqtt.Client(c.ip, self.mqtt_port, self.client_id, username=c.username, password=c.password,
                             ssl_context=self.ssl_context, keepalive=60, timeout=self.timeout,
                             on_message=self._on_message)
        client.on_close = lambda reason: self._closed(client, reason)
        try:
            client.connect()
            client.subscribe("anycubic/anycubicCloud/v1/printer/public/%s/%s/#" % (c.mode_id, c.device_id))
        except mqtt.MqttError as e:
            client.close()
            raise KobraError("MQTT %s:%d: %s" % (c.ip, self.mqtt_port, e), code=e.code) from None
        self._client = client

    def close(self):
        client, self._client = self._client, None
        if client:
            client.close()
        self._fail_pending()

    def _closed(self, client, reason):
        if client is not self._client:
            return
        self._fail_pending()
        self._emit(self.on_disconnect, reason)

    def _fail_pending(self):
        with self._lock:
            pending = list(self._by_id.values())
        for p in pending:
            self._resolve(p, None)

    def _resolve(self, p, payload):
        with self._lock:
            self._by_id.pop(p.msgid, None)
            if self._by_report.get(p.report_key) is p:
                del self._by_report[p.report_key]
            if not p.event.is_set():
                p.reply = payload
                p.event.set()

    def _emit(self, callback, *args):
        if callback:
            try:
                callback(*args)
            except Exception:
                log.exception("Kobra callback failed")

    def _on_message(self, topic, raw):
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        suffix = "/".join(topic.split("/")[-2:])
        msgid = payload.get("msgid")
        with self._lock:
            by_report, by_id = self._by_report.get(suffix), self._by_id.get(msgid) if msgid else None
        if by_report and (not msgid or by_report.msgid == msgid or
                          (by_report.action and by_report.action == payload.get("action"))):
            self._resolve(by_report, payload)
        if by_id and (not by_id.action or suffix == by_id.report_key):
            self._resolve(by_id, payload)
        self._emit(self.on_report, suffix, payload)

    def _publish(self, kind, type_, action, data, msgid=None):
        client = self._client
        if not (client and client.connected):
            return False
        body = {"type": type_, "action": action, "msgid": msgid or str(uuid.uuid4()),
                "timestamp": int(time.time() * 1000), "data": data}
        try:
            client.publish(self._topic(kind, type_), json.dumps(body))
            return True
        except mqtt.MqttError:
            return False

    def request(self, type_, action, data=None, timeout=5, match_action=False):
        """Publish and wait for the reply (matched by msgid or by `<type>/report`); None on timeout."""
        if not self.connected:
            return None
        p = _Pending(str(uuid.uuid4()), type_ + "/report", action if match_action else None)
        with self._lock:
            self._by_id[p.msgid] = p
            self._by_report.setdefault(p.report_key, p)
        try:
            if self._publish("slicer", type_, action, data, p.msgid):
                p.event.wait(max(timeout, 0.001))
        finally:
            self._resolve(p, None)
        return p.reply

    def send(self, type_, action, data=None):
        return self._publish("slicer", type_, action, data)

    def publish_web(self, type_, action, data=None):
        return self._publish("web", type_, action, data)

    # command helpers (Kobralink names in snake_case) --------------------------------------------
    def query_info(self):
        return self.request("info", "query")

    def query_status(self):
        return self.request("status", "query")

    def query_print(self, timeout=3):
        return self.request("print", "query", timeout=timeout)

    def query_multi_color_box(self):
        return self.request("multiColorBox", "getInfo")

    def pause_print(self, taskid="-1"):
        return self.request("print", "pause", {"taskid": taskid})

    def resume_print(self, taskid="-1"):
        return self.request("print", "resume", {"taskid": taskid})

    def stop_print(self, taskid="-1"):
        return self.request("print", "stop", {"taskid": taskid})

    def start_camera(self):
        return self.request("video", "startCapture", timeout=8)

    def stop_camera(self):
        return self.request("video", "stopCapture")

    def set_fan(self, pct):
        return self.send("fan", "setSpeed", {"fan_speed_pct": pct})

    def set_light(self, on, brightness=80):
        return self.send("light", "control", {"type": 3, "status": 1 if on else 0, "brightness": brightness})

    def set_print_speed_mode(self, taskid, mode):
        return self.publish_web("print", "update", {"taskid": taskid, "settings": {"print_speed_mode": mode}})

    def set_idle_temperature(self, nozzle=None, bed=None):
        if nozzle is None and bed is None:
            return False
        kind = 2 if nozzle is not None and bed is not None else (0 if nozzle is not None else 1)
        return self.publish_web("tempature", "set", {"type": kind, "target_nozzle_temp": _round(nozzle or 0),
                                                     "target_hotbed_temp": _round(bed or 0)})

    def set_printing_temperature(self, taskid, nozzle=None, bed=None):
        for key, value in (("target_nozzle_temp", nozzle), ("target_hotbed_temp", bed)):
            if value is not None:
                self.publish_web("print", "update", {"taskid": taskid, "settings": {key: _round(value)}})

    def move_axis(self, axis, move_type, distance=0):
        timeout = 30 if move_type == 2 else 5
        return self.request("axis", "move", {"axis": axis, "move_type": move_type, "distance": distance},
                            timeout, match_action=True)

    def disable_steppers(self):
        return self.send("axis", "turnOff")

    def set_ams_slot_info(self, box_id, local_slot, type_, color):
        slot = {"index": local_slot, "type": type_, "color": list(color)}
        return self.publish_web("multiColorBox", "setInfo", {"multi_color_box": [{"id": box_id, "slots": [slot]}]})

    def feed_filament(self, box_id, local_slot, type_):
        return self.send("multiColorBox", "feedFilament", {
            "multi_color_box": [{"id": box_id, "feed_status": {"slot_index": local_slot, "type": type_}}]})

    def set_auto_feed(self, ace_id, on):
        return self.send("multiColorBox", "setAutoFeed", {"multi_color_box": [{"id": ace_id, "auto_feed": 1 if on else 0}]})

    def set_dry(self, ace_ids, drying):
        return self.send("multiColorBox", "setDry",
                         {"multi_color_box": [{"id": i, "drying_status": dict(drying)} for i in ace_ids]})

    def query_skip_objects(self):
        return self.request("skip", "query_obj", timeout=3)

    def skip_objects(self, names):
        return self.request("skip", "start", {"objects_skip_parts": list(names)})

    def list_local_files(self):
        return self.send("file", "listLocal", {"page_num": 1, "page_size": 1000, "path": "/"})

    def delete_local_files(self, filenames):
        return self.send("file", "deleteBatch", {"root": "local", "files": [{"path": "/", "filename": f} for f in filenames]})

    def request_file_details(self, filename):
        return self.send("file", "fileDetails", {"root": "local", "filename": filename})

    def start_print(self, payload, timeout=15):
        reply = self.request("print", "start", payload, timeout)
        if reply is None:
            raise KobraError("the printer gave no answer to print/start")
        code = reply.get("code")
        if reply.get("state") == "failed" or (code is not None and code != 0):
            detail = reply.get("msg") or json.dumps(reply.get("data"))
            raise KobraError("the printer refused the print (code %s): %s" % ("?" if code is None else code, detail),
                             code=code)
        return reply

    # upload ------------------------------------------------------------------------------------------
    def upload(self, filename, source_path, upload_url, progress=None, cancelled=None):
        """Stream source_path to the printer as `filename`; returns the printer's JSON answer."""
        if not filename or any(ch in filename for ch in '"\r\n'):
            raise KobraError("unsupported file name for the printer")
        idx = upload_url.find("?s=")
        if idx < 0:
            raise KobraError("the printer's upload URL has no session token")
        total = os.path.getsize(source_path)
        head = ("--{b}\r\nContent-Disposition: form-data; name=\"filename\"\r\n\r\n{f}\r\n--{b}\r\n"
                "Content-Disposition: form-data; name=\"gcode\"; filename=\"{f}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").format(b=BOUNDARY, f=filename).encode()
        tail = ("\r\n--%s--\r\n" % BOUNDARY).encode()
        conn = http.client.HTTPConnection(self.creds.ip, self.http_port, timeout=30)
        try:
            conn.putrequest("POST", "/gcode_upload?s=" + upload_url[idx + 3:], skip_host=True, skip_accept_encoding=True)
            for key, value in self._upload_headers(total, len(head) + total + len(tail)):
                conn.putheader(key, value)
            conn.endheaders()
            conn.send(head)
            self._stream(conn, source_path, total, progress, cancelled)
            conn.send(tail)
            conn.sock.settimeout(180)  # the printer answers after writing the file to its storage
            resp = conn.getresponse()
            status, body = resp.status, resp.read()
        except OSError as e:
            raise KobraError("upload to the printer failed (%s)" % e) from None
        finally:
            conn.close()
        if status != 200:
            raise KobraError("the printer refused the upload: HTTP %d" % status)
        try:
            return json.loads(body)
        except ValueError:
            raise KobraError("unexpected upload answer: %r" % body[:200]) from None

    def _upload_headers(self, file_size, body_size):
        return [("Host", "%s:%d" % (self.creds.ip, self.http_port)), ("User-Agent", "AnycubicSlicerNext/1.3.9.4"),
                ("Accept", "*/*"), ("X-BBL-Client-Name", "AnycubicSlicerNext"), ("X-BBL-Client-Type", "slicer"),
                ("X-BBL-Client-Version", "01.03.09.04"), ("X-BBL-Device-ID", str(uuid.uuid4())),
                ("X-BBL-Language", "en-US"), ("X-BBL-OS-Type", "windows"), ("X-BBL-OS-Version", "10.0.26200"),
                ("X-File-Length", str(file_size)), ("Content-Type", "multipart/form-data; boundary=" + BOUNDARY),
                ("Content-Length", str(body_size)), ("Connection", "close")]

    @staticmethod
    def _stream(conn, path, total, progress, cancelled):
        sent = 0
        with open(path, "rb") as f:
            while True:
                if cancelled and cancelled():
                    raise Cancelled("upload cancelled")
                chunk = f.read(UPLOAD_CHUNK)
                if not chunk:
                    return
                conn.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, total)


def print_file_payload(filename, size, mapping, task=None):
    """print/start data for a file already on the printer (Kobralink printPrinterFile).
    mapping: ams_box_mapping entries; task: {"auto_leveling", "vibration_compensation", "skip_parts"}."""
    task = task or {}
    return {
        "taskid": "-1", "url": "", "filename": filename, "md5": "", "filepath": "/" + filename,
        "filetype": 1, "project_type": 1, "filesize": size,
        "ams_settings": {"use_ams": bool(mapping), "ams_box_mapping": list(mapping)},
        "task_settings": {
            "auto_leveling": 1 if task.get("auto_leveling") else 0,
            "vibration_compensation": 1 if task.get("vibration_compensation") else 0,
            "flow_calibration": 0, "dry_mode": 0,
            "ai_settings": {"status": 0, "count": 0, "type": 1},
            "timelapse": {"status": 0, "count": 0, "type": 64},
            "drying_settings": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
            "model_objects_skip_parts": list(task.get("skip_parts") or []),
        },
    }



# state reducer -------------------------------------------------------------------------------------
VIEW_KEYS = ("connected", "state", "kobra_state", "printer_name", "model", "firmware", "filename", "progress",
             "layer", "total_layers", "elapsed_s", "remaining_s", "task_id", "nozzle_temp", "nozzle_target",
             "bed_temp", "bed_target", "fan_pct", "light_on", "light_brightness", "speed_mode", "multi_color_box",
             "head_tools_model", "files", "file_details", "upload_url", "camera_url", "camera_urls",
             "camera_active", "storage", "skipped_objects", "pause_reason", "last_error", "updated_at")


def normalise(kobra_state):
    if kobra_state in ("", "free"):
        return "idle"
    if kobra_state in PAUSED:
        return "paused"
    if kobra_state == "finished":
        return "finished"
    if kobra_state in ("stoped", "canceled"):
        return "cancelled"
    if kobra_state in ("failed", "offline"):
        return "error"
    return "printing" if kobra_state in PRINTING else "busy"


def _dict(value):
    return value if isinstance(value, dict) else {}


def _num(value, default=0):
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str(value):
    return value if isinstance(value, str) else ""


class State:
    """Folds report payloads into one view (see the module docstring). Thread-safe."""

    def __init__(self, model=""):
        self.connected = False
        self._lock = threading.Lock()
        self._v = {
            "kobra_state": "", "printer_name": "", "model": model, "firmware": "", "filename": "", "progress": 0,
            "layer": 0, "total_layers": 0, "elapsed_s": 0, "remaining_s": 0, "task_id": "", "nozzle_temp": 0,
            "nozzle_target": 0, "bed_temp": 0, "bed_target": 0, "fan_pct": 0, "light_on": False,
            "light_brightness": 80, "speed_mode": 0, "multi_color_box": [], "head_tools_model": None, "files": [],
            "file_details": {}, "upload_url": "", "camera_url": "", "camera_urls": {}, "camera_active": False,
            "storage": {}, "skipped_objects": [], "pause_reason": None, "last_error": None, "updated_at": 0.0}

    def view(self):
        with self._lock:
            out = copy.deepcopy(self._v)
        out["connected"] = bool(self.connected)
        out["state"] = normalise(out["kobra_state"]) if self.connected else "offline"
        return out

    def apply(self, suffix, payload):
        if not isinstance(payload, dict):
            return
        handler = self._HANDLERS.get(suffix)
        with self._lock:
            if payload.get("state") == "failed":
                self._v["last_error"] = {"report": suffix, "action": _str(payload.get("action")),
                                         "code": payload.get("code"), "msg": _str(payload.get("msg"))}
            if handler:
                handler(self, payload, _dict(payload.get("data")))
            self._v["updated_at"] = time.time()

    def _print_fields(self, d, kobra_state):
        v = self._v
        if "progress" in d and kobra_state not in PRE_PRINT:
            v["progress"] = _num(d["progress"])
        for key, field, scale in (("print_time", "elapsed_s", 60), ("remain_time", "remaining_s", 60),
                                  ("curr_layer", "layer", 1), ("total_layers", "total_layers", 1)):
            if key in d:
                v[field] = _num(d[key]) * scale
        if "taskid" in d:
            v["task_id"] = str(d["taskid"])

    def _on_print(self, p, d):
        v, st = self._v, _str(p.get("state"))
        if st:
            v["kobra_state"] = st
        if st in ("pause", "paused"):
            if p.get("msg"):
                v["pause_reason"] = {"code": _num(p.get("code")), "msg": _str(p.get("msg"))}
        elif st in ("resuming", "resumed", "printing") or st in TERMINAL:
            v["pause_reason"] = None
        if st in TERMINAL:
            v.update(filename="", progress=0, elapsed_s=0, remaining_s=0, layer=0, total_layers=0)
            d = {k: d[k] for k in ("progress", "taskid") if k in d}
        elif "filename" in d:
            v["filename"] = _str(d["filename"])
        self._print_fields(d, st)
        settings = _dict(d.get("settings"))
        if "print_speed_mode" in settings:
            v["speed_mode"] = _num(settings["print_speed_mode"])

    def _on_info(self, p, d):
        v, project = self._v, _dict(d.get("project"))
        for key, field in (("version", "firmware"), ("printerName", "printer_name"), ("modelName", "model"),
                           ("model", "model")):
            if _str(d.get(key)):
                v[field] = d[key]
        st = _str(project.get("state")) or _str(d.get("state"))
        if st:
            v["kobra_state"] = st
        if st in TERMINAL:
            v.update(layer=0, total_layers=0)
            project = {k: x for k, x in project.items() if k not in ("filename", "curr_layer", "total_layers")}
        elif "filename" in project:
            v["filename"] = _str(project["filename"])
        self._print_fields(project, st)
        self._temps(_dict(d.get("temp")))
        urls = {k: x for k, x in _dict(d.get("urls")).items() if isinstance(x, str) and x}
        v["upload_url"] = urls.pop("fileUploadurl", v["upload_url"])
        if urls:
            v["camera_urls"] = urls
            v["camera_url"] = urls.get("rtspUrl", v["camera_url"])
        for key, field in (("fan_speed_pct", "fan_pct"), ("print_speed_mode", "speed_mode")):
            if key in d:
                v[field] = _num(d[key])
        storage = _dict(d.get("storage"))
        if storage:
            v["storage"] = {"total": _num(storage.get("total")), "used": _num(storage.get("used"))}

    def _temps(self, d):
        if d:
            for key, field in (("curr_nozzle_temp", "nozzle_temp"), ("target_nozzle_temp", "nozzle_target"),
                               ("curr_hotbed_temp", "bed_temp"), ("target_hotbed_temp", "bed_target")):
                self._v[field] = _num(d.get(key))

    def _on_temp(self, p, d):
        self._temps(d)

    def _on_box(self, p, d):
        if p.get("state") == "failed":
            return
        if isinstance(d.get("multi_color_box"), list):
            self._v["multi_color_box"] = d["multi_color_box"]
        if "head_tools_model" in d:
            self._v["head_tools_model"] = d["head_tools_model"]

    def _on_light(self, p, d):
        self._v.update(light_on=bool(d.get("status")), light_brightness=_num(d.get("brightness", 80), 80))

    def _on_fan(self, p, d):
        if "fan_speed_pct" in d:
            self._v["fan_pct"] = _num(d["fan_speed_pct"])

    def _on_file(self, p, d):
        if p.get("action") == "listLocal":
            if p.get("code") == 200 and isinstance(d.get("records"), list):
                files = [{"filename": _str(r.get("filename")), "size": _num(r.get("size")),
                          "timestamp": _num(r.get("timestamp"))}
                         for r in d["records"] if isinstance(r, dict) and not r.get("is_dir")]
                self._v["files"] = sorted(files, key=lambda f: -f["timestamp"])
        elif isinstance(d.get("file_details"), dict):
            self._v["file_details"] = d["file_details"]

    def _on_skip(self, p, d):
        raw = next((d[k] for k in ("objects_skip_parts", "skipped", "skipped_parts") if isinstance(d.get(k), list)), [])
        skipped = [str(x) for x in raw if x]
        existing = self._v["skipped_objects"]
        if normalise(self._v["kobra_state"]) in ("printing", "paused") and existing:
            skipped = existing + [n for n in skipped if n not in existing]
        self._v["skipped_objects"] = skipped

    def _on_buried(self, p, d):
        if "storage_total" in d or "storage_used" in d:
            self._v["storage"] = {"total": _num(d.get("storage_total")), "used": _num(d.get("storage_used"))}

    def _on_video(self, p, d):
        if p.get("state") != "failed" and p.get("action") in ("startCapture", "stopCapture"):
            self._v["camera_active"] = p["action"] == "startCapture"

    _HANDLERS = {"print/report": _on_print, "info/report": _on_info, "tempature/report": _on_temp,
                 "multiColorBox/report": _on_box, "light/report": _on_light, "fan/report": _on_fan,
                 "file/report": _on_file, "skip/report": _on_skip, "buried/report": _on_buried,
                 "video/report": _on_video}
