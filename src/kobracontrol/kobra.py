"""Anycubic Kobra X LAN protocol: credentials, MQTT commands, upload, state. Ported from Kobralink and
KX-Bridge (both GPL-3.0); where they disagree, a comment says which behaviour is kept and why.

`fetch_credentials(ip)` -> Credentials; `Printer(creds, ssl_context=certs.context(...))` talks MQTT;
`Printer.upload(...)` + `Printer.start_print(print_file_payload(...))` print a file; `State` folds reports.

Request/reply contract (observed on firmware 2.0.2.8; the captures in tests/kobra_captures.py are ground truth):
  - The printer acknowledges every request at once on `.../<deviceId>/response` with our msgid and empty
    fields (code 0, data null). That only means "received": it never settles a request. `Printer.last_ack`
    holds the last ack of one of our requests; acks are not passed to on_report.
  - The answer comes later on `<type>/report` with a msgid the PRINTER made, code 200, state "done" or
    "success", and action = the request's action (info/query answers with action "report"; see
    REPLY_ACTIONS). The topic is shared with other clients, so `request()` settles on the first report of
    that type and action that arrives after it published, whoever triggered it; concurrent identical
    requests share one answer. A report carrying the request's own msgid (older firmware) always settles
    that request, whatever its action.
  - `request()` returns that report dict; on timeout `None` when not even the ack came (not received), or
    an ack marker `{"ack": True, "type", "action", "msgid", "data": None}` (`is_ack_only()`) when only the
    ack came (received, no result reported: e.g. print/query on an idle printer). A dropped session -> None.
  - `succeeded(reply)`: a real report that is not state "failed" and whose code, if present, is 0 or 200.
    `check_reply(reply, what)` returns the reply or raises KobraError(code="no_answer"),
    NoResult(code="no_result") or KobraError(code=<the printer's code>).

State.view() returns one JSON-serialisable dict with exactly these keys (VIEW_KEYS):
  connected        bool, set by the owner through `State.connected`
  state            "offline|idle|printing|paused|finished|cancelled|error|busy" (normalised: see normalise()).
                   "error" also when the printer ended the task itself (print/report stoped with a code
                   other than 0/200, e.g. 10111 "abnormal end of task"); stoped with code 200 is "cancelled".
                   An unknown state during a job (a start report or an info project is active) is "printing".
  preparing        bool, True while a print runs a preparation phase (heating, levelling, wiping, ACE
                   feeding, any unknown phase of a running job); state is then "printing" and progress,
                   layers, elapsed and remaining keep their last values (the printer reports 0 meanwhile)
  kobra_state      raw printer state ("free", "printing", "pause", "stoped", ...; "" before any report)
  printer_name, model, firmware                       str ("" when unknown; model from the constructor
                                                      unless info/report carries model/modelName)
  filename         str, current job ("" when idle or after a terminal state)
  progress         number 0-100 as reported; never decreases within a job (reset when a new job reports
                   "checking", and by a terminal state); preparation phases keep the previous value
  layer, total_layers, elapsed_s, remaining_s         numbers (printer reports minutes; converted to s)
  task_id          str ("" unknown; pass it to pause/resume/stop and print/update helpers)
  nozzle_temp, nozzle_target, bed_temp, bed_target    numbers, deg C
  aux_fan_pct      number 0-100 (info aux_fan_speed_pct)
  phase_unit, phase_channel  ints (1-based ACE unit and slot) from the last job print/report, during the
                   ace_filament_unfeeding/feeding and nozzle_purging slot checks; None when it carried none
  layer/total_layers of a finished job stay shown (e.g. 50/50) until the next job reports "checking";
                   a cancel or abnormal end clears them
  features         {"<name>_support": bool} as info/report announces it ({} before)
  last_project     the printer's last job as info/report gives it (filename, state, task_id, progress,
                   curr_layer, total_layers, print_time, supplies_usage, ...), raw dict or None
  fan_pct          number 0-100; light_on bool; light_brightness number; speed_mode number (printer's code)
  multi_color_box  raw list from multiColorBox/report (ACE units and slots); head_tools_model raw value
  box_set_failed   bool, the last multiColorBox/report was state "failed" (e.g. a refused slot setInfo)
  files            [{"filename", "size", "timestamp"}] newest first (file/report listLocal, code 200);
                   timestamp in SECONDS (the printer reports milliseconds)
  file_details     raw dict of the last file/report file_details (thumbnail, objects_skip_parts, ...)
  upload_url       info urls.fileUploadurl ("" until announced); camera_url urls.rtspUrl, always the latest
  camera_urls      every info url except fileUploadurl; camera_active bool (video/report, unconfirmed)
  camera_url_rev   int, +1 each time camera_url changes to a new value (the printer rotates its stream
                   token on reboot, KX-Bridge issue #99): a camera reader restarts when it changes
  storage          {"total", "used"} from info storage or buried/report storage_total/used (MB), else {}
  last_job         buried/report of the last print start: {"task_name", "gcode_size" (bytes),
                   "estimate_duration" (s), "total_layers"} or None; metadata for files not uploaded by us
  skipped_objects  [str]; pause_reason {"code", "msg"} or None; last_error {"report", "action",
                   "code", "msg"} of the last report with state "failed", or None
  updated_at       time.time() of the last applied report (0.0 before)
  mac              str, the printer's network address (info/net data.mac or machine_mac; "" until reported)
  stats            {"print_minutes", "print_count", "filament_g"}: only the counters the printer reported
                   (info statistic-query / statistic-reported); {} when it reported none
  assist           {option: bool} of properties/report assistant_settings (Print Assist: 0 belt, 1 lost
                   step, 3 filament break, 4 filament jam, 5 remaining filament); an option the printer does not
                   list is not supported and is absent; None until the printer answered
UNTESTED on our printer (firmware 2.0.2.8): mac, stats and assist come from messages read in Anycubic Slicer
Next 2.0.0.3's Workbench page (info/net, info/statistic-query, properties/read); no capture of their answers yet.
"""

import base64
import copy
import hashlib
import http.client
import json
import logging
import math
import os
import re
import secrets
import string
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass

import aes
import mqtt
from i18n import tr

log = logging.getLogger(__name__)
UPLOAD_CHUNK = 256 * 1024
MAX_HTTP_BODY = 1024 * 1024  # /info, /ctrl and upload answers are a few hundred bytes
JSON_ERRORS = (ValueError, RecursionError)  # deeply nested JSON raises RecursionError, not ValueError
BOUNDARY = "------------------------a3a050b927d92a4c"
# Print-preparation phases (KX-Bridge PREPARATION_STATES + Kobralink PRE_PRINT_STATES; firmware 2.0.x
# reports each phase on its own). They belong to a running print, and the progress they report is
# their own, so it is ignored: passing it through makes print progress jump (KX-Bridge issue #102).
PRE_PRINT = {"preheating", "auto_leveling", "checking", "updated", "init", "hotbed_heating", "nozzle_heating",
             "nozzle_cooling", "nozzle_cooling_off", "hotbed_cooling_off", "nozzle_purging", "nozzle_wiping",
             "frequency_sweeping", "z_offset_calibrating", "extfilbox_filament_feeding",
             "ace_filament_feeding", "ace_filament_unfeeding"}  # last two: live capture, fw 2.0.2.8
# print/report actions that describe the job. Others (live: getSliceParam, answering another client every
# ~10 s with state "done") must not touch the print state or its numbers.
PRINT_JOB_ACTIONS = {"start", "pause", "resume", "stop", "finish", "query", "", None}
PRINTING = PRE_PRINT | {"printing", "resuming", "resumed", "stopping"}
PAUSED = {"pausing", "paused", "pause"}
TERMINAL = {"finished", "stoped", "canceled"}


class KobraError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class Cancelled(KobraError):
    pass


class NoResult(KobraError):
    """The printer acknowledged the request but reported no result before the timeout."""

    def __init__(self, message):
        super().__init__(message, code="no_result")


# Reply action when it is not the request's own (captured: info/query -> info/report action "report").
REPLY_ACTIONS = {("info", "query"): "report"}
START_WATCH = 5.0  # seconds start_print watches for the printer ending a fresh task by itself
_DEFAULT = object()


def _start_outcome(payload):
    """True: the print runs (a start report in a preparation phase past "checking", e.g. hotbed_heating);
    False: it ended (start/stop report stoped or failed); None: not decided by this report (checking,
    printing and anything else: a wrong filepath also reports both before ending). Other actions (another
    client's refused pause or update) say nothing about our start."""
    if not isinstance(payload, dict):
        return None
    state = payload.get("state")
    if state in ("stoped", "failed") and payload.get("action") in ("start", "stop"):
        return False
    if payload.get("action") == "start" and state in PRE_PRINT and state != "checking":
        return True
    return None


def is_ack_only(reply):
    return isinstance(reply, dict) and reply.get("ack") is True


def succeeded(reply):
    """One rule for every command reply: a real report, not state "failed", code absent or 0 or 200.
    (Kobralink took only code 0 as success; the real printer answers 200.)"""
    if not isinstance(reply, dict) or is_ack_only(reply):
        return False
    return reply.get("state") != "failed" and reply.get("code") in (None, 0, 200)


def check_reply(reply, what):
    """`reply` when it succeeded, else the KobraError a caller can show (what: "the pause", ...)."""
    if reply is None:
        raise KobraError(tr("the printer did not answer %s") % what, code="no_answer")
    if is_ack_only(reply):
        raise NoResult(tr("the printer received %s but reported no result") % what)
    if not succeeded(reply):
        code = reply.get("code")
        detail = _str(reply.get("msg")) or json.dumps(reply.get("data"))
        raise KobraError(tr("the printer refused %s (code %s): %s") % (what, "?" if code is None else code, detail),
                         code=code)
    return reply


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
# HTTP goes through http.client, never urllib.request. OrcaSlicer's plugin audit (PluginAuditManager.cpp,
# v2.5.0) matches `urllib.Request` against the full URL, and /ctrl carries a fresh ts/nonce/sign query
# every time, so no grant could ever cover it. http.client raises `http.client.connect` (target: the
# host) and then `socket.getaddrinfo`/`socket.connect` (target: the address), all network events matched
# by host whatever the port, so one grant of the printer's IP covers /info, /ctrl, the upload and MQTT.
# A denied event raises PermissionError from the audit hook. http.client has no proxy and never follows
# redirects: a 3xx is just a non-200 answer.
def _network_error(e, host, what):
    if isinstance(e, PermissionError):
        return KobraError(tr("OrcaSlicer denied network access to %s (grant it in the plugin's permissions)") % host,
                          code="denied")
    return KobraError(tr("printer not reachable at %s for %s (%s)") % (host, what, e), code="unreachable")


def _read_capped(resp, what):
    body = resp.read(MAX_HTTP_BODY + 1)
    if len(body) > MAX_HTTP_BODY:
        raise KobraError(tr("answer from %s too large") % what)
    return body


def _loads(body):
    """Parsed JSON, or None for anything that is not valid UTF-8 JSON (never raises)."""
    try:
        return json.loads(body)
    except JSON_ERRORS:
        return None


def _http_json(ip, port, path, timeout, what, post=False):
    conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.request("POST" if post else "GET", path, body=b"" if post else None, headers={"Connection": "close"})
        resp = conn.getresponse()
        if resp.status != 200:
            raise KobraError(tr("%s answered HTTP %d") % (what, resp.status))
        body = _read_capped(resp, what)
    except (OSError, http.client.HTTPException) as e:
        raise _network_error(e, "%s:%d" % (ip, port), what) from None
    finally:
        conn.close()
    result = _loads(body)
    if result is None:
        raise KobraError(tr("bad answer from %s (not JSON)") % what)
    return result


def fetch_credentials(ip, port=18910, timeout=10):
    info = _http_json(ip, port, "/info", timeout, "/info")
    token = info.get("token") if isinstance(info, dict) else None
    if not isinstance(token, str) or len(token) < 32:
        raise KobraError(tr("/info gave no token: is LAN mode enabled on the printer?"))
    ts = str(int(time.time() * 1000))
    nonce = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(6))
    sign = _md5(_md5(token[:16]) + ts + nonce)
    query = urllib.parse.urlencode({"ts": ts, "nonce": nonce, "sign": sign, "did": "random"})
    ctrl = _http_json(ip, port, "/ctrl?" + query, timeout, "/ctrl", post=True)
    data = ctrl.get("data") if isinstance(ctrl, dict) else None
    if not (isinstance(data, dict) and isinstance(data.get("info"), str) and isinstance(data.get("token"), str)):
        raise KobraError(tr("unexpected /ctrl answer from the printer"))
    try:  # AES-128: KX-Bridge's notes say AES-256, but both use the 16-byte key token[16:32]
        plain = aes.decrypt_cbc(token[16:32].encode(), data["token"].encode(), base64.b64decode(data["info"]))
    except ValueError:
        plain = b""
    result = _loads(plain)
    if not isinstance(result, dict):
        raise KobraError(tr("could not decrypt the printer credentials"))
    if result.get("error"):
        raise KobraError(tr("printer refused LAN access: %s") % result["error"])
    # The decrypted "ip" is ignored: the printer must not choose where we connect (both references use it).
    return Credentials(ip, str(result.get("username", "")), str(result.get("password", "")),
                       str(result.get("deviceId", "")), str(result.get("modeId") or "20030"),
                       str(result.get("modelName") or "Anycubic Kobra"))


def _md5(text):
    return hashlib.md5(text.encode()).hexdigest()


def _round(x):
    return math.floor(x + 0.5)  # JavaScript Math.round, as Kobralink sends


# printer ------------------------------------------------------------------------------------------
class _Pending:
    def __init__(self, msgid, report_key, reply_action, accept=None):
        """accept(payload) -> bool replaces the action match (used to watch a print start)."""
        self.msgid, self.report_key, self.reply_action, self.accept = msgid, report_key, reply_action, accept
        self.event, self.reply = threading.Event(), None
        self.sent = self.acked = self.dropped = False


class Printer:
    def __init__(self, creds, ssl_context=None, mqtt_port=9883, http_port=18910, on_report=None,
                 on_disconnect=None, timeout=8):
        """ssl_context: certs.context(...) for a real printer; None means plain TCP (tests only)."""
        self.creds, self.ssl_context, self.mqtt_port, self.http_port = creds, ssl_context, mqtt_port, http_port
        self.on_report, self.on_disconnect, self.timeout = on_report, on_disconnect, timeout
        self.client_id = "kobracontrol_" + secrets.token_hex(4)
        self._client = None
        self._lock = threading.Lock()
        self._connect_lock = threading.Lock()
        self._pending = []
        self.last_ack = None

    @property
    def connected(self):
        client = self._client
        return bool(client and client.connected)

    @property
    def tls_fingerprint(self):
        """SHA-256 (hex) of the certificate the printer presented on this session; "" without TLS or a session."""
        der = getattr(self._client, "peer_cert", None)
        return hashlib.sha256(der).hexdigest() if der else ""

    @property
    def last_rx(self):
        """time.monotonic() of the last MQTT bytes from the printer, 0.0 when never connected."""
        client = self._client
        return client.last_rx if client else 0.0

    def _topic(self, kind, type_):
        return "anycubic/anycubicCloud/v1/%s/printer/%s/%s/%s" % (kind, self.creds.mode_id, self.creds.device_id, type_)

    def connect(self, wait=True):
        """Open the MQTT session; a no-op when already connected. Returns `connected`.

        Concurrent callers never start two handshakes (the printer accepts one mTLS session at a time,
        KX-Bridge issue #105): with wait=True they block until the running attempt ends; with
        wait=False they return the current `connected` at once (for a poll loop that must stay prompt)."""
        if not self._connect_lock.acquire(blocking=wait):
            return self.connected
        try:
            if not self.connected:
                self._open_session()
            return True
        finally:
            self._connect_lock.release()

    def _open_session(self):
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
            raise KobraError(tr("MQTT %s:%d: %s") % (c.ip, self.mqtt_port, e), code=e.code) from None
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
            pending = list(self._pending)
        for p in pending:
            p.dropped = True
            self._resolve(p, None)

    def _resolve(self, p, payload):
        with self._lock:
            if p in self._pending:
                self._pending.remove(p)
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
        payload = _loads(raw)
        if not isinstance(payload, dict):
            return
        suffix = "/".join(topic.split("/")[-2:])
        msgid = payload.get("msgid")
        if topic.endswith("/response"):  # "received" ack: never an answer, never a report
            with self._lock:
                mine = [p for p in self._pending if msgid and p.msgid == msgid]
                for p in mine:
                    p.acked = True
                    self.last_ack = payload
            return
        with self._lock:
            waiting = [p for p in self._pending if p.sent and p.report_key == suffix]
        own = [p for p in waiting if msgid and p.msgid == msgid]
        action = payload.get("action")
        for p in own or [p for p in waiting if (p.accept(payload) if p.accept else
                                               p.reply_action is None or p.reply_action == action)]:
            self._resolve(p, payload)
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

    def request(self, type_, action, data=None, timeout=5, reply_action=_DEFAULT, accept=None, kind="slicer"):
        """Publish and wait for the `<type>/report` answer (see the module docstring for the contract).
        reply_action: the report action that answers (default: REPLY_ACTIONS or the request's action);
        None accepts any action of that type. accept(report) -> bool: an extra test on top of the action
        (an answer that names its subject, e.g. fileDetails' data.filename, must name ours)."""
        if not self.connected:
            return None
        if reply_action is _DEFAULT:
            reply_action = REPLY_ACTIONS.get((type_, action), action)
        def matches(report):
            return ((reply_action is None or report.get("action") == reply_action)
                    and (accept is None or accept(report)))
        p = _Pending(str(uuid.uuid4()), type_ + "/report", reply_action, accept=matches)
        with self._lock:
            self._pending.append(p)
        try:
            p.sent = True  # set before publishing: the answer can arrive before publish() returns
            if self._publish(kind, type_, action, data, p.msgid):
                p.event.wait(max(timeout, 0.001))
        finally:
            self._resolve(p, None)
        if p.reply is None and p.acked and not p.dropped:
            return {"ack": True, "type": type_, "action": action, "msgid": p.msgid, "data": None}
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

    # fan setSpeed and light type 3 as Kobralink and KX-Bridge's HTTP endpoints; KX-Bridge's older client
    # helpers (fan "set", light type 2) are not used by its own UI.
    def set_fan(self, pct):
        return self.send("fan", "setSpeed", {"fan_speed_pct": pct})

    def set_light(self, on, brightness=100):
        return self.send("light", "control", {"type": 3, "status": 1 if on else 0, "brightness": brightness})

    def set_printing_fan(self, taskid, pct):
        """The part fan during a print, as Anycubic Slicer Next's Workbench sends it (print/update settings); UNTESTED
        on our printer: fan/setSpeed is what the references send, idle or not."""
        return self.publish_web("print", "update", {"taskid": taskid, "settings": {"fan_speed_pct": pct}})

    # Anycubic Slicer Next 2.0.0.3 Workbench (web topic). UNTESTED on our printer: no answer captured yet.
    ASSIST_KEYS = ["assistant_settings"]

    # Which properties/report or info/report answers a request: the report topic is shared with every client and
    # with the printer's own pushes, so only a report of the request's own action settles it (Anycubic's page names
    # the properties actions read, write and report). A read may also be answered by a "report" push carrying the
    # switches; a write or a rename is never settled by a push.
    def query_properties(self, timeout=5):
        """properties/read of the Print Assist switches."""
        def answers(r):
            return r.get("action") in ("read", "report") and "assistant_settings" in _dict(r.get("data"))
        return self.request("properties", "read", list(self.ASSIST_KEYS), timeout, reply_action=None, accept=answers,
                            kind="web")

    def set_assist(self, items, timeout=8):
        """items: [{"option": n, "value": 0|1}]; settled only by a properties/report action "write"."""
        return self.request("properties", "write", {"assistant_settings": list(items)}, timeout, reply_action="write",
                            kind="web")

    def query_net(self):
        return self.publish_web("info", "net", {})

    def query_statistics(self):
        return self.publish_web("info", "statistic-query")

    def set_printer_name(self, name, timeout=8):
        """Settled only by an info/report action "setPrinterName" (the periodic info "report" never does)."""
        return self.request("info", "setPrinterName", {"printerName": name}, timeout, reply_action="setPrinterName",
                            kind="web")

    def set_print_speed_mode(self, taskid, mode):
        return self.publish_web("print", "update", {"taskid": taskid, "settings": {"print_speed_mode": mode}})

    def set_idle_temperature(self, nozzle=None, bed=None):
        """True when published; False when nothing to set or not connected."""
        if nozzle is None and bed is None:
            return False
        kind = 2 if nozzle is not None and bed is not None else (0 if nozzle is not None else 1)
        return self.publish_web("tempature", "set", {"type": kind, "target_nozzle_temp": _round(nozzle or 0),
                                                     "target_hotbed_temp": _round(bed or 0)})

    def set_printing_temperature(self, taskid, nozzle=None, bed=None):
        """True when every requested target was published."""
        sent = [self.publish_web("print", "update", {"taskid": taskid, "settings": {key: _round(value)}})
                for key, value in (("target_nozzle_temp", nozzle), ("target_hotbed_temp", bed)) if value is not None]
        return bool(sent) and all(sent)

    def move_axis(self, axis, move_type, distance=0):
        # homing answers when done (41 s on a real Kobra X); a jog answers when done too: 5 s + 1 s per 5 mm
        timeout = 90 if move_type == 2 else 5 + abs(_num(distance)) / 5
        return self.request("axis", "move", {"axis": axis, "move_type": move_type, "distance": distance}, timeout)

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

    # page_size 200 as KX-Bridge (tested against a real printer); Kobralink sends 1000.
    LIST_DATA = {"page_num": 1, "page_size": 200, "path": "/"}

    def list_local_files(self):
        return self.send("file", "listLocal", self.LIST_DATA)

    def delete_local_files(self, filenames):
        return self.send("file", "deleteBatch", _delete_data(filenames))

    def request_file_details(self, filename):
        return self.send("file", "fileDetails", {"root": "local", "filename": filename})

    def list_files(self, timeout=15):
        """[{"filename", "size", "timestamp" (seconds)}] of the printer's local storage, newest first."""
        reply = check_reply(self.request("file", "listLocal", self.LIST_DATA, timeout), tr("the file list"))
        return _file_records(_dict(reply.get("data")).get("records"))

    def delete_files(self, filenames, timeout=8):
        filenames = list(filenames)
        if not filenames:
            raise KobraError(tr("no file to delete"))
        return check_reply(self.request("file", "deleteBatch", _delete_data(filenames), timeout), tr("the delete"))

    # Time-lapse videos. file/listVideo and its answer were read on firmware 2.0.2.8 (tests/kobra_captures.py
    # FILE_LISTVIDEO). There is no known way to fetch a video or its cover picture (file_image) over the LAN.
    VIDEO_LIST_DATA = {"page_num": 1, "page_size": 200, "path": "/", "keyword": ""}

    def list_videos(self, timeout=15):
        """[{"filename", "name" (the print), "created" (unix s), "duration" (s), "size" (bytes)}], newest first."""
        reply = check_reply(self.request("file", "listVideo", self.VIDEO_LIST_DATA, timeout), tr("the time-lapse list"))
        return _video_records(_dict(reply.get("data")).get("records"))

    def delete_video(self, filename, timeout=8):
        if not isinstance(filename, str) or not filename:
            raise KobraError(tr("no video to delete"))
        def ours(report):  # other clients delete videos on the shared topic; a reply naming another file is theirs
            named = _str(_dict(report.get("data")).get("filename")).lstrip("/")
            return named in ("", filename.lstrip("/"))
        reply = self.request("file", "deleteVideo", _delete_video_data(filename), timeout, accept=ours)
        return check_reply(reply, tr("the delete"))

    def file_details(self, filename, timeout=5):
        """The printer's file_details dict (thumbnail, png_image, objects_skip_parts, estimated_time_s, ...)."""
        def ours(report):  # other clients poll fileDetails for their files on the shared topic
            named = _str(_dict(report.get("data")).get("filename")).lstrip("/")
            return named == filename.lstrip("/") or (not named and not succeeded(report))  # a refusal names none
        reply = self.request("file", "fileDetails", {"root": "local", "filename": filename}, timeout, accept=ours)
        return _dict(_dict(check_reply(reply, tr("the details of %s") % filename).get("data")).get("file_details"))

    def start_print(self, payload, timeout=15):
        """Send print/start; return the first print/report action "start" once the print is known to run.

        Raises KobraError with the printer's code when refused, NoResult when only acknowledged (not
        success), KobraError(code="no_answer") when not even that. A start report alone is no proof: with a
        file it cannot find, firmware 2.0.2.8 reports start/checking and start/printing, then ends the task
        itself (stop/stoped code 10111 "abnormal end of task") within a second. So after the first start
        report this watches print/report for up to START_WATCH seconds: a stoped/failed report raises with
        its code and msg; a start report in a later phase (heating, levelling, ...) ends the watch early."""
        watch = _Pending(None, "print/report", None, accept=lambda report: _start_outcome(report) is not None)
        watch.sent = True
        with self._lock:
            self._pending.append(watch)
        try:
            reply = check_reply(self.request("print", "start", payload, timeout), tr("the print"))
            if not _start_outcome(reply):
                watch.event.wait(START_WATCH)
        finally:
            self._resolve(watch, None)
        end = reply if _start_outcome(reply) is not None else watch.reply
        if isinstance(end, dict) and end.get("state") in ("stoped", "failed"):
            code = end.get("code")
            if end.get("state") == "stoped" and code in (None, 0, 200):
                raise Cancelled(tr("the print was stopped right after it started"))
            raise KobraError(tr("the printer ended the print at once (code %s): %s") % (code, _str(end.get("msg"))),
                             code=code)
        return reply

    # upload ------------------------------------------------------------------------------------------
    def upload(self, filename, source, upload_url, size=None, progress=None, cancelled=None):
        """Stream `source` to the printer as `filename`; returns the printer's JSON answer.

        source: a path (size from the file) or a readable binary file object such as a zipfile member
        (then `size` is required). Only the ?s= token is taken from upload_url; the POST goes to creds.ip.
        progress(sent, total) after each chunk; cancelled() is checked before each chunk (-> Cancelled).
        A source that ends before `size` bytes raises KobraError: nothing truncated is ever completed."""
        if not filename or any(ch in filename for ch in '"\r\n'):
            raise KobraError(tr("unsupported file name for the printer"))
        idx = upload_url.find("?s=")
        if idx < 0:
            raise KobraError(tr("the printer's upload URL has no session token"))
        if isinstance(source, (str, os.PathLike)):
            with open(source, "rb") as f:
                return self._upload(filename, f, os.path.getsize(source), upload_url[idx + 3:], progress, cancelled)
        if size is None:
            raise KobraError("upload from a file object needs its size")
        return self._upload(filename, source, int(size), upload_url[idx + 3:], progress, cancelled)

    def _upload(self, filename, source, total, token, progress, cancelled):
        head = ("--{b}\r\nContent-Disposition: form-data; name=\"filename\"\r\n\r\n{f}\r\n--{b}\r\n"
                "Content-Disposition: form-data; name=\"gcode\"; filename=\"{f}\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n").format(b=BOUNDARY, f=filename).encode()
        tail = ("\r\n--%s--\r\n" % BOUNDARY).encode()
        conn = http.client.HTTPConnection(self.creds.ip, self.http_port, timeout=30)
        try:
            conn.putrequest("POST", "/gcode_upload?s=" + token, skip_host=True, skip_accept_encoding=True)
            for key, value in self._upload_headers(total, len(head) + total + len(tail)):
                conn.putheader(key, value)
            conn.endheaders()
            conn.send(head)
            self._stream(conn, source, total, progress, cancelled)
            conn.send(tail)
            conn.sock.settimeout(180)  # the printer answers after writing the file to its storage
            resp = conn.getresponse()
            status, body = resp.status, _read_capped(resp, tr("the upload"))
        except PermissionError as e:
            raise _network_error(e, self.creds.ip, tr("the upload")) from None
        except (OSError, http.client.HTTPException) as e:
            raise KobraError(tr("upload to the printer failed (%s)") % e) from None
        finally:
            conn.close()
        if status != 200:
            raise KobraError(tr("the printer refused the upload: HTTP %d") % status)
        result = _loads(body)
        if not isinstance(result, dict):
            raise KobraError(tr("unexpected upload answer: %r") % body[:200])
        if result.get("code") != 200:  # real answer: {"code": 200, "data": {"gcode": name}, "message": "success"}
            raise KobraError(tr("the printer refused the upload (code %s): %s")
                             % (result.get("code"), _str(result.get("message"))), code=result.get("code"))
        return result

    def _upload_headers(self, file_size, body_size):
        return [("Host", "%s:%d" % (self.creds.ip, self.http_port)), ("User-Agent", "AnycubicSlicerNext/1.3.9.4"),
                ("Accept", "*/*"), ("X-BBL-Client-Name", "AnycubicSlicerNext"), ("X-BBL-Client-Type", "slicer"),
                ("X-BBL-Client-Version", "01.03.09.04"), ("X-BBL-Device-ID", str(uuid.uuid4())),
                ("X-BBL-Language", "en-US"), ("X-BBL-OS-Type", "windows"), ("X-BBL-OS-Version", "10.0.26200"),
                ("X-File-Length", str(file_size)), ("Content-Type", "multipart/form-data; boundary=" + BOUNDARY),
                ("Content-Length", str(body_size)), ("Connection", "close")]

    @staticmethod
    def _stream(conn, source, total, progress, cancelled):
        sent = 0
        while sent < total:
            if cancelled and cancelled():
                raise Cancelled(tr("upload cancelled"))
            chunk = source.read(min(UPLOAD_CHUNK, total - sent))
            if not chunk:  # closing the connection short of Content-Length makes the printer drop it
                raise KobraError(tr("the file ended early (%d of %d bytes)") % (sent, total))
            conn.send(chunk)
            sent += len(chunk)
            if progress:
                progress(sent, total)
        if cancelled and cancelled():  # last chance: the printer keeps nothing until the closing boundary
            raise Cancelled(tr("upload cancelled"))


def print_file_payload(filename, size, mapping, task=None):
    """print/start data for a file already on the printer.

    filepath is the FOLDER holding the file ("/"), as in file/deleteBatch's {path, filename}: firmware 2.0.2.8
    joins it with filename, so Kobralink's printPrinterFile form ("/<filename>") made it look for
    /<name>/<name>, find nothing and end the task with code 10111.
    mapping: ams_box_mapping entries; task: {"auto_leveling", "vibration_compensation", "flow_calibration", "timelapse",
    "skip_parts"}. flow_calibration and timelapse are UNTESTED on our printer: the fields are Anycubic Slicer Next's
    (libmach_mqtt PrintStart), timelapse type 64 is what Kobralink and KX-Bridge send; no print with them set was
    captured yet (the printer echoes both in buried/report PrintStart as flow_calibration / time_lapse)."""
    task = task or {}
    return {
        "taskid": "-1", "url": "", "filename": filename, "md5": "", "filepath": "/",
        "filetype": 1, "project_type": 1, "filesize": size,
        "ams_settings": {"use_ams": bool(mapping), "ams_box_mapping": list(mapping)},
        "task_settings": {
            "auto_leveling": 1 if task.get("auto_leveling") else 0,
            "vibration_compensation": 1 if task.get("vibration_compensation") else 0,
            "flow_calibration": 1 if task.get("flow_calibration") else 0, "dry_mode": 0,
            "ai_settings": {"status": 0, "count": 0, "type": 1},
            "timelapse": {"status": 1 if task.get("timelapse") else 0, "count": 0, "type": 64},
            "drying_settings": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
            "model_objects_skip_parts": list(task.get("skip_parts") or []),
        },
    }



# state reducer -------------------------------------------------------------------------------------
VIEW_KEYS = ("connected", "state", "preparing", "box_set_failed", "camera_url_rev", "kobra_state", "printer_name", "model", "firmware", "filename", "progress",
             "layer", "total_layers", "elapsed_s", "remaining_s", "task_id", "nozzle_temp", "nozzle_target",
             "bed_temp", "bed_target", "fan_pct", "light_on", "light_brightness", "speed_mode", "multi_color_box",
             "head_tools_model", "files", "file_details", "upload_url", "camera_url", "camera_urls",
             "camera_active", "storage", "skipped_objects", "pause_reason", "last_error", "updated_at", "last_job", "aux_fan_pct",
             "features", "last_project", "phase_unit", "phase_channel", "mac", "stats", "assist")


def normalise(kobra_state):
    """Printer state -> view state. Both references map "busy" (the top-level device state) and unknown
    states to printing/standby; here they are "busy", which says less but is never wrong. "offline" is
    error in Kobralink and unused by KX-Bridge; it is reported as "offline"."""
    if kobra_state in ("", "free"):
        return "idle"
    if kobra_state in PAUSED:
        return "paused"
    if kobra_state == "finished":
        return "finished"
    if kobra_state in ("stoped", "canceled"):
        return "cancelled"
    if kobra_state == "failed":
        return "error"
    if kobra_state == "offline":
        return "offline"
    return "printing" if kobra_state in PRINTING else "busy"


def _delete_data(filenames):
    return {"root": "local", "files": [{"path": "/", "filename": f} for f in filenames]}


def _seconds(ts):
    """listLocal timestamps are milliseconds on firmware 2.0.2.8; seconds are kept as they are."""
    ts = _num(ts)
    return ts / 1000 if ts > 1e11 else ts


def _file_records(records):
    files = [{"filename": _str(r.get("filename")), "size": _num(r.get("size")), "timestamp": _seconds(r.get("timestamp"))}
             for r in (records if isinstance(records, list) else []) if isinstance(r, dict) and not r.get("is_dir")]
    return sorted(files, key=lambda f: -f["timestamp"])


def _delete_video_data(filename):
    """file/deleteVideo data: Anycubic Slicer Next's VideoDelete {path, filename}, "/" being the folder listVideo
    lists (as in a deleteBatch entry). Verified on a Kobra X with firmware 2.0.2.8 on 2026-11-16; it answered
    {"action": "deleteVideo", "code": 200, "data": null, "msg": "done"}."""
    return {"path": "/", "filename": filename}


VIDEO_TEXT_MAX = 255


def _amount(value, top):
    """A number from 0 to top as the printer sent it; anything else (text, a bool, negative, infinite) is 0."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= top else 0


def _video_records(records):
    """listVideo records as [{"filename", "name", "created", "duration", "size"}], newest first. A record without
    a file name of a sane length is dropped; every other field is a string of at most VIDEO_TEXT_MAX characters or
    a plain number, whatever the printer sent. createTime is seconds on firmware 2.0.2.8; milliseconds would be
    converted, as for listLocal."""
    videos = []
    for r in records if isinstance(records, list) else []:
        filename = _str(r.get("filename")) if isinstance(r, dict) else ""
        if not filename or len(filename) > VIDEO_TEXT_MAX:
            continue
        videos.append({"filename": filename, "name": _str(r.get("main_file_name"))[:VIDEO_TEXT_MAX],
                       "created": _seconds(_amount(r.get("createTime"), 1e13)),
                       "duration": _amount(r.get("duration"), 1e7), "size": _amount(r.get("fileSize"), 1e13)})
    return sorted(videos, key=lambda v: -v["created"])


def _dict(value):
    return value if isinstance(value, dict) else {}


def _num(value, default=0):
    """A finite number, else default (JSON numbers such as 1e999 parse as infinity)."""
    if isinstance(value, int):
        return value
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _str(value):
    return value if isinstance(value, str) else ""


def _box(raw):
    """A multiColorBox entry the slot code can read: a slot that is not an object becomes an empty one (its
    position is its slot number, so it is never dropped), a status block that is not an object is left out."""
    box = {k: v for k, v in raw.items() if k not in ("feed_status", "drying_status", "drying_settings")
           or isinstance(v, dict)}
    if "slots" in box:
        box["slots"] = [s if isinstance(s, dict) else {} for s in box["slots"]] if isinstance(box["slots"], list) else []
    return box


def _merge_slots(old, new):
    """A box's slots after a report: a list at least as long as the known one replaces it; a shorter one (one
    edited slot, say) replaces only the slots it names by `index`; none or an empty list keeps them."""
    if not isinstance(new, list) or not new:
        return old
    if len(new) >= len(old) or not all(isinstance(s.get("index"), int) and 0 <= s["index"] < len(old) for s in new):
        return new
    out = list(old)
    for s in new:
        out[s["index"]] = s
    return out


def _merge_boxes(old, new):
    """The known boxes updated with a report's boxes, by id: fields it carries replace the old ones, boxes it
    leaves out stay. ponytail: an unplugged ACE shows until the printer reconnects (a fresh State); a report
    that omits a box is not proof the box is gone."""
    out = {b.get("id"): b for b in old}
    for b in new:
        prev = out.get(b.get("id"))
        out[b.get("id")] = {**prev, **b, "slots": _merge_slots(prev.get("slots") or [], b.get("slots"))} \
            if prev is not None else b
    return list(out.values())


# Anycubic Slicer Next 2.0.0.3 (Workbench lanTopic_v3 mergeLanStatistics): grams in material_used_gram_value, else
# material_used_value. UNTESTED on our printer.
_STATS = (("print_total_minutes", "print_minutes"), ("print_count", "print_count"))


def _statistics(d):
    """The cumulative counters an info report carries, each only when present and a number >= 0."""
    out = {}
    for key, field in _STATS:
        if isinstance(d.get(key), (int, float)) and not isinstance(d.get(key), bool) and d[key] >= 0:
            out[field] = _num(d[key])
    grams = d.get("material_used_gram_value", d.get("material_used_value"))
    if isinstance(grams, (int, float)) and not isinstance(grams, bool) and grams >= 0:
        out["filament_g"] = _num(grams)
    return out


ASSIST_OPTIONS = (0, 1, 3, 4, 5)   # belt, lost step, filament break, filament jam, remaining filament


def _assist(raw):
    """{option: bool} from assistant_settings ([{option, value}], maybe wrapped as {"value": [...]}); None when it
    is not a list. Unknown options are dropped."""
    if isinstance(raw, dict) and "value" in raw:
        raw = raw["value"]
    if not isinstance(raw, list):
        return None
    out = {}
    for item in raw:
        option = _int(item.get("option")) if isinstance(item, dict) else None
        if option in ASSIST_OPTIONS:
            out[option] = _int(item.get("value")) == 1
    return out


def _int(value):
    """An int from an int or a numeric string ("3"); None otherwise (bools and fractions too)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value.strip(), re.ASCII):   # not "--3", "3.0", "٣" or ""
        return int(value.strip())
    return None


class State:
    """Folds report payloads into one view (see the module docstring). Thread-safe."""

    def __init__(self, model=""):
        self.connected = False
        self._in_job = self._error_end = False
        self._lock = threading.Lock()
        self._v = {
            "kobra_state": "", "printer_name": "", "model": model, "firmware": "", "filename": "", "progress": 0,
            "layer": 0, "total_layers": 0, "elapsed_s": 0, "remaining_s": 0, "task_id": "", "nozzle_temp": 0,
            "nozzle_target": 0, "bed_temp": 0, "bed_target": 0, "fan_pct": 0, "light_on": False,
            "light_brightness": 80, "speed_mode": 0, "multi_color_box": [], "head_tools_model": None, "files": [],
            "file_details": {}, "upload_url": "", "camera_url": "", "camera_urls": {}, "camera_active": False,
            "storage": {}, "skipped_objects": [], "pause_reason": None, "last_error": None, "updated_at": 0.0,
            "box_set_failed": False, "camera_url_rev": 0, "last_job": None,
            "aux_fan_pct": 0, "features": {}, "last_project": None, "phase_unit": None, "phase_channel": None,
            "mac": "", "stats": {}, "assist": None}

    def view(self):
        with self._lock:
            out = copy.deepcopy(self._v)
        out["connected"] = bool(self.connected)
        state = normalise(out["kobra_state"]) if out["kobra_state"] else "busy"  # unknown until a first report
        if state == "busy" and self._in_job:
            state = "printing"
        elif state == "cancelled" and self._error_end:
            state = "error"
        out["state"] = state if self.connected else "offline"
        out["preparing"] = out["state"] == "printing" and self._preparing(out["kobra_state"])
        return out

    def _preparing(self, kobra_state):
        return kobra_state in PRE_PRINT or (self._in_job and normalise(kobra_state) == "busy")

    def _set_state(self, st, in_job):
        """Record a job state; in_job: whether a job is known to run (start report, info project)."""
        self._v["kobra_state"] = st
        was = self._in_job
        self._in_job = in_job and st not in TERMINAL and st != "free"
        if self._in_job and not was:  # a job begins (by any route): nothing of the last one carries over
            self._v.update(progress=0, layer=0, total_layers=0, elapsed_s=0, remaining_s=0)
        elif st == "free":  # idle: a cancel's or a finished job's progress is not shown any more
            self._v["progress"] = 0
        if st != "stoped":
            self._error_end = False

    def apply(self, suffix, payload):
        if not isinstance(payload, dict):
            return
        handler = self._HANDLERS.get(suffix)
        with self._lock:
            if payload.get("state") == "failed":
                self._v["last_error"] = {"report": suffix, "action": _str(payload.get("action")),
                                         "code": payload.get("code"), "msg": _str(payload.get("msg"))}
            before = self._job_key()
            if handler:
                handler(self, payload, _dict(payload.get("data")))
            self._clear_skips_on_new_print(before)
            self._v["updated_at"] = time.time()

    def _job_key(self):
        return normalise(self._v["kobra_state"]), self._v["filename"], self._v["task_id"]

    def _clear_skips_on_new_print(self, before):
        """Kobralink clears skipped objects at print start: a print starts when the state enters printing
        from a non-print state, or when the job's filename or task id changes to a new value. "busy" (the
        device-level state info/report may carry mid-print) counts as in-print, so it never clears."""
        (was, old_file, old_task), (now, new_file, new_task) = before, self._job_key()
        active = ("printing", "paused", "busy")
        if now != "printing":
            return
        if (was not in active or (new_file and old_file and new_file != old_file)
                or (new_task and old_task and new_task != old_task)):
            self._v["skipped_objects"] = []

    def _print_fields(self, d, kobra_state):
        v = self._v
        if not self._preparing(kobra_state):  # preparation phases report their own numbers, often 0
            if "progress" in d and (kobra_state in TERMINAL or _num(d["progress"]) >= v["progress"]):
                # never back within a job: after the last layer fw 2.0.2.8 sends start/printing progress 0
                v["progress"] = _num(d["progress"])
            for key, field, scale in (("print_time", "elapsed_s", 60), ("remain_time", "remaining_s", 60),
                                      ("curr_layer", "layer", 1), ("total_layers", "total_layers", 1)):
                if key in d:
                    v[field] = _num(d[key]) * scale
        if "taskid" in d:
            v["task_id"] = str(d["taskid"])

    def _on_print(self, p, d):
        v, st = self._v, _str(p.get("state"))
        settings = _dict(d.get("settings"))
        if "print_speed_mode" in settings:
            v["speed_mode"] = _num(settings["print_speed_mode"])
        # Not job news: other actions (getSliceParam), and a refused command of any client ("failed": apply()
        # already put it in last_error) which leaves the job as it was.
        if p.get("action") not in PRINT_JOB_ACTIONS or st == "failed":
            return
        if st == "checking":  # a new job starts: its progress and layers start from 0 (monotonic from here)
            v.update(progress=0, layer=0, total_layers=0)
        v["phase_unit"] = d.get("unit_no") if isinstance(d.get("unit_no"), int) else None
        v["phase_channel"] = d.get("channel_no") if isinstance(d.get("channel_no"), int) else None
        if st:
            self._set_state(st, p.get("action") == "start" or self._in_job)
            if st == "stoped" and p.get("code") not in (None, 0, 200):
                self._error_end = True
                v["last_error"] = {"report": "print/report", "action": _str(p.get("action")),
                                   "code": p.get("code"), "msg": _str(p.get("msg"))}
        if st in ("pause", "paused"):
            if p.get("msg"):
                v["pause_reason"] = {"code": _num(p.get("code")), "msg": _str(p.get("msg"))}
        elif st in ("resuming", "resumed", "printing") or st in TERMINAL:
            v["pause_reason"] = None
        if st in TERMINAL:
            v.update(filename="", progress=0, elapsed_s=0, remaining_s=0)
            if st != "finished":  # a finished job keeps its layers (50/50) until the next job's "checking"
                v.update(layer=0, total_layers=0)
            d = {k: d[k] for k in ("progress", "taskid") if k in d}
        elif "filename" in d:
            v["filename"] = _str(d["filename"]).rsplit("/", 1)[-1]  # print/report sends "/<name>"
        self._print_fields(d, st)

    def _on_info(self, p, d):
        v, project = self._v, _dict(d.get("project"))
        for key, field in (("version", "firmware"), ("printerName", "printer_name"), ("modelName", "model"),
                           ("model", "model")):
            if _str(d.get(key)):
                v[field] = d[key]
        st = _str(project.get("state")) or _str(d.get("state"))
        if st:
            self._set_state(st, bool(project))
        if st in TERMINAL:
            # KX-Bridge still adopts project.filename here; Kobralink (followed) does not, so a finished
            # job does not reappear as the current file. Neither project has a test for it.
            if st != "finished":
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
            camera = urls.get("rtspUrl", v["camera_url"])
            if v["camera_url"] and camera != v["camera_url"]:
                v["camera_url_rev"] += 1
            v["camera_url"] = camera
        if isinstance(d.get("features"), dict):
            v["features"] = d["features"]
        if "last_project" in d:
            v["last_project"] = d["last_project"] if isinstance(d["last_project"], dict) else None
        for key, field in (("fan_speed_pct", "fan_pct"), ("print_speed_mode", "speed_mode"),
                           ("aux_fan_speed_pct", "aux_fan_pct")):
            if key in d:
                v[field] = _num(d[key])
        storage = _dict(d.get("storage"))
        if storage:
            v["storage"] = {"total": _num(storage.get("total")), "used": _num(storage.get("used"))}
        mac = _str(d.get("mac")) or _str(d.get("machine_mac"))
        if mac:
            v["mac"] = mac[:64]
        stats = _statistics(d)
        if stats:
            v["stats"] = {**v["stats"], **stats}

    def _temps(self, d):
        if d:
            for key, field in (("curr_nozzle_temp", "nozzle_temp"), ("target_nozzle_temp", "nozzle_target"),
                               ("curr_hotbed_temp", "bed_temp"), ("target_hotbed_temp", "bed_target")):
                if key in d:   # a partial report keeps the rest: a missing target is not a heater turned off
                    self._v[field] = _num(d[key])

    def _on_temp(self, p, d):
        self._temps(d)

    def _on_box(self, p, d):
        # A refused setInfo answers state "failed" with data as a list (KX-Bridge issue #100): keep the
        # slots, raise the flag. An empty list changes nothing, as in both references: firmware 1.1.5.1
        # answered some getInfo polls without its ACE, which wiped the slots every 5 s. A report naming
        # some boxes updates those (_merge_boxes), so one box's or one slot's news never drops the rest.
        self._v["box_set_failed"] = p.get("state") == "failed"
        if self._v["box_set_failed"]:
            return
        if isinstance(d.get("multi_color_box"), list):
            boxes = [_box(b) for b in d["multi_color_box"] if isinstance(b, dict)]
            if boxes:
                self._v["multi_color_box"] = _merge_boxes(self._v["multi_color_box"], boxes)
        if "head_tools_model" in d:
            self._v["head_tools_model"] = d["head_tools_model"]

    def _on_light(self, p, d):
        if p.get("state") == "failed":   # a refused light/control: the light did not change
            return
        if "status" in d:
            self._v["light_on"] = bool(d["status"])
        if "brightness" in d:
            self._v["light_brightness"] = _num(d["brightness"], 80)

    def _on_fan(self, p, d):
        if "fan_speed_pct" in d:
            self._v["fan_pct"] = _num(d["fan_speed_pct"])

    def _on_file(self, p, d):
        if p.get("action") == "listLocal":
            if p.get("code") == 200 and isinstance(d.get("records"), list):
                self._v["files"] = _file_records(d["records"])
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
        # The printer's analytics event, once per print start; ignored without task_name (both references).
        if not _str(d.get("task_name")):
            return
        self._v["last_job"] = {"task_name": d["task_name"], "gcode_size": _num(d.get("gcode_size")),
                               "estimate_duration": _num(d.get("estimate_duration")),
                               "total_layers": _num(d.get("total_layers"))}
        self._v["storage"] = {"total": _num(d.get("storage_total")), "used": _num(d.get("storage_used"))}

    def _on_properties(self, p, d):
        assist = _assist(d.get("assistant_settings"))
        if assist is not None and p.get("state") != "failed":
            self._v["assist"] = {**(self._v["assist"] or {}), **assist}

    def _on_video(self, p, d):
        if p.get("state") != "failed" and p.get("action") in ("startCapture", "stopCapture"):
            self._v["camera_active"] = p["action"] == "startCapture"

    def _on_status(self, p, d):
        # workReport busy|free: the device is busy (moving, homing) or free. Only while no job runs: during a
        # job the job's own state says more.
        if p.get("action") == "workReport" and p.get("state") in ("busy", "free") and not self._in_job:
            self._set_state(p["state"], False)

    _HANDLERS = {"status/report": _on_status, "print/report": _on_print, "info/report": _on_info, "tempature/report": _on_temp,
                 "multiColorBox/report": _on_box, "light/report": _on_light, "fan/report": _on_fan,
                 "file/report": _on_file, "skip/report": _on_skip, "buried/report": _on_buried,
                 "video/report": _on_video, "properties/report": _on_properties}
