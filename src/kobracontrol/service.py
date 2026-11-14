"""Printer-side work for the printer agent and the Kobra Control tab, kept free of the `orca` module.

One `connection.Connection` (MQTT session + `kobra.State`) per printer address, shared by the agent and the
tab. (The printer does not require this: two MQTT sessions were observed side by side on firmware 2.0.2.8. One
connection keeps one state and one stream of reports. Reports are shared by every client of the printer, so a
report caused by another client's command can reach us; nothing here takes one as the answer to our command.)
Threads, all the plugin's own: each connection's loop; one command worker (page commands run in order);
one monitor (status and camera for the page, only while it holds a lease); one tracker (filament use and
Spoolman follow-up for every connected printer). Pause and stop run at once on their own short-lived thread.

Every page request is tied to the printer that was selected when it arrived (generation). A queued request
whose printer is no longer selected is dropped before it does anything; pause and stop are pinned to the
printer they were pressed for. Every command checks the printer's current state itself (`can_flags`), so a
command the state does not allow is refused whatever the page shows.
"""

import base64
import contextlib
import queue
import re
import threading
import time
import traceback

import ace
import camera
import certs
import connection
from connection import camera_url_for, find_and_save_certificate  # noqa: F401  (plugin.py imports them here)
import kobra
import settings
import spoolman as sm
import usage
from jobs import CONNECT_WAIT, JobsMixin, plate_source, remote_name, supported_task  # noqa: F401  (re-exported for callers)
from files import FilesMixin
from stockview import StockMixin
from usage import UsageMixin

LEASE_SECONDS = 6.0
STATUS_EVERY = 1.0
URGENT = ("pause", "stop")      # never wait behind the command worker
BOUNDED = ("stock", "usage", "usage_ack", "find_certificate", "home")   # home: up to 90 s, never on the worker   # own thread, at most one of each in flight
DEDICATED = URGENT + BOUNDED                                    # own short-lived thread
BUSY = "%s is already running; try again when it ends"
STALE = "the selected printer changed; nothing was sent to it"
NO_PRINTER = "no Kobra X selected: choose an Anycubic Kobra X printer preset with its IP address"
# The Kobra X machine profile (OrcaSlicer resources/profiles/Anycubic/machine/Anycubic Kobra X 0.4 nozzle.json)
# sets no temperature maxima; these are Kobralink's limits (packages/shared/src/control.ts setTemperature).
NOZZLE_MAX, BED_MAX = 320, 120
LIMITS = {"nozzle_max": NOZZLE_MAX, "bed_max": BED_MAX}
IDLE = ("idle", "finished", "cancelled")
MOVE_MAX = 50.0                 # mm per jog: the largest step the page offers; anything larger is clamped
AXIS = {"x": 1, "y": 2, "z": 3}
# Jog as Kobralink and KX-Bridge's client: axis 1/2/3, move_type 1 = +, 0 = -, distance > 0.
# Home is move_type 2 with axis 5 = X, Y and Z, 4 = X and Y, 3 = Z: KX-Bridge fixed "Home All" to 5 after a
# report from a real printer (its CHANGELOG 0.9.1-beta14, Issue #4). Kobralink sends 4 for "all", which by that
# report homes X and Y only. Still to be watched once on our own printer.
HOME = {"xyz": 5, "xy": 4, "z": 3}
STOCK_UNSUPPORTED_S = 30.0      # Spooler active but no stock list for us this long: "unsupported"
FEED_ACK_DELAY = 2.0            # Kobralink: feedFilament type 3 two seconds after feed_status 10/11
DRY_TEMP, DRY_MINUTES = (30, 80), (10, 24 * 60)   # ace.sanitize_ace_dry_presets bounds


class Target:
    """The tab's printer, resolved by the plugin on the UI thread."""

    def __init__(self, host, name=settings.DEFAULT_PRINTER_NAME, spoolman_url="", spoolman_auto=True,
                 spoolman_report_usage=True, ffmpeg_path="", camera_enabled=True):
        self.host, self.name = host, name or settings.DEFAULT_PRINTER_NAME
        self.spoolman_url, self.spoolman_auto = spoolman_url, spoolman_auto
        self.spoolman_report_usage, self.ffmpeg_path, self.camera_enabled = spoolman_report_usage, ffmpeg_path, camera_enabled

    def key(self):
        return (self.host, self.name, self.spoolman_url)

    @property
    def ident(self):
        return usage.printer_ident(self.host)


def can_flags(view):
    """What the printer state allows now (status.data `can`)."""
    st, on = view.get("state"), bool(view.get("connected"))
    idle, running, paused = on and st in IDLE, on and st == "printing", on and st == "paused"
    running_print = running and not view.get("preparing")   # heating/levelling: the printer has no print to pause yet
    return {"pause": running_print, "resume": paused, "stop": running or paused, "move": idle,
            "heat": idle or running or paused, "feed": idle or paused, "print": idle}


def status_data(view, units_before=(), bindings=None, pending_load=-1):
    """status.data for the page (architecture.md) -> (data, ace units). The upload URL carries the printer's
    upload token, so it never leaves the plugin: `upload_url` is always "". `file_details` is left out: it holds
    whichever file was asked about last; the running print's objects come from cmd_objects."""
    boxes = view.get("multi_color_box") or []
    mode = ace.detect_filament_mode(boxes, view.get("head_tools_model"))
    slots, loaded = ace.aggregate_slots(boxes, mode)
    activity = ace.slot_activity_map(boxes, loaded, mode, pending_load)
    units, _ = ace.aggregate_ace_units(boxes, list(units_before))
    bindings = bindings or {}
    slots = [{**s, "activity": activity.get(s["global_index"], ""), "tray": ace.tray_id(s),
              "usable": ace.slot_usable_for_print(s, mode), "spool_id": bindings.get(s["global_index"])} for s in slots]
    view = {k: v for k, v in view.items() if k != "file_details"}   # some file's details, maybe not the running one
    data = {**view, "upload_url": "", "mode": mode, "slots": slots, "loaded_slot": loaded, "ace_units": units,
            "can": can_flags(view)}
    return data, units




def _background(fn, name):
    """Teardown that joins threads or closes sockets never runs on the caller (UI thread, agent callback)."""
    threading.Thread(target=fn, name="kobracontrol-" + name, daemon=True).start()


class Service(FilesMixin, JobsMixin, StockMixin, UsageMixin):
    def __init__(self, publish, log=print, cert_dir="", tls=None, http_port=18910, mqtt_port=9883,
                 fetch=kobra.fetch_credentials, ledger_path=None, camera_factory=camera.Camera,
                 spoolman_factory=sm.Spoolman):
        self.publish, self.log = publish, log
        self.cert_dir = cert_dir
        self.tls = tls or connection.tls_from(cert_dir)
        self.http_port, self.mqtt_port, self.fetch = http_port, mqtt_port, fetch
        self.spoolman_factory = spoolman_factory
        self.lock = threading.RLock()
        self._op = threading.local()
        self.connections = {}
        self.target, self.generation = None, 0
        self.closed = False
        self._closing = threading.Event()
        self._changed = threading.Event()
        self.lease_until, self.camera_on = 0.0, False
        self.ledger = usage.Ledger(usage.LedgerStore(ledger_path, log) if ledger_path else None)
        if self.ledger.restore_notice:
            self.log("kobracontrol: " + self.ledger.restore_notice)
        self._units, self._feed_acks, self._capture, self._busy = {}, {}, None, set()
        self._camera_refused = set()
        self._reset_printer_state()
        self.camera = camera_factory(self._camera_url, self._on_frame, "", self._on_camera_error, log=log)
        self.jobs = queue.Queue()
        self.worker = self._thread(self._work, "worker")
        self.monitor = self._thread(self._watch, "monitor")
        self.tracker = self._thread(self._track_loop, "tracker")

    def _thread(self, fn, name):
        t = threading.Thread(target=fn, name="kobracontrol-" + name, daemon=True)
        t.start()
        return t

    def _reset_printer_state(self):   # caller holds self.lock (or is __init__)
        self.spools, self.bindings, self._last_slots = [], {}, None
        self._stock_missing_since = None

    # ------------------------------------------------------------------ connections

    def connection(self, host):
        """The shared Connection for a printer address, started on first use (its thread does the I/O)."""
        with self.lock:
            conn = self.connections.get(host)
            if conn is None:
                conn = connection.Connection(host, self.tls, self.log, self.http_port, self.mqtt_port, self.fetch)
                conn.add_listener(self._on_change)
                self.connections[host] = conn
                conn.start()
            return conn

    def release(self, host):
        """Close the connection to `host` unless the tab or a listener still uses it."""
        with self.lock:
            conn = self.connections.get(host)
            if conn is None or (self.target and self.target.host == host) or conn.listeners != [self._on_change]:
                return
            del self.connections[host]
        _background(conn.stop, "release")

    def _on_change(self, conn):   # a connection's reader or loop thread: no I/O here
        self._changed.set()

    def view_for(self, host):
        conn = self.connections.get(host)
        return conn.view() if conn else None

    # ------------------------------------------------------------------ page plumbing

    def set_target(self, target):
        with self.lock:
            changed = self.target is None or self.target.key() != target.key()
            previous = self.target.host if self.target else None
            if changed:
                self.generation += 1
                self._reset_printer_state()
            self.target = target
        self.connection(target.host)
        if previous and previous != target.host:
            self.release(previous)

    def clear_target(self):
        with self.lock:
            if self.target is None:
                return
            previous, self.target = self.target.host, None
            self.generation += 1
            self._reset_printer_state()
        _background(self.camera.stop, "camera-stop")
        self.release(previous)

    def touch(self, camera=None, stock=None):
        if stock:
            self.want_stock()
        with self.lock:
            self.lease_until = time.monotonic() + LEASE_SECONDS
            if camera is not None:
                self.camera_on = bool(camera)
        if camera is False:
            _background(self.camera.stop, "camera-stop")

    def ack_frame(self):
        self.camera.ack()

    def submit(self, request_id, command, args, gen=None):
        args = args if isinstance(args, dict) else {}
        with self.lock:
            current, target = self.generation, self.target
        if gen is not None and gen != current:
            self.publish({"type": "reply", "id": request_id, "error": STALE})
            return
        conn = self.connections.get(target.host) if target else None
        job = (request_id, command, args, (current, conn, target, command in URGENT))
        if command in BOUNDED:
            with self.lock:
                busy = command in self._busy
                self._busy.add(command)
            if busy:
                self.publish({"type": "reply", "id": request_id, "error": BUSY % command})
                return
            threading.Thread(target=self._run_bounded, args=job, name="kobracontrol-" + command, daemon=True).start()
        elif command in DEDICATED:
            threading.Thread(target=self._guard, args=(command, lambda: self._run(*job)),
                             name="kobracontrol-" + str(command), daemon=True).start()
        else:
            self.jobs.put(job)

    def _run_bounded(self, request_id, command, args, ctx):
        try:
            self._guard(command, lambda: self._run(request_id, command, args, ctx))
        finally:
            with self.lock:
                self._busy.discard(command)

    def close(self):
        self.closed = True
        self._closing.set()
        self.jobs.put(None)
        self._changed.set()
        self.camera.close()
        for t in (self.worker, self.monitor, self.tracker):
            if t is not threading.current_thread():
                t.join(1.0)
        with self.lock:
            conns, self.connections = list(self.connections.values()), {}
        for conn in conns:
            conn.stop()

    def _work(self):
        while not self.closed:
            job = self.jobs.get()
            if job is None:
                return
            self._guard("command worker", lambda: self._run(*job))

    def _run(self, request_id, command, args, ctx):
        handler = getattr(self, "cmd_" + str(command), None) if re.fullmatch(r"\w+", str(command)) else None
        if handler is None:
            self.publish({"type": "reply", "id": request_id, "error": "unknown command %s" % command})
            return
        gen, _, _, pinned = ctx
        if not pinned and not self._current(gen):
            self.publish({"type": "reply", "id": request_id, "error": STALE})
            return
        try:
            with self._bound(ctx):
                result = handler(**args)
            self.publish({"type": "reply", "id": request_id, "result": result})
        except (kobra.KobraError, certs.CertError, sm.SpoolmanError, ValueError, TypeError) as e:
            reply = {"type": "reply", "id": request_id, "error": str(e)}
            if getattr(e, "no_certificate", False):
                reply["no_certificate"] = True
            self.publish(reply)
        except Exception as e:  # never kill the worker; details go to the log only
            self.log("kobracontrol: %s failed: %s\n%s" % (command, e, traceback.format_exc()))
            self.publish({"type": "reply", "id": request_id, "error": "%s failed: %s" % (command, e)})

    def call(self, host, command, **args):
        """Run cmd_<command> for printer `host` on this thread (the printer agent's commands)."""
        conn = self.connection(host)
        with self._bound((None, conn, Target(host), True)):
            return getattr(self, "cmd_" + command)(**args)

    @contextlib.contextmanager
    def _bound(self, ctx):
        previous = getattr(self._op, "ctx", None)
        self._op.ctx = ctx
        try:
            yield
        finally:
            self._op.ctx = previous

    def _snapshot(self):
        with self.lock:
            target = self.target
            return self.generation, self.connections.get(target.host) if target else None, target

    def _ctx(self):
        """(generation, connection, target) this thread works for; raises once that printer is not selected."""
        ctx = getattr(self._op, "ctx", None)
        if ctx is None:
            gen, conn, target = self._snapshot()
        else:
            gen, conn, target, pinned = ctx
            if not pinned and not self._current(gen):
                raise kobra.KobraError(STALE)
        if conn is None or target is None:
            raise kobra.KobraError(NO_PRINTER)
        return gen, conn, target

    def _current(self, gen):
        with self.lock:
            return gen == self.generation

    def _notice(self, text, gen=None):
        if gen is None or self._current(gen):
            self.publish({"type": "notice", "text": text})

    def _conn(self):
        return self._ctx()[1]

    def _printer(self):
        conn = self._conn()
        printer = conn.printer
        if not conn.connected or printer is None:
            raise kobra.KobraError(conn.error or "the printer is not connected yet")
        return printer

    def _data(self, conn=None):
        conn = conn or self._conn()
        with self.lock:
            bindings = dict(self.bindings) if self.target and self.target.host == conn.host else {}
            before = self._units.get(conn.host, [])
        data, units = status_data(conn.view(), before, bindings)
        with self.lock:
            self._units[conn.host] = units
        return data

    def _allowed(self, flag, what):
        data = self._data()
        if not data["connected"]:
            raise kobra.KobraError(self._conn().error or "the printer is not connected")
        if not data["can"][flag]:
            raise kobra.KobraError("%s is not possible while the printer is %s" % (what, data["state"]))
        return data

    # ------------------------------------------------------------------ monitor and tracker

    def _watch(self):
        next_status = 0.0
        while not self.closed:
            now = time.monotonic()
            with self.lock:
                target, gen = self.target, self.generation
                active = now < self.lease_until and target is not None
                cam = active and self.camera_on and target.camera_enabled
            if not active:
                self._guard("camera", self.camera.stop)
                self._closing.wait(0.25)
                continue
            if now >= next_status:
                next_status = now + STATUS_EVERY
                self._guard("status", lambda: self._push_status(target, gen))
            self._guard("camera", lambda: self._camera_tick(target) if cam else self.camera.stop())
            self._closing.wait(0.1)

    def _push_status(self, target, gen):
        conn = self.connections.get(target.host)
        if conn is None:
            return
        data = self._data(conn)
        if self._current(gen):
            self.publish({"type": "status", "data": data, "gen": gen})
            if not data["connected"]:
                self.publish({"type": "offline", "error": conn.error or "connecting to %s" % target.host,
                              **({"no_certificate": True} if conn.no_certificate else {})})

    def _camera_url(self):
        with self.lock:
            target = self.target
        conn = self.connections.get(target.host) if target else None
        return camera_url_for(conn.view(), conn.host, self.log, self._camera_refused) if conn else ""

    def _camera_tick(self, target):
        """Ask the printer to start its stream (once per stream URL), then keep the reader running."""
        conn = self.connections.get(target.host)
        if not conn or not conn.connected:
            return
        view = conn.view()
        key = (target.host, view["camera_url_rev"], id(conn.printer))
        if key != self._capture:
            self._capture = key
            printer = conn.printer
            threading.Thread(target=lambda: printer.start_camera(), name="kobracontrol-capture", daemon=True).start()
        self.camera.set_ffmpeg(target.ffmpeg_path)
        self.camera.start()

    def _on_frame(self, jpeg):
        self.publish({"type": "frame", "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()})

    def _on_camera_error(self, reason, text):
        self.publish({"type": "camera_error", "reason": reason, "error": text})

    def _track_loop(self):
        retry_at = time.monotonic() + 60
        while not self.closed:
            self._changed.wait(1.0)
            self._changed.clear()
            if self.closed:
                return
            for host, conn in list(self.connections.items()):
                self._guard("tracker", lambda: self._track_one(host, conn))
            self._guard("spoolman", self._follow_slots)
            if time.monotonic() >= retry_at:
                retry_at = time.monotonic() + 60
                self._guard("usage retry", self.retry_due)

    def _track_one(self, host, conn):
        view = conn.view()
        if view["connected"]:
            self._guard("usage", lambda: self.track(host, view))
            self._guard("feed", lambda: self._feed_ack(conn, view))

    def _guard(self, what, fn):
        try:
            fn()
        except Exception as e:
            self.log("kobracontrol: %s: %r" % (what, e))

    def _feed_ack(self, conn, view):
        """As Kobralink (printer-bridge.ts:820-830) and KX-Bridge (bridge_ams.py:426-440): every box reporting
        feed_status 10/11 (a feed or retract finished, from here, the touchscreen or an automatic refill) gets
        feedFilament type 3 for its slot two seconds later. Sent once per event: a status that lingers in later
        reports is not acknowledged again; it is re-armed once the box reports anything else."""
        now = time.monotonic()
        due = []
        with self.lock:
            events = self._feed_acks.setdefault(conn.host, {})
            for box in view.get("multi_color_box") or []:
                status = box.get("feed_status") if isinstance(box.get("feed_status"), dict) else {}
                bid, key = box.get("id", -1), (status.get("current_status"), status.get("slot_index", 0))
                if key[0] not in (10, 11):
                    events.pop(bid, None)
                    continue
                entry = events.get(bid)
                if entry is None or entry["key"] != key:
                    entry = events[bid] = {"key": key, "seen": now, "sent": False}
                if not entry["sent"] and now - entry["seen"] >= FEED_ACK_DELAY:
                    entry["sent"] = True
                    due.append((bid, key[1]))
        printer = conn.printer
        for bid, slot in due:
            if printer:
                printer.feed_filament(bid, slot, 3)

    def _follow_slots(self):
        """spoolman_auto: when a slot's filament changes, bind the closest Spoolman spool (location only; the
        printer is never written)."""
        gen, conn, target = self._snapshot()
        if not (conn and target and target.spoolman_url and target.spoolman_auto and conn.connected):
            return
        slots = {s["global_index"]: s for s in self._data(conn)["slots"]}
        with self.lock:
            previous, self._last_slots = self._last_slots, slots
        if previous is None:
            return
        changed = [g for g, s in slots.items() if s["status"] == 5 and sm.slot_changed(previous.get(g), s)]
        if not changed:
            return
        try:
            self.cmd_spools()
            for g in changed:
                with self.lock:
                    bound = next((s for s in self.spools if s["id"] == self.bindings.get(g)), None)
                    taken, spools = set(self.bindings.values()), list(self.spools)
                score = sm.match_score(slots[g], bound) if bound else None
                if score is not None and score < 60:
                    continue
                pick = sm.best_spool(slots[g], spools, exclude=taken)
                if pick:
                    self.cmd_bind(g, pick["id"])
                    self._notice("S%d now uses Spoolman spool #%d (%s %s)" % (g + 1, pick["id"], pick["vendor"],
                                                                                pick["name"]), gen)
        except (kobra.KobraError, sm.SpoolmanError, ValueError) as e:
            self._notice("Spoolman: %s" % e, gen)

    # ------------------------------------------------------------------ commands

    def cmd_connect(self):
        gen, conn, target = self._ctx()
        if not conn.connected:
            conn.retry()
            conn.wait_connected(CONNECT_WAIT)
        if not conn.connected:
            cls = connection.NoCertificate if conn.no_certificate else kobra.KobraError
            raise cls(conn.error or "the printer at %s did not answer yet" % target.host)
        view = conn.view()
        return {"generation": gen, "address": target.host, "printer": target.name, "model": view["model"],
                "firmware": view["firmware"], "limits": LIMITS}

    def _task_id(self):
        return self._conn().view()["task_id"] or "-1"

    def _answer(self, reply, what, in_progress_ok=False):
        """{"confirmed": True} when the printer reported success; KobraError with its code and msg when it
        reported failure, or when not even the "received" ack came. Received without a result in time is
        {"confirmed": False} when in_progress_ok (pause, stop, homing: the next status shows what happened),
        otherwise kobra.NoResult."""
        try:
            kobra.check_reply(reply, what)
        except kobra.NoResult:
            if in_progress_ok:
                return {"confirmed": False}
            raise
        return {"confirmed": True}

    def cmd_pause(self):
        self._allowed("pause", "pausing")
        return self._answer(self._printer().pause_print(self._task_id()), "the pause", True)

    def cmd_resume(self):
        self._allowed("resume", "resuming")
        return self._answer(self._printer().resume_print(self._task_id()), "the resume", True)   # reply action not captured

    def cmd_stop(self):
        self._allowed("stop", "stopping")
        return self._answer(self._printer().stop_print(self._task_id()), "the stop", True)

    def cmd_set_temp(self, nozzle=None, bed=None):
        data = self._allowed("heat", "heating")
        nozzle = None if nozzle is None else max(0, min(float(nozzle), NOZZLE_MAX))
        bed = None if bed is None else max(0, min(float(bed), BED_MAX))
        if nozzle is None and bed is None:
            raise ValueError("no temperature given")
        if data["state"] == "printing":   # only a running print takes print/update; paused uses tempature/set
            # (Kobralink printer-bridge.ts:1162, KX-Bridge handle_api_temperature)
            sent = self._printer().set_printing_temperature(data["task_id"] or "-1", nozzle, bed)
        else:
            sent = self._printer().set_idle_temperature(nozzle, bed)
        self._sent(sent)
        return {"nozzle": nozzle, "bed": bed}

    def cmd_set_fan(self, pct):
        self._printer()
        return self._sent(self._printer().set_fan(int(max(0, min(100, float(pct))))))

    def cmd_set_light(self, on):
        return self._sent(self._printer().set_light(bool(on), int(self._conn().view()["light_brightness"] or 80)))

    def cmd_set_speed(self, mode):
        mode = int(mode)
        if mode not in (1, 2, 3):   # the Kobra's three modes (Kobralink controls-card.tsx); no reference sends 4
            raise ValueError("speed mode is 1 (quiet) to 3 (sport)")
        data = self._data()
        if data["state"] not in ("printing", "paused"):
            raise kobra.KobraError("the speed mode applies to a running print")
        return self._sent(self._printer().set_print_speed_mode(data["task_id"] or "-1", mode))

    def _sent(self, ok):
        if not ok:
            raise kobra.KobraError("the printer connection dropped; nothing was sent")
        return True

    def cmd_move(self, axis, distance):
        if axis not in AXIS:
            raise ValueError("axis is x, y or z")
        distance = float(distance)
        if not distance or distance != distance:
            raise ValueError("no distance given")
        distance = max(-MOVE_MAX, min(MOVE_MAX, distance))   # one move is never longer than MOVE_MAX
        self._allowed("move", "moving")
        return self._answer(self._printer().move_axis(AXIS[axis], 1 if distance > 0 else 0, abs(distance)), "the move", True)

    def cmd_home(self, axes="xyz"):
        if axes not in HOME:
            raise ValueError("home xyz, xy or z")
        self._allowed("move", "homing")
        return self._answer(self._printer().move_axis(HOME[axes], 2, 0), "homing", True)   # ~37 s; state "busy"

    def cmd_motors_off(self):
        self._allowed("move", "turning the motors off")
        return self._sent(self._printer().disable_steppers())

    def _running_objects(self):
        """(view, object names of the running file), asked of the printer now (file/fileDetails, read-only)."""
        data = self._data()
        if data["state"] not in ("printing", "paused") or not data["filename"]:
            raise kobra.KobraError("no print is running")
        raw = self._printer().file_details(data["filename"]).get("objects_skip_parts")
        names = [str(o.get("name") if isinstance(o, dict) else o) for o in raw if o not in (None, "")] \
            if isinstance(raw, list) else []
        return data, [n for n in names if n and n != "None"]

    def cmd_objects(self):
        data, names = self._running_objects()
        return {"filename": data["filename"], "objects": names, "skipped": list(data["skipped_objects"])}

    def cmd_skip_objects(self, names):
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError("no objects chosen")
        data, objects = self._running_objects()
        unknown = [n for n in names if n not in objects]
        if unknown:
            raise ValueError("not in %s: %s; nothing was skipped" % (data["filename"], ", ".join(unknown)))
        return self._answer(self._printer().skip_objects(names), "the skip")

    # slots and ACE -----------------------------------------------------------------------------------

    def _slot(self, data, slot):
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ValueError("no slot chosen")
        found = next((s for s in data["slots"] if s["global_index"] == slot), None)
        if found is None:
            raise ValueError("slot %d does not exist" % (slot + 1))
        return found

    def cmd_slot_set(self, slot, type, colour):
        data = self._allowed("feed", "editing a slot")
        found = self._slot(data, slot)
        material = str(type or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9+ _-]{1,20}", material):
            raise ValueError("material is 1-20 letters, digits, '+', '-'")
        m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(colour or ""))
        if not m:
            raise ValueError("colour is #RRGGBB")
        rgb = [int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)]
        return self._sent(self._printer().set_ams_slot_info(found["box_id"], found["index"], material, rgb))

    def _feed(self, slot, kind):
        data = self._allowed("feed", "loading filament" if kind == 1 else "unloading filament")
        if kind == 2 and data["loaded_slot"] >= 0:   # Kobralink: retract unloads what is loaded
            slot = data["loaded_slot"]
        found = self._slot(data, slot)
        if kind == 1 and found["status"] != 5:
            raise kobra.KobraError("slot %d is empty" % (slot + 1))
        return self._sent(self._printer().feed_filament(found["box_id"], found["index"], kind))

    def cmd_slot_feed(self, slot):
        return self._feed(slot, 1)

    def cmd_slot_retract(self, slot=-1):
        return self._feed(slot, 2)

    def _aces(self, data, aces):
        ids = [u["id"] for u in data["ace_units"]]
        aces = aces if isinstance(aces, list) else [aces]
        if not aces or any(a not in ids for a in aces):
            raise ValueError("no such ACE unit")
        return aces

    def cmd_auto_feed(self, ace, on):
        data = self._data()
        return self._sent(self._printer().set_auto_feed(self._aces(data, [ace])[0], bool(on)))

    def cmd_dry_start(self, aces, temp, minutes):
        data = self._allowed("heat", "drying")
        temp = int(max(DRY_TEMP[0], min(DRY_TEMP[1], float(temp))))
        minutes = int(max(DRY_MINUTES[0], min(DRY_MINUTES[1], float(minutes))))
        payload = ace.set_dry_payload(self._aces(data, aces), temp, minutes)   # minutes, as the printer counts
        return self._sent(self._printer().set_dry([b["id"] for b in payload["multi_color_box"]],
                                                  payload["multi_color_box"][0]["drying_status"]))

    def cmd_dry_stop(self, aces):
        data = self._data()
        return self._sent(self._printer().set_dry(self._aces(data, aces), {"status": 0}))

    # files (files.FilesMixin: cmd_files, cmd_file_details, cmd_file_print, cmd_file_delete) ----------------

    def cmd_file_print(self, name, auto_leveling=False, vibration_compensation=False):
        conn = self._conn()
        task = supported_task(conn.view(), {"auto_leveling": auto_leveling, "vibration_compensation": vibration_compensation})
        with conn.start_lock:   # the idle check and print/start of one job at a time (agent jobs too)
            return super().cmd_file_print(name, bool(task["auto_leveling"]), bool(task["vibration_compensation"]))

    def _view(self):
        """status.data of the printer this thread works for (FilesMixin reads its slots and mode)."""
        return self._data()

    def _require_idle(self):
        return self._allowed("print", "starting a print")

    # stock --------------------------------------------------------------------------------------------------

    def cmd_stock(self, refresh=False):
        """StockMixin's answer plus `available` and `reason`: "absent" (Spooler not running here), "stale",
        "waiting", "unsupported" (Spooler runs but has published no list for kobracontrol for STOCK_UNSUPPORTED_S:
        released Spooler versions only publish for u1control), or the stock state's code; None when available."""
        out = super().cmd_stock(refresh)
        spooler, stock = out["spooler"]["state"], out["stock"]["state"]
        now = time.monotonic()
        with self.lock:
            if spooler == "active" and stock == "missing":
                self._stock_missing_since = self._stock_missing_since or now
                waited = now - self._stock_missing_since
            else:
                self._stock_missing_since, waited = None, 0.0
        if spooler == "active" and stock == "ok":
            reason = None
        elif spooler != "active":
            reason = "absent" if spooler in ("absent", "stopped") else spooler
        elif stock == "missing":
            reason = "unsupported" if waited >= STOCK_UNSUPPORTED_S else "waiting"
        else:
            reason = stock if stock == "stale" else out["stock"].get("code") or stock
        return {**out, "available": reason is None, "reason": reason}

    def cmd_find_certificate(self, path=None):
        found = find_and_save_certificate(self.cert_dir, path)
        for conn in list(self.connections.values()):
            conn.retry()
        return {"found": True, "source": found.source}

    # spoolman --------------------------------------------------------------------------------------------

    def _spoolman(self, target):
        smc = self.spoolman_factory(target.spoolman_url)
        smc.connect()
        return smc

    def cmd_spools(self):
        gen, _, target = self._ctx()
        spools = [sm.spool_view(s) for s in self._spoolman(target).spools()]
        with self.lock:
            if gen is not None and gen != self.generation:
                raise kobra.KobraError(STALE)
            self.spools, self.bindings = spools, sm.bindings_from_locations(spools, target.name)
            return {"spools": spools, "bindings": {str(k): v for k, v in self.bindings.items()}}

    def cmd_bind(self, slot, spool_id):
        """Link a spool to a slot: its Spoolman location becomes "<printer name> S<n>" (the printer is not written)."""
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise ValueError("no slot chosen")
        if not isinstance(spool_id, int) or isinstance(spool_id, bool) or spool_id <= 0:
            raise ValueError("no spool chosen")
        gen, _, target = self._ctx()
        if not any(s["id"] == spool_id for s in self.spools):
            self.cmd_spools()
        if not any(s["id"] == spool_id for s in self.spools):
            raise ValueError("spool #%d not found in Spoolman" % spool_id)
        smc = self._spoolman(target)
        with self.lock:
            previous = self.bindings.get(slot)
        smc.set_location(spool_id, sm.location_for(target.name, slot))
        if previous and previous != spool_id:
            smc.set_location(previous, "")
        with self.lock:
            if gen is None or gen == self.generation:
                self.bindings = {g: s for g, s in self.bindings.items() if s != spool_id and g != slot}
                self.bindings[slot] = spool_id
            return {"bindings": {str(k): v for k, v in self.bindings.items()}}

    cmd_bind_spool = cmd_bind   # the name stockview.StockMixin calls

    def cmd_unbind(self, slot):
        gen, _, target = self._ctx()
        with self.lock:
            sid = self.bindings.get(slot)
        if sid:
            self._spoolman(target).set_location(sid, "")
        with self.lock:
            if (gen is None or gen == self.generation) and self.bindings.get(slot) == sid:
                self.bindings.pop(slot, None)
            return {"bindings": {str(k): v for k, v in self.bindings.items()}}
