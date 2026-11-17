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
import os
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
import locate
import peers
import requirements
import settings
import spoolman as sm
import usage
from locating import ORIGIN_TEXT, RELOCATE_EVERY, LocatingMixin  # noqa: F401  (tests read RELOCATE_EVERY here)
from jobs import CONNECT_WAIT, PRINT_OPTIONS, JobsMixin, plate_source, remote_name, supported_task  # noqa: F401  (re-exported for callers)
from files import FilesMixin
from stockview import StockMixin
from usage import UsageMixin
from i18n import lazy, tr

LEASE_SECONDS = 6.0
STATUS_EVERY = 1.0
URGENT = ("pause", "stop")      # never wait behind the command worker
# Own thread, at most one of each in flight. home: up to 90 s; device: three read-only queries, up to 5 s unanswered.
BOUNDED = ("stock", "usage", "usage_ack", "find_certificate", "home", "search_printer", "device")
DEDICATED = URGENT + BOUNDED                                    # own short-lived thread
BUSY = lazy("%s is already running; try again when it ends")
STALE = lazy("the selected printer changed; nothing was sent to it")
NO_PRINTER = lazy("no Kobra X selected: choose an Anycubic Kobra X printer preset with its IP address")
NOTHING_LOADED = lazy("no filament is loaded in the print head, so there is nothing to unload")
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
# Print Assist switches by the names Anycubic Slicer Next's page uses -> assistant_settings option numbers.
ASSIST = {"belt": 0, "lostStep": 1, "breakAlert": 3, "jamAlert": 4, "remain": 5}
NAME_MAX = 32                   # printer name, UTF-8 bytes: an assumption (Anycubic's own limit is not known)
NAME_FORBIDDEN = '\\"<>'          # backslash, quote, angle brackets: the same rule as the page (PrinterPanel.vue)
FEED_ACK_DELAY = 2.0            # Kobralink: feedFilament type 3 two seconds after feed_status 10/11
DRY_TEMP, DRY_MINUTES = (30, 80), (10, 24 * 60)   # ace.sanitize_ace_dry_presets bounds




class Target:
    """The tab's printer as the plugin sees it on the UI thread. host: the address in Settings (used as given), else
    "" until the service has located the printer from preset_host, the address remembered for preset_key and a
    network search (locate.py). preset_agent: the printer agent of the selected preset."""

    def __init__(self, host, name=settings.DEFAULT_PRINTER_NAME, spoolman_url="", spoolman_auto=True,
                 spoolman_report_usage=True, ffmpeg_path="", camera_enabled=True, preset_host="", preset_key="",
                 preset_agent=""):
        self.host, self.override, self.name = host, host, name or settings.DEFAULT_PRINTER_NAME
        self.own_spoolman_url, self.spoolman_auto = spoolman_url, spoolman_auto
        self.own_report_usage, self.ffmpeg_path, self.camera_enabled = spoolman_report_usage, ffmpeg_path, camera_enabled
        self.preset_host, self.preset_key, self.preset_agent = preset_host, preset_key, preset_agent
        self.source = "override" if host else ""
        self.identity = ""                 # the located printer's /info identity
        self.spooler_origin = lambda: ""   # the service links this to Spooler's Spoolman address
        self.spooler_books = lambda: False  # ... and to whether Spooler books Anycubic prints itself

    @property
    def spoolman_url(self):
        """The Spoolman address set in Kobra Control, else the one Spooler uses."""
        return self.own_spoolman_url or self.spooler_origin() or ""

    @property
    def spoolman_source(self):
        return "settings" if self.own_spoolman_url else "spooler" if self.spooler_origin() else ""

    @property
    def spoolman_report_usage(self):
        """Book filament use: the setting, except when Spooler books this printer's prints in the same Spoolman
        (it would count every print twice)."""
        if not self.own_report_usage:
            return False
        url = self.spoolman_url
        same = bool(url) and peers_origin(url) == peers_origin(self.spooler_origin())
        return not (same and self.spooler_books())

    def key(self):
        """What selects the printer. Name, Spoolman and camera options are not part of it: changing them applies
        to the live target without touching the connection."""
        return (self.override, self.preset_host, self.preset_key)

    @property
    def ident(self):
        return usage.printer_ident(self.host)


def peers_origin(url):
    return peers.normalize_origin(url) if url else ""


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


class Service(LocatingMixin, FilesMixin, JobsMixin, StockMixin, UsageMixin):
    def __init__(self, publish, log=print, cert_dir="", tls=None, http_port=18910, mqtt_port=9883,
                 fetch=kobra.fetch_credentials, ledger_path=None, camera_factory=camera.Camera, relay_factory=camera.Relay,
                 spoolman_factory=sm.Spoolman, addresses_path=None, search=locate.search, probe=None, granted=None):
        self.publish, self.log = publish, log
        self.cert_dir = cert_dir
        self.tls = tls or connection.tls_from(cert_dir)
        self.pins = certs.Pins(os.path.join(cert_dir, certs.PINS_FILE)) if cert_dir else None
        self.http_port, self.mqtt_port, self.fetch = http_port, mqtt_port, fetch
        self.spoolman_factory = spoolman_factory
        self.lock = threading.RLock()
        self._op = threading.local()
        self.connections = {}
        self.target, self.generation = None, 0
        self.closed = False
        self._init_locating(addresses_path, search, probe, granted)
        self._closing = threading.Event()
        self._changed = threading.Event()
        self.lease_until, self.camera_on = 0.0, False
        self.camera_mse = False      # the page plays H.264 itself (lease `mse`): Relay, no ffmpeg
        self._relay_refused = None   # the stream URL Relay found not to be FLV/H.264: ffmpeg plays that one
        self._told_no_ffmpeg = False   # the ffmpeg path is needed but ffmpeg is missing: told the page once
        self.ledger = usage.Ledger(usage.LedgerStore(ledger_path, log) if ledger_path else None)
        if self.ledger.restore_notice:
            self.log("kobracontrol: " + self.ledger.restore_notice)
        self._units, self._feed_acks, self._capture, self._busy = {}, {}, None, set()
        self._camera_refused = set()
        self._reset_printer_state()
        self.camera = camera_factory(self._camera_url, self._on_frame, "", self._on_camera_error, log=log)
        self.relay = relay_factory(self._camera_url, self._on_video, self._on_relay_error, log=log)
        # ffmpeg and Anycubic Slicer Next: checked once on a thread of their own when the page first asks
        # (check_requirements), never here. agent_seen: plugin.py's answer to "is our printer agent in use".
        self.requirements, self.agent_seen = requirements.Checker(self._publish_requirements, log), False
        self.host_requirements = ()   # certificate and Spooler, set by plugin.py from its config message
        self._requirements_lock = threading.Lock()
        self.jobs = queue.Queue()
        self.worker = self._thread(self._work, "worker")
        self.monitor = self._thread(self._watch, "monitor")
        self.tracker = self._thread(self._track_loop, "tracker")

    def _thread(self, fn, name):
        t = threading.Thread(target=fn, name="kobracontrol-" + name, daemon=True)
        t.start()
        return t

    def _reset_printer_state(self):   # caller holds self.lock (or is __init__): a printer switch
        self.spools, self.bindings, self._last_slots = [], {}, None
        self._stock_missing_since = None
        self._units, self._feed_acks, self._capture = {}, {}, None
        if hasattr(self, "_details"):   # FilesMixin's per-printer file details
            self._details = {}

    # ------------------------------------------------------------------ connections

    def connection(self, host, origin=None, expect_fp=None, identity=None):
        """The shared Connection for a printer address, started on first use (its thread does the I/O). KobraError
        once the service is closed: nothing may start a connection after close(). origin, expect_fp and identity
        (when given) are set before the connection's thread starts, so its first attempt already names where the
        address came from and already checks the certificate pin."""
        with self.lock:
            if self.closed:
                raise kobra.KobraError(tr("Kobra Control is shutting down"))
            conn = self.connections.get(host)
            fresh = conn is None
            if fresh:
                conn = connection.Connection(host, self.tls, self.log, self.http_port, self.mqtt_port, self.fetch,
                                             pins=self.pins)
                if identity is None and self.addresses is not None:
                    # Any path (the printer agent's too): an address known in the address book has its printer's
                    # pin checked under that identity. Warn-only there, as for every address the user gave.
                    known = next((r for r in self.addresses.records() if r["ip"] == host and r["id"]), None)
                    identity = known["id"] if known else None
                conn.add_listener(self._on_change)
                self.connections[host] = conn
            for name, value in (("origin", origin), ("expect_fp", expect_fp), ("identity", identity)):
                if value is not None:
                    setattr(conn, name, value)
            impostor = ""
            if not fresh and expect_fp and conn.connected:
                # A session already open (say by the printer agent, warn-only) and now a pin to enforce: the session
                # must have presented that certificate, or it is closed now, not at its next reconnect.
                seen = (conn.server_cert or {}).get("fingerprint", "")
                if seen != expect_fp:
                    impostor = seen or "none"
                    del self.connections[host]   # whoever else listens: this session is not used any more
            if fresh:
                conn.start()
        if impostor:
            conn.mismatch = impostor
            conn._stop.set()
            conn._fail(tr("A different Kobra X answered at %s: its certificate is not the one of the printer Kobra Control "
                       "knows. It was not used.") % host, False)
            _background(conn.stop, "impostor-stop")
            _background(lambda: self._refuse_impostor(conn), "impostor")
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
        self._note_connection(conn)

    def view_for(self, host):
        conn = self.connections.get(host)
        return conn.view() if conn else None

    # ------------------------------------------------------------------ page plumbing

    def set_target(self, target, retry=False):
        """Select the tab's printer (UI thread: no I/O). Without an address in Settings the printer is located on
        a thread of its own; cmd_connect waits for it. The same target again keeps the address found for it;
        retry (Save) tries a failed connection or search again at once, with a fresh retry delay."""
        target.spooler_origin, target.spooler_books = self._spooler_origin, self._spooler_books
        with self.lock:
            if self.closed:
                return
            changed = self.target is None or self.target.key() != target.key()
            previous = self.target.host if self.target else None
            if not changed and not target.host:
                target.host, target.source, target.identity = self.target.host, self.target.source, self.target.identity
            if changed:
                self.generation += 1
                self._reset_printer_state()
                self.locate_error = None
            self.target, gen = target, self.generation
        if target.host:
            conn = self.connection(target.host, origin=ORIGIN_TEXT.get(target.source, ""))
            if retry and not changed and not conn.connected:
                conn.retry()
        elif changed or retry:
            self._start_locate(gen)
        if previous and previous != target.host:
            self.release(previous)

    def _spooler_books(self):
        peers = self.peers
        try:
            return bool(peers.spooler().get("books_anycubic")) if peers is not None and hasattr(peers, "spooler") else False
        except Exception:
            return False

    def _spooler_origin(self):
        peers = self.peers
        try:
            return peers.spooler()["origin"] if peers is not None and hasattr(peers, "spooler") else ""
        except Exception:   # an unreadable presence file is "no Spooler", never a failed command
            return ""

    def clear_target(self):
        with self.lock:
            if self.target is None:
                return
            previous, self.target = self.target.host, None
            self.generation += 1
            self._reset_printer_state()
        _background(self.stop_cameras, "camera-stop")
        self.release(previous)

    def touch(self, camera=None, stock=None, mse=None):
        if stock:
            self.want_stock()
        with self.lock:
            self.lease_until = time.monotonic() + LEASE_SECONDS
            if camera is not None:
                self.camera_on = bool(camera)
            if mse is not None:
                self.camera_mse = bool(mse)
        if camera is False:
            _background(self.stop_cameras, "camera-stop")

    def ack_frame(self):
        self.camera.ack()

    def submit(self, request_id, command, args, gen=None):
        args = args if isinstance(args, dict) else {}
        with self.lock:
            current, target = self.generation, self.target
        if gen is not None and gen != current:
            self.publish({"type": "reply", "id": request_id, "error": tr(STALE)})
            return
        conn = self.connections.get(target.host) if target else None
        job = (request_id, command, args, (current, conn, target, command in URGENT))
        if command in BOUNDED:
            with self.lock:
                busy = command in self._busy
                self._busy.add(command)
            if busy:
                self.publish({"type": "reply", "id": request_id, "error": tr(BUSY) % command})
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
        """Stop everything; safe to call more than once. A locate thread still running finds the service closed
        and starts nothing (connection() refuses), so no connection outlives close()."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
        self._closing.set()
        self.jobs.put(None)
        self._changed.set()
        self.camera.close()
        self.relay.close()
        for t in (self.worker, self.monitor, self.tracker):
            if t is not threading.current_thread():
                t.join(1.0)
        self._join_locators()
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
            self.publish({"type": "reply", "id": request_id, "error": tr("unknown command %s") % command})
            return
        gen, _, _, pinned = ctx
        if not pinned and not self._current(gen):
            self.publish({"type": "reply", "id": request_id, "error": tr(STALE)})
            return
        try:
            with self._bound(ctx):
                result = handler(**args)
            self.publish({"type": "reply", "id": request_id, "result": result})
        except (kobra.KobraError, certs.CertError, sm.SpoolmanError, ValueError, TypeError) as e:
            reply = {"type": "reply", "id": request_id, "error": str(e)}
            if getattr(e, "no_certificate", False):
                reply["no_certificate"] = True
            if getattr(e, "no_target", False):
                reply["no_target"] = True
                reply["candidates"] = [{"ip": c.get("ip", ""), "name": c.get("name", ""), "model": c.get("model", ""),
                                        "needs_allow": bool(c.get("needs_allow")), "different": bool(c.get("different"))}
                                       for c in e.candidates]
                reply["pending"] = list(e.pending)
            self.publish(reply)
        except Exception as e:  # never kill the worker; details go to the log only
            self.log("kobracontrol: %s failed: %s\n%s" % (command, e, traceback.format_exc()))
            self.publish({"type": "reply", "id": request_id, "error": tr("%s failed: %s") % (command, e)})

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
                raise kobra.KobraError(tr(STALE))
        if conn is None or target is None:
            raise kobra.KobraError(tr(NO_PRINTER))
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
            raise kobra.KobraError(conn.error or tr("the printer is not connected yet"))
        return printer

    def _data(self, conn=None):
        conn = conn or self._conn()
        with self.lock:
            bindings = dict(self.bindings) if self.target and self.target.host == conn.host else {}
            before = self._units.get(conn.host, [])
        data, units = status_data(conn.view(), before, bindings)
        data["tls"] = dict(conn.server_cert) if conn.server_cert else None
        with self.lock:
            self._units[conn.host] = units
        return data

    def _allowed(self, flag, what):
        data = self._data()
        if not data["connected"]:
            raise kobra.KobraError(self._conn().error or tr("the printer is not connected"))
        if not data["can"][flag]:
            raise kobra.KobraError(tr("%s is not possible while the printer is %s") % (what, tr(data["state"])))
        return data

    # ------------------------------------------------------------------ monitor and tracker

    def _watch(self):
        next_status = 0.0
        while not self.closed:
            now = time.monotonic()
            with self.lock:
                target, gen = self.target, self.generation
                active = now < self.lease_until and target is not None
                cam = active and self.camera_on   # without ffmpeg the page's own player still runs (_camera_tick)
            if not active:
                self._guard("camera", self.stop_cameras)
                self._closing.wait(0.25)
                continue
            if now >= next_status:
                next_status = now + STATUS_EVERY
                self._guard("status", lambda: self._push_status(target, gen))
            self._guard("camera", lambda: self._camera_tick(target) if cam else self.stop_cameras())
            self._closing.wait(0.1)

    def _push_status(self, target, gen):
        conn = self.connections.get(target.host)
        if conn is None:
            return
        data = self._data(conn)
        if self._current(gen):
            self.publish({"type": "status", "data": data, "gen": gen})
            if not data["connected"]:
                self.publish({"type": "offline", "error": conn.error or tr("connecting to %s") % target.host,
                              "retry_at": conn.next_try, **({"no_certificate": True} if conn.no_certificate else {})})

    def _camera_url(self):
        with self.lock:
            target = self.target
        conn = self.connections.get(target.host) if target else None
        return camera_url_for(conn.view(), conn.host, self.log, self._camera_refused) if conn else ""

    def _camera_tick(self, target):
        """Ask the printer to start its stream (once per stream URL), then keep the reader running."""
        conn = self.connections.get(target.host)
        printer = conn.printer if conn else None   # read once: the loop may replace the session meanwhile
        if printer is None or not conn.connected:
            return
        view = conn.view()
        key = (target.host, view["camera_url_rev"], id(printer))
        if key != self._capture:
            self._capture = key
            threading.Thread(target=printer.start_camera, name="kobracontrol-capture", daemon=True).start()
        url = self._camera_url()
        if self.camera_mse and url.lower().startswith("http://") and url != self._relay_refused:
            self.camera.stop()
            self.relay.start()
            self._told_no_ffmpeg = False
            return
        # ffmpeg: an RTSP stream, a page that cannot play H.264, or a stream Relay could not read
        self.relay.stop()
        if self.requirements.ffmpeg() == "":   # known missing: not started, said once
            self.camera.stop()
            if not self._told_no_ffmpeg:
                self._told_no_ffmpeg = True
                self.publish({"type": "camera_error", "reason": "no_ffmpeg", "error": tr("ffmpeg was not found")})
            return
        self.camera.set_ffmpeg(self.requirements.ffmpeg() or target.ffmpeg_path)
        self.camera.start()

    def stop_cameras(self):
        self.camera.stop()
        self.relay.stop()
        self._told_no_ffmpeg = False

    def check_requirements(self, ffmpeg_setting, force=False):
        """Start the file checks unless they are cached for this ffmpeg setting (force: Check again); their answer
        is published when they finish. Publishes the requirements as they stand now (UI thread: no I/O)."""
        self.requirements.ensure(ffmpeg_setting, force)
        self._publish_requirements()

    def requirements_message(self):
        with self.lock:
            target = self.target
        return requirements.message(self.requirements, self.agent_seen, target.spoolman_url if target else "",
                                    self.host_requirements)

    def _publish_requirements(self):
        with self._requirements_lock:   # built and sent together: a finished check is never followed by an older state
            self.publish(self.requirements_message())

    def _on_frame(self, jpeg):
        self.publish({"type": "frame", "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()})

    def _on_video(self, part):
        b64 = {k: base64.b64encode(v).decode() if isinstance(v, bytes) else v for k, v in part.items()}
        self.publish({"type": "video", **b64})

    def _on_relay_error(self, reason, text):
        if reason == "unsupported":   # not FLV/H.264: hand this stream to ffmpeg on the next tick
            self._relay_refused = self._camera_url()
            self.log("kobracontrol camera: %s; using ffmpeg" % text)
            return
        self._on_camera_error(reason, text)

    def _on_camera_error(self, reason, text):
        if reason == "no_ffmpeg":   # gone since the check: missing now, so the monitor stops starting the camera
            self.requirements.mark_missing("ffmpeg")
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
                    self._notice(tr("S%d now uses Spoolman spool #%d (%s %s)") % (g + 1, pick["id"], pick["vendor"],
                                                                                pick["name"]), gen)
        except (kobra.KobraError, sm.SpoolmanError, ValueError) as e:
            self._notice(tr("Spoolman: %s") % e, gen)

    # ------------------------------------------------------------------ commands

    def cmd_connect(self, retry=False):
        """The tab's hello. Only the user's Retry (retry=True) cuts the connection's backoff short; otherwise a
        connection that already failed answers its error at once and keeps its retry delay. Without an address
        it first waits for the printer to be located (a NotFound names the candidates, if any)."""
        with self.lock:   # check and reset together: a locate thread may set a new error at the same moment
            gen, target = self.generation, self.target
            again = retry is True and target is not None and not target.host and self.locate_error is not None
            if again:
                self.locate_error = None
        if again:
            self._start_locate(gen)
        target = self.wait_located(CONNECT_WAIT + 2 * (locate.SEARCH_SECONDS + locate.SEND_GAP) + 2 * locate.PROBE_TIMEOUT)
        if not self._current(gen):
            raise kobra.KobraError(tr(STALE))
        conn = self.connection(target.host)
        if not conn.connected:
            failures = conn.failures
            if retry is True:
                conn.retry()
            if retry is True or not conn.error:
                conn.wait_attempt(CONNECT_WAIT, failures)
        if not conn.connected:
            with self.lock:
                offer = self.locate_error if gen == self.generation else None
            if getattr(offer, "candidates", None):
                # The known printer is down and another Kobra X answered: the reply carries that offer, so the
                # page keeps showing "Use it?" while the known address keeps being retried.
                raise locate.NotFound("%s %s" % (conn.error or tr("The known printer does not answer."), offer),
                                      offer.candidates, rejected=offer.rejected)
            cls = connection.NoCertificate if conn.no_certificate else kobra.KobraError
            raise cls(conn.error or tr("the printer at %s did not answer yet") % target.host)
        view = conn.view()
        return {"generation": gen, "address": target.host, "printer": target.name, "model": view["model"],
                "firmware": view["firmware"], "limits": LIMITS, "source": target.source,
                "note": self.locate_note if target.source in ("discovered", "chosen") else ""}

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
        self._allowed("pause", tr("pausing"))
        return self._answer(self._printer().pause_print(self._task_id()), tr("the pause"), True)

    def cmd_resume(self):
        self._allowed("resume", tr("resuming"))
        return self._answer(self._printer().resume_print(self._task_id()), tr("the resume"), True)   # reply action not captured

    def cmd_stop(self):
        self._allowed("stop", tr("stopping"))
        return self._answer(self._printer().stop_print(self._task_id()), tr("the stop"), True)

    def cmd_set_temp(self, nozzle=None, bed=None):
        data = self._allowed("heat", tr("heating"))
        nozzle = None if nozzle is None else max(0, min(float(nozzle), NOZZLE_MAX))
        bed = None if bed is None else max(0, min(float(bed), BED_MAX))
        if nozzle is None and bed is None:
            raise ValueError(tr("no temperature given"))
        if data["state"] == "printing":   # only a running print takes print/update; paused uses tempature/set
            # (Kobralink printer-bridge.ts:1162, KX-Bridge handle_api_temperature)
            sent = self._printer().set_printing_temperature(data["task_id"] or "-1", nozzle, bed)
        else:
            sent = self._printer().set_idle_temperature(nozzle, bed)
        self._sent(sent)
        return {"nozzle": nozzle, "bed": bed}

    def cmd_set_fan(self, pct):
        pct = int(max(0, min(100, float(pct))))
        data, printer = self._data(), self._printer()
        sent = self._sent(printer.set_fan(pct))   # fan/setSpeed, verified on the printer: always sent
        if data["state"] == "printing":
            # Anycubic Slicer Next's Workbench also sets the fan through the running print (UNTESTED): a second
            # message, never instead of fan/setSpeed. Best effort: the fan/setSpeed above already went out.
            printer.set_printing_fan(data["task_id"] or "-1", pct)
        return sent

    def cmd_set_light(self, on):
        # Anycubic Slicer Next's camera light (Workbench toggle-light: status 1/0, brightness 100/0)
        return self._sent(self._printer().set_light(bool(on), 100 if on else 0))

    # printer details and Print Assist ------------------------------------------------------------------
    # Messages from Anycubic Slicer Next 2.0.0.3's Workbench page. UNTESTED on our printer (firmware 2.0.2.8): no answer
    # to any of them was captured yet; what the printer reports shows up in status.data mac / stats / assist.

    def cmd_device(self):
        """Ask the printer for its network address, its print counters and its Print Assist switches (read only),
        only while it is idle: untested messages are never sent during a print. The answers arrive as reports; a
        firmware that does not answer leaves those fields empty."""
        self._allowed("print", tr("reading the printer's details"))
        printer = self._printer()
        sent = [printer.query_net(), printer.query_statistics()]
        assist = printer.query_properties()
        return {"sent": all(sent), "assist": kobra.succeeded(assist) if assist and not kobra.is_ack_only(assist) else False}

    def cmd_assist(self, option, on):
        """Turn one Print Assist switch on or off (idle printer only). option: "autoFeed" (every ACE's auto-feed,
        as Anycubic Slicer Next does) or one of ASSIST, which the printer must have reported as supported."""
        data = self._allowed("print", tr("changing Print Assist"))
        self._not_reading()
        if option == "autoFeed":
            ids = [u["id"] for u in data["ace_units"]]
            if not ids:
                raise kobra.KobraError(tr("no ACE is connected"))
            printer = self._printer()
            return self._sent(all([printer.set_auto_feed(i, bool(on)) for i in ids]))
        number = ASSIST.get(option)
        if number is None:
            raise ValueError(tr("unknown Print Assist option %r") % (option,))
        if number not in (data.get("assist") or {}):
            raise kobra.KobraError(tr("the printer did not report this Print Assist option; nothing was sent"))
        return self._answer(self._printer().set_assist([{"option": number, "value": 1 if on else 0}]),
                            tr("the Print Assist change"), True)

    def _not_reading(self):
        """A write waits until the read-only device queries are done: their answers share the report topics."""
        with self.lock:
            busy = "device" in self._busy
        if busy:
            raise kobra.KobraError(tr("the printer's details are still being read; nothing was sent, try again in a moment"))

    def cmd_rename(self, name):
        """The printer's own name (info/setPrinterName), on an idle printer."""
        name = " ".join(str(name or "").split())
        if not name or len(name.encode("utf-8")) > NAME_MAX or any(ord(c) < 32 or c in NAME_FORBIDDEN for c in name):
            raise ValueError(tr("the name is 1-%d bytes (UTF-8), without quotes, backslashes or angle brackets") % NAME_MAX)
        self._allowed("print", tr("renaming the printer"))
        self._not_reading()
        printer = self._printer()
        result = self._answer(printer.set_printer_name(name), tr("the new name"), True)
        printer.query_info()
        return {**result, "name": name}

    def cmd_set_speed(self, mode):
        mode = int(mode)
        if mode not in (1, 2, 3):   # the Kobra's three modes (Kobralink controls-card.tsx); no reference sends 4
            raise ValueError(tr("speed mode is 1 (quiet) to 3 (sport)"))
        data = self._data()
        if data["state"] not in ("printing", "paused"):
            raise kobra.KobraError(tr("the speed mode applies to a running print"))
        return self._sent(self._printer().set_print_speed_mode(data["task_id"] or "-1", mode))

    def _sent(self, ok):
        if not ok:
            raise kobra.KobraError(tr("the printer connection dropped; nothing was sent"))
        return True

    def cmd_move(self, axis, distance):
        if axis not in AXIS:
            raise ValueError(tr("axis is x, y or z"))
        distance = float(distance)
        if not distance or distance != distance:
            raise ValueError(tr("no distance given"))
        distance = max(-MOVE_MAX, min(MOVE_MAX, distance))   # one move is never longer than MOVE_MAX
        self._allowed("move", tr("moving"))
        return self._answer(self._printer().move_axis(AXIS[axis], 1 if distance > 0 else 0, abs(distance)), tr("the move"), True)

    def cmd_home(self, axes="xyz"):
        if axes not in HOME:
            raise ValueError(tr("home xyz, xy or z"))
        self._allowed("move", tr("homing"))
        return self._answer(self._printer().move_axis(HOME[axes], 2, 0), tr("homing"), True)   # ~37 s; state "busy"

    def cmd_motors_off(self):
        self._allowed("move", tr("turning the motors off"))
        return self._sent(self._printer().disable_steppers())

    def _running_objects(self):
        """(view, object names of the running file), asked of the printer now (file/fileDetails, read-only)."""
        data = self._data()
        if data["state"] not in ("printing", "paused") or not data["filename"]:
            raise kobra.KobraError(tr("no print is running"))
        raw = self._printer().file_details(data["filename"]).get("objects_skip_parts")
        names = [str(o.get("name") if isinstance(o, dict) else o) for o in raw if o not in (None, "")] \
            if isinstance(raw, list) else []
        return data, [n for n in names if n and n != "None"]

    def cmd_objects(self):
        data, names = self._running_objects()
        return {"filename": data["filename"], "objects": names, "skipped": list(data["skipped_objects"])}

    def cmd_skip_objects(self, names):
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError(tr("no objects chosen"))
        data, objects = self._running_objects()
        unknown = [n for n in names if n not in objects]
        if unknown:
            raise ValueError(tr("not in %s: %s; nothing was skipped") % (data["filename"], ", ".join(unknown)))
        return self._answer(self._printer().skip_objects(names), tr("the skip"))

    # slots and ACE -----------------------------------------------------------------------------------

    def _slot(self, data, slot):
        if not isinstance(slot, int) or isinstance(slot, bool):
            raise ValueError(tr("no slot chosen"))
        found = next((s for s in data["slots"] if s["global_index"] == slot), None)
        if found is None:
            raise ValueError(tr("slot %d does not exist") % (slot + 1))
        return found

    def cmd_slot_set(self, slot, type, colour):
        data = self._allowed("feed", tr("editing a slot"))
        found = self._slot(data, slot)
        material = str(type or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9+ _-]{1,20}", material):
            raise ValueError(tr("material is 1-20 letters, digits, '+', '-'"))
        m = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(colour or ""))
        if not m:
            raise ValueError(tr("colour is #RRGGBB"))
        rgb = [int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4)]
        return self._sent(self._printer().set_ams_slot_info(found["box_id"], found["index"], material, rgb))

    def _feed(self, slot, kind):
        data = self._allowed("feed", tr("loading filament") if kind == 1 else tr("unloading filament"))
        if kind == 2 and data["loaded_slot"] >= 0:   # Kobralink: retract unloads what is loaded
            slot = data["loaded_slot"]
        elif kind == 2 and isinstance(slot, int) and slot < 0:   # "unload" without a slot and nothing loaded
            raise kobra.KobraError(tr(NOTHING_LOADED))
        found = self._slot(data, slot)
        if kind == 1 and found["status"] != 5:
            raise kobra.KobraError(tr("slot %d is empty") % (slot + 1))
        return self._sent(self._printer().feed_filament(found["box_id"], found["index"], kind))

    def cmd_slot_feed(self, slot):
        return self._feed(slot, 1)

    def cmd_slot_retract(self, slot=-1):
        return self._feed(slot, 2)

    def _aces(self, data, aces):
        ids = [u["id"] for u in data["ace_units"]]
        aces = aces if isinstance(aces, list) else [aces]
        if not aces or any(a not in ids for a in aces):
            raise ValueError(tr("no such ACE unit"))
        return aces

    def cmd_auto_feed(self, ace, on):
        data = self._data()
        return self._sent(self._printer().set_auto_feed(self._aces(data, [ace])[0], bool(on)))

    def cmd_dry_start(self, aces, temp, minutes):
        data = self._allowed("heat", tr("drying"))
        temp = int(max(DRY_TEMP[0], min(DRY_TEMP[1], float(temp))))
        minutes = int(max(DRY_MINUTES[0], min(DRY_MINUTES[1], float(minutes))))
        payload = ace.set_dry_payload(self._aces(data, aces), temp, minutes)   # minutes, as the printer counts
        return self._sent(self._printer().set_dry([b["id"] for b in payload["multi_color_box"]],
                                                  payload["multi_color_box"][0]["drying_status"]))

    def cmd_dry_stop(self, aces):
        data = self._data()
        return self._sent(self._printer().set_dry(self._aces(data, aces), {"status": 0}))

    # files (files.FilesMixin: cmd_files, cmd_file_details, cmd_file_print, cmd_file_delete, and the time-lapse
    # videos' cmd_videos and cmd_video_delete) -------------------------------------------------------------

    def cmd_file_print(self, name, auto_leveling=False, vibration_compensation=False, flow_calibration=False,
                       timelapse=False):
        conn = self._conn()
        task = supported_task(conn.view(), {"auto_leveling": auto_leveling, "vibration_compensation": vibration_compensation,
                                            "flow_calibration": flow_calibration, "timelapse": timelapse})
        with conn.start_lock:   # the idle check and print/start of one job at a time (agent jobs too)
            return super().cmd_file_print(name, *(bool(task[k]) for k in PRINT_OPTIONS))

    def _view(self):
        """status.data of the printer this thread works for (FilesMixin reads its slots and mode)."""
        return self._data()

    def _require_idle(self):
        return self._allowed("print", tr("starting a print"))

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
                raise kobra.KobraError(tr(STALE))
            self.spools, self.bindings = spools, sm.bindings_from_locations(spools, target.name)
            return {"spools": spools, "bindings": {str(k): v for k, v in self.bindings.items()}}

    def links_for(self, target):
        """(spools, {slot: spool id}) for target from Spoolman, for the printer agent before (or without) the tab;
        the tab's own spools and links are left alone. ([], {}) without a Spoolman address."""
        target.spooler_origin = self._spooler_origin
        if not target.spoolman_url:
            return [], {}
        spools = [sm.spool_view(s) for s in self._spoolman(target).spools()]
        return spools, sm.bindings_from_locations(spools, target.name)

    def cmd_bind(self, slot, spool_id):
        """Link a spool to a slot: its Spoolman location becomes "<printer name> S<n>" (the printer is not written)."""
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
            raise ValueError(tr("no slot chosen"))
        if not isinstance(spool_id, int) or isinstance(spool_id, bool) or spool_id <= 0:
            raise ValueError(tr("no spool chosen"))
        gen, _, target = self._ctx()
        if not any(s["id"] == spool_id for s in self.spools):
            self.cmd_spools()
        if not any(s["id"] == spool_id for s in self.spools):
            raise ValueError(tr("spool #%d not found in Spoolman") % spool_id)
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
