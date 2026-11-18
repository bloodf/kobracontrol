"""OrcaSlicer glue: the Anycubic Kobra X printer agent, the Kobra Control tab and two scripts. The only module
that imports `orca`. Printer work runs in service.py on the plugin's own threads; everything here that runs
on OrcaSlicer's UI thread only queues work and returns."""

import base64
import json
import os
import re
import sys
import tempfile
import threading
import time
import zlib

import orca

import ace
import bambu
import bridge
import certs
import gcode_check
import i18n
import locate
import kobra
import peers
import printsetup


import requirements
import settings
import spooler_bridge
from i18n import tr
from service import (BED_MAX, LIMITS, NOTHING_LOADED, NOZZLE_MAX, Service, Target, camera_url_for, can_flags,
                     find_and_save_certificate, status_data)

VERSION = "0.0.0-dev"
AGENT_ID = "kobracontrol"
AGENT_NAME = "Anycubic Kobra X (kobracontrol)"
MODEL = "Anycubic Kobra X"
TLS_DIR = "tls"          # never "cert(s)": the plugin sandbox refuses such path components
LEDGER_FILE = "usage_ledger.json"
ADDRESSES_FILE = "addresses.json"   # printer preset -> the Kobra X found for it (locate.Addresses)
CHECK_SECONDS = 20.0                # Check Kobra X connection: locating and connecting together
_granted = set()   # printer addresses declared at load or allowed since: the search probes only these by itself
_refused = set()   # addresses refused in OrcaSlicer's dialog this session: asked again only on a user action
_queue_on_main = None   # OrcaSlicer's queue_on_main, once it hands it to the printer agent
_last_hints = ("", "", "")   # preset_hints() as last read on the UI thread, for the script's worker thread
STOP_WAIT = 10.0   # s a restart worker waits for the previous bridge to let go of its port (an upload may be finishing)
UI_WAIT = 5.0      # s a worker thread waits for the UI thread to read the presets
# OrcaSlicer status codes (src/slic3r/Utils/bambu_networking.hpp, v2.5.0)
OK, ERR_INVALID_HANDLE, ERR_CANCELED, ERR_INVALID_RESULT = 0, -1, -18, -19
ERR_LP_UPLOAD, ERR_LP_PUBLISH, ERR_SG_UPLOAD, ERR_CONNECT = -4020, -4030, -5010, -6010
STAGE_CREATE, STAGE_UPLOAD, STAGE_SENDING, STAGE_FINISHED, STAGE_ERROR = 0, 1, 3, 6, 7
CONNECT_OK = 0
PUSH_EVERY = 0.5         # s between Device tab status pushes at most
CATALOG_EVERY = 30.0     # s between re-reads of Spooler's presets, profiles.json and the Spoolman links for tray ids

_service = None
_service_lock = threading.Lock()
_link = None
_store = None
_store_lock = threading.Lock()
_storage_dir = None
_bridge = None            # the running upload bridge (bridge.Bridge), None while off
_bridge_error = ""       # why it is not running although on (shown in Settings)
_bridge_key = ""         # the key when there is no storage folder to keep it in (this session only)
_agent_seen = False   # our printer agent is in use: OrcaSlicer made one, or its selected printer names it
_preset_notices = set()   # orca_filament_preset names already reported as not usable this session
_user_presets_failed = False
# Preset.is_compatible is bound in OrcaSlicer 2.5 (PluginHostPresets.cpp); a host without it reads as compatible
# (True), as OrcaSlicer itself treats a preset with no compatibility condition.
COMPATIBLE_DEFAULT = True


def log(msg):
    line = "[kobracontrol] " + str(msg)
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc))


def clean(value):
    return value.strip().strip('"') if isinstance(value, str) else ""


def host_of(address):
    """'http://192.168.1.5:18910/x' -> '192.168.1.5' (scheme, port and path stripped)."""
    text = clean(address).split("://", 1)[-1].split("/", 1)[0]
    if text.startswith("["):
        return text[1:].split("]", 1)[0]
    return text.rsplit(":", 1)[0] if text.count(":") == 1 else text


def is_kobra_x(*values):
    return any(re.search(r"kobra[ _-]*x\b", clean(v), re.I) for v in values if v)


def json_for_html(data):
    """JSON safe inside a <script> block: no literal <, > or & can end it or open a tag."""
    return json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ---------------------------------------------------------------------- storage, settings, assets

def _storage():
    """The plugin's storage folder ("" when unknown). OrcaSlicer 2.5 answers plugin.storage() only inside a
    plugin callback, so the first answer is kept for the worker threads."""
    global _storage_dir
    if _storage_dir:
        return _storage_dir
    try:
        _storage_dir = orca.host.plugin.storage() or None
    except Exception as e:
        log("no storage folder (%s)" % e)
    return _storage_dir or ""


def _storage_or_raise():
    folder = _storage()
    if not folder:
        raise RuntimeError("no storage folder")
    return folder


def cert_dir():
    folder = _storage()
    return os.path.join(folder, TLS_DIR) if folder else ""


def get_store(cap=None):
    """The shared settings store: a file in the storage folder, else the capability's own config."""
    global _store
    with _store_lock:
        if _store is None:
            try:
                _store = settings.Store(os.path.join(_storage_or_raise(), "settings.json"))
            except Exception as e:
                log("settings: no storage folder (%s); using the plugin config" % e)
                if cap is None:
                    return settings.Store()
                _store = settings.Store(load=lambda: json.dumps(_cap_config(cap).get("kobra_settings") or {}),
                                        save=lambda text: cap.save_config(
                                            json.dumps({**_cap_config(cap), "kobra_settings": json.loads(text)})))
        return _store


def _cap_config(cap):
    try:
        data = json.loads(cap.get_config())
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _asset(name):
    """From the generated _assets module in the wheel; from src/kobracontrol/ui during development."""
    if __package__:
        from . import _assets
        if name == "icon.svg":
            return _assets.ICON_SVG
        return zlib.decompress(base64.b64decode(_assets.APP_HTML_Z64)).decode("utf-8")
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", name), encoding="utf-8") as f:
        return f.read()


def _host_language():
    try:
        attr = orca.host.app_language
        lang = attr() if callable(attr) else attr
    except Exception:
        return None
    return lang if isinstance(lang, str) and lang else None


def sync_language():
    """The plugin's own texts (i18n.py) follow the page: the language chosen in Settings, else OrcaSlicer's. Called
    from plugin callbacks, where OrcaSlicer answers; while its language can't be read, the last one stays."""
    try:
        choice, host = get_store().effective()["ui_language"], _host_language()
        if choice in i18n.LANGUAGES or host:
            i18n.set_language(i18n.resolve(choice, host))
    except Exception as e:
        log("language not read (%s)" % e)


def page_html(language="auto", mode="app", data=None):
    """The Kobra Control tab ("app"), or the print dialog ("print", with its data)."""
    boot = {"version": VERSION, "lang": _host_language(),
            "pref": language if language in settings.UI_LANGUAGES else "auto", "mode": mode, "data": data}
    return _asset("app.html").replace("__BOOT__", json_for_html(boot), 1)


# ---------------------------------------------------------------------- service and Spooler link

def note_agent():
    """Whether "Use printer agents instead of print hosts" is on, as far as a plugin can tell (OrcaSlicer.conf is
    not readable): OrcaSlicer created a KobraAgent this session, or orca.host.selected_printer() reports our agent.
    UI thread only (a host call); a host without that call, or one that fails, leaves the answer "not detected"."""
    global _agent_seen
    if not _agent_seen:
        try:
            selected = orca.host.selected_printer()
            agent = selected.get("agent") if hasattr(selected, "get") else getattr(selected, "agent", "")
            _agent_seen = clean(agent) == AGENT_ID
        except Exception:
            pass
    return _agent_seen


_service_options = {}   # extra Service keyword arguments (tests only: ports and fakes of a loopback printer)
_users = set()          # loaded capabilities that use the service: closed once none is left


def _use(name):
    with _service_lock:
        _users.add(name)


def _unuse(name):
    """`name` unloaded; the last one out closes the service (and the Spooler link with the page)."""
    global _service
    with _service_lock:
        _users.discard(name)
        svc = _service if not _users else None
        if svc is not None:
            _service = None
    if svc is not None:
        svc.close()


def service(publish=None):
    global _service
    with _service_lock:
        if _service is None:
            folder = _storage()
            _service = Service(publish or (lambda m: None), log, cert_dir=cert_dir(),
                               ledger_path=os.path.join(folder, LEDGER_FILE) if folder else None,
                               addresses_path=os.path.join(folder, ADDRESSES_FILE) if folder else None, granted=_granted,
                               **_service_options)
        elif publish is not None:
            _service.publish = publish
        _service.peers = _link
        return _service


# ---------------------------------------------------------------------- upload bridge (opt-in)

def bridge_key(renew=False, create=True):
    """The bridge's API key: kept in the storage folder (mode 0600), else for this session only. create=False only
    reads it ("" when there is none yet): the bridge's requests and Settings while the bridge is off."""
    global _bridge_key
    folder = _storage()
    if folder:
        if renew:
            return bridge.write_key(folder, bridge.new_key())
        return bridge.key_for(folder) if create else bridge.read_key(folder)
    if not create and not renew:
        return _bridge_key
    if renew or not _bridge_key:
        _bridge_key = bridge.new_key()
    return _bridge_key


def _bridge_upload(path, filename, plate_index, start):
    """The bridge's thread: the file to the printer Kobra Control has selected (located now if the tab never was open)."""
    svc = service()
    if svc.target is None:   # never read the presets here: the UI thread does (preset_hints_from_worker)
        svc.set_target(_target(preset_hints_from_worker(svc)))
    try:
        svc.wait_located(CHECK_SECONDS)
    except Exception as e:
        raise bridge.Refused(503, str(e)) from None
    return svc.bridge_upload(path, filename, plate_index, start, get_store().effective())


def sync_bridge(on_change=None):
    """Start, restart or stop the bridge as Settings say. Binds on the caller's thread: OrcaSlicer asks for the
    127.0.0.1 network permission there when it was not granted at load. Never waits: when the previous bridge on
    the port is still stopping, a worker waits for it and binds again, then calls on_change() (the page's config)."""
    global _bridge, _bridge_error
    cfg = get_store().effective()
    want, folder = cfg["bridge_enabled"], _storage()   # an upload is written to the storage folder first
    if _bridge is not None and (not want or _bridge.port != cfg["bridge_port"]):
        stop_bridge()
    _bridge_error = ""
    if want and _bridge is None and not folder:
        _bridge_error = tr("no storage folder for the uploads")
    elif want and _bridge is None:
        try:
            bridge_key()   # made once here; requests only read it
            _bridge = _make_bridge(cfg["bridge_port"], folder)
        except OSError as e:
            stopping = _stopping
            if stopping is not None and stopping.is_alive() and stopping.port == cfg["bridge_port"]:   # off and on quickly
                _bridge_error = tr("waiting for the previous bridge to close")
                threading.Thread(target=_retry_bridge, args=(stopping, cfg["bridge_port"], folder, on_change),
                                 name="kobracontrol-bridge-retry", daemon=True).start()
            else:
                _bridge_error = tr("port %d could not be opened (%s)") % (cfg["bridge_port"], e.strerror or e)
                log("upload bridge not started: %s" % _bridge_error)


_stopping = None   # the thread stopping the previous bridge, while it runs


def _make_bridge(port, folder):
    return bridge.Bridge(port, lambda: bridge_key(create=False), _bridge_upload, folder, log).start()


def _retry_bridge(stopping, port, folder, on_change):
    """Worker: wait for the old bridge to let go of the port, bind once more if Settings still want this one."""
    global _bridge, _bridge_error
    stopping.join(STOP_WAIT)
    cfg = get_store().effective()
    if _bridge is None and cfg["bridge_enabled"] and cfg["bridge_port"] == port:
        try:
            _bridge, _bridge_error = _make_bridge(port, folder), ""
        except OSError as e:
            _bridge_error = tr("port %d could not be opened (%s)") % (port, e.strerror or e)
            log("upload bridge not started: %s" % _bridge_error)
    if on_change is not None:
        try:
            on_change()
        except Exception as e:
            log("bridge state not shown: %r" % e)


def stop_bridge():
    global _bridge, _stopping
    running, _bridge = _bridge, None
    if running is not None:   # shutdown waits for a request in progress: never on the UI thread
        _stopping = threading.Thread(target=running.stop, name="kobracontrol-bridge-stop", daemon=True)
        _stopping.port = running.port
        _stopping.start()


def bridge_state():
    cfg = get_store().effective()
    return {"enabled": cfg["bridge_enabled"], "running": _bridge is not None, "port": _bridge.port if _bridge else cfg["bridge_port"],
            "host": bridge.HOST, "key": bridge_key(create=cfg["bridge_enabled"]), "error": _bridge_error}


def start_link():
    global _link
    with _service_lock:
        if _link is not None:
            return _link
        root = peers.data_root(_storage())
        if not root:
            log("no OrcaSlicer data folder found; Spooler's stock can't be shown here")
            return None
        _link = peers.SpoolerLink(root, VERSION, log)
        _link.presence.start()
        if _service is not None:
            _service.peers = _link
        return _link


def stop_link():
    global _link
    with _service_lock:
        link, _link = _link, None
        if _service is not None:
            _service.peers = None
    if link is not None:
        link.presence.stop()


def spooler_state():
    try:
        ids = list(orca.host.preset.bundles.list_ids())
    except Exception:
        ids = []
    try:
        collection = orca.host.preset_bundle().filaments
        meta = [{"name": collection.preset(i).name, "bundle_id": getattr(collection.preset(i), "bundle_id", "") or ""}
                for i in range(collection.size())]
    except Exception:
        meta = []
    try:
        has_file = os.path.exists(os.path.join(spooler_bridge.data_dir(_storage_or_raise()), spooler_bridge.SETTINGS_FILE))
    except Exception:
        has_file = False
    return {**spooler_bridge.detect(ids, meta, has_file), "url": spooler_bridge.URL}


def filament_catalog():
    """(Spooler presets, printer label) for the Device tab's tray ids; UI thread, no I/O. Presets: the Spooler
    presets OrcaSlicer counts as compatible with the selected printer, the only ones its sync from AMS loads, as
    spooler_bridge.tray_filament_id meta."""
    bundle = orca.host.preset_bundle()
    printer = bundle.current_printer_preset()
    collection = bundle.filaments
    presets = []
    for i in range(collection.size()):
        preset = collection.preset(i)
        if (getattr(preset, "bundle_id", "") or "") != spooler_bridge.BUNDLE_ID or not getattr(preset, "is_compatible", COMPATIBLE_DEFAULT):
            continue
        first = lambda key: (spooler_bridge.as_list(preset.config_value(key)) or [""])[0]   # noqa: E731
        presets.append({"name": preset.name, "bundle_id": spooler_bridge.BUNDLE_ID, "vendor": first("filament_vendor"),
                        "colour": first("default_filament_colour") or first("filament_colour")})
    return presets, clean(printer.config_value("printer_model")) or printer.name


def user_presets():
    """The user's own filament presets, for a spool's orca_filament_preset (spooler_bridge.find_user_preset); UI
    thread, no I/O. Not system or default presets, and not a plugin bundle's (named "_local/...")."""
    collection = orca.host.preset_bundle().filaments
    out = []
    for i in range(collection.size()):
        preset = collection.preset(i)
        if preset.is_user() and not preset.name.startswith("_local/"):
            out.append({"name": preset.name, "compatible": bool(getattr(preset, "is_compatible", COMPATIBLE_DEFAULT)), "file": preset.file or "",
                        "inherits": clean(preset.config_value("inherits"))})
    return out


def _user_presets_safe():
    """user_presets(), or [] when they can't be read (logged once a session): the rest of the catalog still works."""
    global _user_presets_failed
    try:
        return user_presets()
    except Exception as e:
        if not _user_presets_failed:
            _user_presets_failed = True
            log("own filament presets not readable (%s); orca_filament_preset is ignored" % e)
        return []


def certificate_state():
    try:   # as connection.tls_from: a saved pair counts only when it loads
        certs.context(*certs.paths(cert_dir()))
        return {"found": True, "source": "saved"}
    except certs.CertError:
        if certs.bundled():
            return {"found": True, "source": "bundled"}
        return {"found": False}


def preset_hints():
    """(address, preset name, printer agent) of the selected printer preset, or ("", name, agent) when it is not a
    Kobra X: its print_host stripped of scheme, port and path. The address is only a hint (locate.py): a preset
    made for another agent (Kobralink's Moonraker bridge, say) often points to that bridge, not the printer."""
    bundle = orca.host.preset_bundle()
    preset = bundle.current_printer_preset()
    agent = clean(preset.config_value("printer_agent")) or clean(bundle.full_config_value("printer_agent"))
    if agent != AGENT_ID and not is_kobra_x(preset.config_value("printer_model"), preset.name,
                                            preset.config_value("inherits")):
        return "", preset.name, agent
    host = host_of(preset.config_value("print_host")) or host_of(bundle.full_config_value("print_host"))
    return host, preset.name, agent


def ui_preset_hints():
    """UI thread only: preset_hints(), kept for worker threads; ("", "", "") when no preset can be read yet."""
    global _last_hints
    try:
        _last_hints = preset_hints()
    except Exception as e:   # no preset bundle yet: the network search still runs
        log("printer preset not readable (%s)" % e)
        return "", "", ""
    return _last_hints


def on_main(key, fn, default):
    """Worker thread: fn() run on the UI thread through queue_on_main, waited for at most UI_WAIT s; default without
    queue_on_main, when fn raises, or when the UI thread has not started fn in time (fn then never runs). Once fn has
    started (a dialog of its own may be up) its answer is waited for."""
    queue, box, done, lock = _queue_on_main, {}, threading.Event(), threading.Lock()
    if queue is None:
        return default

    def task():
        with lock:   # the worker gave up waiting: it has moved on, so no read and no dialog any more
            if box.get("cancelled"):
                return
            box["started"] = True
        try:
            box["value"] = fn()
        finally:
            done.set()
    try:
        queue(lambda: call_safely(key, task))
    except Exception as e:
        log("queue_on_main failed: %r" % e)
        return default
    if not done.wait(UI_WAIT):
        with lock:
            if not box.get("started"):
                box["cancelled"] = True
                return default
        done.wait()
    return box.get("value", default)


def preset_hints_from_worker(svc):
    """Worker thread: preset_hints() read on the UI thread (and the preset's address asked about there, a script
    being a user action). Presets are never read off the UI thread: without an answer, the hints the tab last read."""
    def read():
        hints = ui_preset_hints()
        grant_on_ui_thread(svc, hints[0], user=True)
        return hints
    return on_main("check_connection", read, _last_hints)


def ui_preset_gcode_problems():
    """UI thread only: gcode_check.preset_problems() of the selected printer preset when it is a Kobra X (or uses
    this agent); [] for another printer or when it can't be read."""
    try:
        bundle = orca.host.preset_bundle()
        preset = bundle.current_printer_preset()
        agent = clean(preset.config_value("printer_agent")) or clean(bundle.full_config_value("printer_agent"))
        if agent != AGENT_ID and not is_kobra_x(preset.config_value("printer_model"), preset.name,
                                                preset.config_value("inherits")):
            return []
        return gcode_check.preset_problems(preset.config_value("gcode_skip_config_block"),
                                           preset.config_value("thumbnails"))
    except Exception as e:
        log("printer preset not checked (%s)" % e)
        return []


def preset_gcode_warnings():
    """Worker thread: translated warnings about the selected Kobra X preset's G-code settings, read on the UI thread;
    [] (the check skipped) when OrcaSlicer does not answer in time."""
    try:
        return [tr(text) % values if values else tr(text)
                for text, values in on_main("check_gcode", ui_preset_gcode_problems, [])]
    except Exception as e:
        log("printer preset not checked (%s)" % e)
        return []


def warn(warnings):
    """OrcaSlicer's warning notification for each text, from a short thread of its own: push_notification hands the
    call to the UI thread itself and waits for it (PluginHostUi.cpp v2.5.1:672, run_on_ui_blocking), and a print job
    should not wait on the UI thread. A failed notification is only logged."""
    def push():
        try:
            ui = orca.host.ui
            level = getattr(ui.NotificationLevel, "WarningNotificationLevel", None) or ui.NotificationLevel.RegularNotificationLevel
            for text in warnings:
                ui.push_notification(level, "Kobra Control: " + text)
        except Exception as e:
            log("notification failed: %r" % e)
    if warnings:
        threading.Thread(target=push, name="kobracontrol-notify", daemon=True).start()


def finished_line(text, warnings):
    """The Print dialog's last line: short, the full warnings are in the notification."""
    return text + " " + tr("G-code warning: see the notification.") if warnings else text


def _target(hints=None):
    """The tab's target. hints: preset_hints() already read on the UI thread; None reads them here (UI thread)."""
    cfg = get_store().effective()
    preset_host, preset_name, agent = ui_preset_hints() if hints is None else hints
    return Target(host_of(cfg.get("host")), settings.printer_label(cfg.get("printer_name")),
                  clean(cfg.get("spoolman_url")), bool(cfg["spoolman_auto"]), bool(cfg["spoolman_report_usage"]),
                  clean(cfg.get("ffmpeg_path")), bool(cfg["camera_enabled"]), preset_host=preset_host,
                  preset_key=preset_name, preset_agent=agent)


def slicer_temp_root():
    """OrcaSlicer's per-user temp folder, where the sliced .3mf for Print/Send is written: OrcaSlicer.cpp:1335
    per_user_temp_dir(wxFileName::GetTempDir(), per_user_temp_id()) -> utils.cpp:1559-1575: "<temp>/orcaslicer_
    <uid>" on macOS and Linux, "<temp>" itself on Windows (empty id). wxFileName::GetTempDir and Python's
    tempfile.gettempdir both follow TMPDIR/TMP/TEMP, so they name the same folder in practice."""
    base = tempfile.gettempdir().rstrip("/\\") or os.sep
    return base if os.name == "nt" else os.path.join(base, "orcaslicer_%d" % os.getuid())


def job_read_grants():
    """Tree read grants for slicer_temp_root(): its realpath form first (e.g. /private/var/folders/... on macOS),
    then the given form when it differs."""
    out = []
    root = slicer_temp_root()
    for form in (os.path.realpath(root), root):
        target = form.rstrip("/\\") + "/*"
        if target not in out:
            out.append(target)
    return out


def known_hosts():
    """Printer addresses known at load, for the network permission request: the Settings address and the addresses
    found for presets before. Only the plugin's own files: plugins load on a thread of their own while OrcaSlicer's
    UI thread is still loading presets, so reading the printer preset here races it (and can crash OrcaSlicer).
    The preset's address is granted later, on the UI thread (grant_on_ui_thread)."""
    hosts = set()
    try:
        hosts.add(host_of(get_store().effective().get("host")))
    except Exception as e:
        log("settings not readable at load (%s)" % e)
    folder = _storage()
    if folder:
        hosts.update(locate.Addresses(os.path.join(folder, ADDRESSES_FILE)).hosts())
    return sorted(h for h in hosts if h)


def grant_on_ui_thread(svc, host, user=False):
    """UI thread only: let OrcaSlicer ask about a printer address not granted at load (the preset's print_host, the
    Device tab's printer). The audited event (svc._ask_orcaslicer: getaddrinfo of a numeric LAN address, no network
    I/O) shows its dialog inline and saves a Yes; an address allowed in an earlier session passes silently. Off the
    UI thread each refused attempt would queue another dialog instead. An address refused this session is asked
    about again only on a user action (user: Save, connecting the Device tab, the Check script), never on the tab's
    own hello or a selection change."""
    if not host or host in _granted or not locate.lan_address(host) or (host in _refused and not user):
        return
    try:
        svc._ask_orcaslicer(host)
    except PermissionError:
        _refused.add(host)
        log("network access to %s not allowed" % host)
        return
    except OSError:
        pass
    _refused.discard(host)
    _granted.add(host)


# ====================================================================== Kobra Control tab

class KobraControlPage(orca.pages.PagesPluginCapabilityBase):
    def get_name(self):
        return "Kobra Control"

    def get_icon(self):
        """The icon file in the plugin storage folder (data_dir(), writable for the plugin); none without it."""
        svg = _asset("icon.svg")
        for folder in [f for f in [_storage()] if f]:
            path = os.path.join(folder, "kobracontrol.svg")
            try:
                try:
                    with open(path, encoding="utf-8") as f:
                        same = f.read() == svg
                except OSError:
                    same = False
                if not same:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(svg)
                return path
            except OSError as e:
                log("icon: can't write %s (%s)" % (path, e))
        return ""

    def get_default_config(self):
        return {}

    def get_ui(self):
        sync_language()
        return page_html(get_store(self).effective()["ui_language"])

    def on_message(self, data):
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        svc = service(self.post_message)
        try:
            if kind == "hello":
                sync_language()
                target = _target()
                grant_on_ui_thread(svc, target.preset_host)
                svc.set_target(target)   # locates the printer and starts its connection on their own threads
                svc.touch(camera=False)
                svc.submit(data.get("id"), "connect", {"retry": data.get("retry") is True})   # only Retry skips the backoff
                self._requirements(svc, self._post_config())
            elif kind == "check_requirements":   # Settings > Requirements > Check again: all of them, now
                self._requirements(svc, self._post_config(), force=True)
            elif kind == "lease":
                svc.touch(camera=data.get("camera"), stock=data.get("stock") is True, mse=data.get("mse") is True)
            elif kind == "frame_ack":
                svc.ack_frame()
            elif kind == "video_ack":   # the page took one fragment of the built-in player's stream
                svc.video_ack()
            elif kind == "video_reset":   # the page's player needs the stream's init segment again
                svc.video_reset()
            elif kind == "video_error":   # the page's player cannot play this stream: fall back to ffmpeg
                svc.video_error()
            elif kind == "cmd":
                svc.touch()
                gen = data.get("gen")
                svc.submit(data.get("id"), data.get("cmd"), data.get("args") or {},
                           gen if isinstance(gen, int) and not isinstance(gen, bool) else None)
            elif kind == "allow_hosts":   # UI thread: OrcaSlicer's dialog for a printer the search found
                result = svc.allow(data.get("hosts"), user=data.get("user") is True)
                self.post_message({"type": "reply", "id": data.get("id"), "result": result})
            elif kind == "bridge_new_key":   # the old key stops working at once
                bridge_key(renew=True)
                self.post_message(self._config_message())
                self.post_message({"type": "reply", "id": data.get("id"), "result": {"renewed": True}})
            elif kind == "ui_language":
                get_store(self).update({"ui_language": data.get("value")})
                sync_language()
            elif kind == "save_settings":
                get_store(self).update(dict(data.get("settings") or {}))
                sync_bridge(lambda: self.post_message(self._config_message()))
                target = _target()
                grant_on_ui_thread(svc, target.preset_host, user=True)
                svc.set_target(target, retry=True)   # a new address connects at once; the same one now
                result = {"saved": True}
                self._requirements(svc, self._post_config(), force=True)   # a Settings save checks again too
                self.post_message({"type": "reply", "id": data.get("id"), "result": result})
        except Exception as e:
            self.post_message({"type": "reply", "id": data.get("id"), "error": str(e)})

    def _post_config(self):
        config = self._config_message()
        self.post_message(config)
        return config

    def _requirements(self, svc, config, force=False):
        """Publish the requirements: the certificate and Spooler as the config just read them, the printer agent as
        seen now (UI thread), ffmpeg and Anycubic Slicer Next from the cached check (started on its own thread)."""
        cert, spooler = config["certificate"], config["spooler"]
        svc.host_requirements = (
            requirements.item("certificate", requirements.OK if cert.get("found") else requirements.MISSING,
                              cert.get("source", "") if cert.get("found") else ""),
            requirements.item("spooler", requirements.OK if spooler.get("installed") else requirements.MISSING))
        svc.agent_seen = note_agent()
        svc.check_requirements(clean(get_store(self).effective().get("ffmpeg_path")), force)

    def _config_message(self):
        cfg = get_store(self).effective()
        spooler = spooler_state()
        spooler["dismissed"] = bool(cfg["spooler_hint_dismissed"])
        target = _service.target if _service is not None else None
        located = {"address": target.host, "source": target.source, "preset_host": target.preset_host,
                   "preset_agent": target.preset_agent, "spoolman_url": target.spoolman_url,
                   "spoolman_source": target.spoolman_source} if target else None
        return {"type": "config", "settings": cfg, "certificate": certificate_state(), "spooler": spooler,
                "version": VERSION, "limits": dict(LIMITS), "located": located, "agent_id": AGENT_ID,
                "bridge": bridge_state()}

    def on_lifecycle_event(self, event, ctx):
        if event == getattr(orca.LifecycleEvent, "DeviceSelected", None) or (
                event == getattr(orca.LifecycleEvent, "PresetSelected", None) and getattr(ctx, "msg", "") == "printer"):
            self.post_message({"type": "selection_changed"})

    def on_load(self):
        _storage()
        sync_language()
        _use("page")
        try:
            start_link()
        except Exception as e:
            log("Spooler discovery not started: %r" % e)
        try:
            sync_bridge(lambda: self.post_message(self._config_message()))
        except Exception as e:
            log("upload bridge not started: %r" % e)

    def on_unload(self):
        stop_bridge()
        stop_link()
        _unuse("page")


# ====================================================================== printer agent

pa = orca.printer_agent


def _parse_json(text, default):
    try:
        value = json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def job_filaments(params):
    """(tray ids, [{"colour", "type"}]) from PrintParams.ams_mapping / ams_mapping_info (SelectMachine.cpp
    get_ams_mapping_result: one entry per project filament)."""
    trays = [int(t) if isinstance(t, (int, float)) and not isinstance(t, bool) else -1
             for t in _parse_json(getattr(params, "ams_mapping", ""), [])]
    info = _parse_json(getattr(params, "ams_mapping_info", ""), [])
    filaments = []
    for i in range(len(trays)):
        item = info[i] if i < len(info) and isinstance(info[i], dict) else {}
        filaments.append({"colour": str(item.get("sourceColor") or "#FFFFFF"), "type": str(item.get("filamentType") or "")})
    return trays, filaments


def job_task(params, defaults):
    """The print options of an OrcaSlicer job. Its Print dialog never offers vibration compensation (SelectMachine.cpp
    sends task_vibration_cali false), so the Kobra Control setting is the default.

    Auto-leveling is sent when the dialog's Bed Leveling AND the Kobra Control setting (on by default) are on: the
    dialog starts it "on" for a printer it has no saved choice for (support_bed_leveling 1, on/off), so the setting
    is how auto-leveling stays off for OrcaSlicer prints.

    Flow calibration and time-lapse are UNTESTED on the printer, so they are opt-in: sent only when the dialog's
    choice AND the Kobra Control setting (Print defaults, off by default) are both on. The dialog alone is not
    enough: its Flow Dynamics Calibration and Timelapse start "on" for a printer it has no saved choice for
    (SelectMachine.cpp load_option_vals falls back to "on" for on/off options)."""
    def opt(name):
        return bool(getattr(params, name, False))
    return {"auto_leveling": opt("task_bed_leveling") and defaults.get("auto_leveling") is not False,
            "vibration_compensation": opt("task_vibration_cali") or bool(defaults.get("vibration_compensation")),
            "flow_calibration": opt("task_flow_cali") and defaults.get("flow_calibration") is True,
            "timelapse": opt("task_record_timelapse") and defaults.get("timelapse") is True}


DIALOG_TIMEOUT = 15 * 60   # s the print dialog may stay open before the print is abandoned
DIALOG_READY = 20          # s for the dialog's page to report it is showing
DIALOG_REFRESH = 2.0       # s between slot updates sent to the open dialog
_open_dialogs = set()   # one Event per open print setup window; the agent's on_unload sets them: it closes, nothing is sent
_open_dialogs_lock = threading.Lock()


def ask_print(params, host, path, trays, filaments, task, cancel_fn):
    """Kobra Control's print dialog, on the print job's thread (never OrcaSlicer's UI thread: create_window queues
    the window there and returns). Starts from OrcaSlicer's dialog's choice, the printer's slots and the Spoolman
    links; returns (tray ids, filaments, task) as print_job takes them, exactly as the user left them.
    Raises printsetup.Cancelled, or KobraError when the printer is busy or the answer can't be used."""
    svc, cfg = service(), get_store().effective()
    data, names = svc.print_snapshot(host)   # a busy printer: the dialog says so and keeps Print off
    plate = printsetup.plate_summary(path, getattr(params, "plate_index", 1))
    described = [{"colour": f["colour"], "type": f["type"]} for f in filaments]
    fils = printsetup.job_filaments(trays, described, plate)
    mode = data["mode"]
    start = printsetup.initial_trays(trays, fils, data["slots"], mode)
    printer = settings.printer_label(cfg.get("printer_name"))
    remembered = printsetup.remembered_for(cfg["print_memory"], host) if cfg["remember_print_options"] else {}
    options = printsetup.offered_options(cfg, data.get("features"), task, remembered)
    units = data.get("ace_units") or []
    auto_feed = all(u.get("auto_feed") for u in units) if units else None
    job = {"name": clean(params.project_name) or clean(params.task_name), "plate": getattr(params, "plate_index", 1),
           "seconds": plate["seconds"], "grams": plate["grams"], "metres": round(plate["metres"], 2),
           "thumbnail": plate["thumbnail"]}
    page = printsetup.page_data({"name": printer, "host": host, "state": data["state"], "can_print": data["can"]["print"],
                                 "model": data.get("model") or MODEL}, job, fils, data, names,
                                start, options, auto_feed, cfg["remember_print_options"])
    answer, data = _show_print_dialog(page, host, cancel_fn, data)
    choice = printsetup.read_answer(answer, fils, data["slots"], data["mode"], start, options, auto_feed)
    ids, described = printsetup.tray_list(choice["trays"], fils, len(trays))
    feed = choice["auto_feed"] if auto_feed is not None and choice["auto_feed"] != auto_feed else None
    return {"trays": ids, "filaments": described, "task": choice["task"], "auto_feed": feed,
            "name": printsetup.task_name(choice["name"], job["name"]),
            "remember": lambda: remember_choice(host, choice["remember"],
                                                {o["key"]: choice["task"][o["key"]] for o in options if not o["lock"]})}


def remember_choice(host, remember_on, task):
    """After the print started: the "Remember these options" choice, and this printer's options when it is on. task
    holds only the options the user could change: a locked one stays unremembered, so turning its setting on later
    starts it from OrcaSlicer's choice."""
    store = get_store()
    if remember_on is not None:
        store.update({"remember_print_options": remember_on})
    if store.effective()["remember_print_options"]:
        store.update({"print_memory": printsetup.remember(store.effective()["print_memory"], host, task)})


def _show_print_dialog(page, host, cancel_fn, data):
    """Open the dialog and wait for its answer on this (job) thread. Returns (answer, the printer's status data the
    window showed last): the answer is checked against the slots the user saw."""
    ui = orca.host.ui
    done, ready, stop = threading.Event(), threading.Event(), threading.Event()
    box, shown = {}, [data]   # shown: one item, the printer data the window shows now
    offline = [False]         # the window shows the printer offline (a read failed)

    wanted = threading.Event()

    def on_message(msg):
        if not isinstance(msg, dict):
            return
        if msg.get("ready"):
            ready.set()
        if msg.get("refresh"):
            wanted.set()
        if msg.get("open_settings"):   # the Kobra Control tab, when open, switches to Settings
            try:
                service().publish({"type": "show_tab", "tab": "settings"})
            except Exception as e:   # UI thread: nothing may escape
                log("print dialog: Settings not shown (%r)" % e)

    def on_submit(msg):
        box["answer"] = msg
        done.set()

    closing = threading.Event()
    with _open_dialogs_lock:
        _open_dialogs.add(closing)
    html = page_html(get_store().effective()["ui_language"], "print", page)
    window = ui.create_window(html, title=tr("Kobra Control — print setup"), width=560, height=780, on_message=on_message,
                              on_close=done.set, on_submit=on_submit, style=ui.WINDOW_MODAL)

    def refresher():   # slots or state changed on the printer (touchscreen, ACE) show up in the open dialog
        while not stop.is_set():
            asked = wanted.wait(DIALOG_REFRESH)
            wanted.clear()
            if stop.is_set():
                return
            try:
                fresh, names = service().print_snapshot(host)
                last = shown[0]
                if asked or offline[0] or fresh["slots"] != last["slots"] or fresh["state"] != last["state"]:
                    shown[0] = fresh
                    offline[0] = False
                    window.post({"slots": printsetup.page_slots(fresh, names), "state": fresh["state"],
                                 "can_print": fresh["can"]["print"]})
            except Exception as e:   # unreachable meanwhile: the window locks Start print until it answers again
                log("print dialog: slots not refreshed (%s)" % e)
                try:
                    offline[0] = True   # the next good read is posted even when nothing else changed
                    window.post({"slots": printsetup.page_slots(shown[0], {}), "state": "offline", "can_print": False})
                except Exception as e2:
                    log("print dialog: not updated (%s)" % e2)

    threading.Thread(target=refresher, name="kobracontrol-print-dialog", daemon=True).start()
    started = time.monotonic()
    try:
        while not done.wait(0.25):
            waited = time.monotonic() - started
            if (cancel_fn and cancel_fn()) or closing.is_set():
                window.close()
                raise printsetup.Cancelled()
            if waited > DIALOG_TIMEOUT:
                window.close()
                raise kobra.KobraError(tr("the print dialog timed out; nothing was sent"))
            if not window.is_open():
                break
            if not ready.is_set() and waited > DIALOG_READY:
                window.close()
                raise kobra.KobraError(tr("the print dialog didn't open (OrcaSlicer was busy); nothing was sent"))
    finally:
        stop.set()
        with _open_dialogs_lock:
            _open_dialogs.discard(closing)
    return box.get("answer"), shown[0]


def call_safely(key, fn, *args):
    """Run a host callback queued to OrcaSlicer's UI thread. Nothing may escape: an exception leaving a queued call
    ends OrcaSlicer (GUI_App::OnExceptionInMainLoop returns false)."""
    try:
        fn(*args)
    except Exception as e:   # pybind's error_already_set arrives as an Exception too; never re-raised
        try:
            log("host callback %s failed: %r" % (key, e))
        except Exception:
            pass


class KobraAgent(pa.PrinterAgentBase):
    """Printer agent `kobracontrol`: Print / Send and the Device tab over the shared service connection."""

    def __init__(self):
        global _agent_seen
        super().__init__()
        _agent_seen = True   # OrcaSlicer makes printer agents only with "Use printer agents instead of print hosts" on
        self._cb = {}
        self._lock = threading.Lock()
        self.selected = ""
        self.dev_id, self.host, self.access_code = "", "", ""
        self._catalog = ([], "", None)       # (Spooler presets, printer label, Spooler's profiles.json) for tray ids
        self._catalog_at = 0.0
        self._links = ([], {})               # (spools, {slot: spool id}) the agent read from Spoolman itself
        self._links_busy = threading.Lock()
        self._user_presets = None            # user_presets(), once read on the UI thread
        self._file_ids = {}                  # (preset file, mtime) -> spooler_bridge.standalone_id
        self._was_connected = False
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._pusher = None
        self._camera_key = None
        self._camera_refused = set()

    def get_name(self):
        return AGENT_NAME

    def get_agent_info(self):
        return pa.AgentInfo(AGENT_ID, AGENT_NAME, VERSION, tr("Anycubic Kobra X over the LAN (MQTT), by kobracontrol"))

    # host callbacks: stored, may be None ------------------------------------------------------------
    def _store(self, key, fn):
        with self._lock:
            self._cb[key] = fn
        return OK

    def set_on_ssdp_msg_fn(self, fn): return self._store("ssdp", fn)
    def set_on_local_connect_fn(self, fn): return self._store("local_connect", fn)
    def set_on_local_message_fn(self, fn): return self._store("local_message", fn)
    def set_on_message_fn(self, fn): return self._store("message", fn)
    def set_on_user_message_fn(self, fn): return self._store("user_message", fn)
    def set_on_printer_connected_fn(self, fn): return self._store("printer_connected", fn)
    def set_on_subscribe_failure_fn(self, fn): return self._store("subscribe_failure", fn)
    def set_server_callback(self, fn): return self._store("server_error", fn)
    def set_queue_on_main_fn(self, fn):
        global _queue_on_main
        _queue_on_main = fn   # also for the Check script's preset read (preset_hints_from_worker)
        return self._store("queue_on_main", fn)

    def _emit(self, key, *args):
        """Call a host callback the way MoonrakerPrinterAgent dispatches: through queue_on_main when set."""
        with self._lock:
            fn, queue = self._cb.get(key), self._cb.get("queue_on_main")
        if fn is None:
            return
        try:
            if queue is not None:
                queue(lambda: call_safely(key, fn, *args))
            else:
                fn(*args)
        except Exception as e:
            log("host callback %s failed: %r" % (key, e))

    def _message(self, payload):
        self._emit("local_message", self.dev_id, json.dumps(payload))

    # discovery and selection --------------------------------------------------------------------------
    def start_discovery(self, start, sending):
        if start and self.host:
            self._announce()
        return True

    def _announce(self):
        """MoonrakerPrinterAgent announce_printhost_device: the configured printer, never a network scan."""
        view = service().view_for(self.host) or {}
        self._emit("ssdp", json.dumps({
            "dev_name": view.get("printer_name") or MODEL, "dev_id": self.dev_id or self.host, "dev_ip": self.host,
            "dev_type": MODEL, "dev_signal": "0", "connect_type": "lan", "bind_state": "free", "sec_link": "secure",
            "ssdp_version": "v1"}))

    def get_user_selected_machine(self):
        return self.selected

    def set_user_selected_machine(self, dev_id):
        self.selected = dev_id or ""
        return OK

    def bind_detect(self, dev_ip, sec_link, detect):
        view = service().view_for(host_of(dev_ip)) or {}
        detect.dev_id = self.dev_id if self.host and self.host == host_of(dev_ip) else dev_ip
        detect.dev_name = view.get("printer_name") or MODEL
        detect.model_id = MODEL
        detect.version = view.get("firmware") or ""
        detect.connect_type = "lan"
        detect.bind_state = "free"
        return OK

    # connection -----------------------------------------------------------------------------------------
    def connect_printer(self, params):
        """UI thread: remember the printer, attach to its shared connection (whose own thread does the I/O)."""
        host = host_of(getattr(params, "host", ""))
        if not host or not getattr(params, "dev_id", ""):
            return ERR_INVALID_HANDLE
        sync_language()
        grant_on_ui_thread(service(), host, user=True)
        previous = self._detach()
        self.dev_id, self.host, self.access_code = params.dev_id, host, getattr(params, "password", "") or ""
        self._catalog_at = 0.0   # the first push re-reads Spooler's profiles.json
        self._links = ([], {})   # another printer's links never reach this one's trays
        self._refresh_catalog()
        self._was_connected = False
        self._stop = threading.Event()
        self._pusher = threading.Thread(target=self._push_loop, args=(self._stop,), name="kobracontrol-agent",
                                        daemon=True)
        self._pusher.start()
        _use("agent")
        service().connection(host).add_listener(self._on_change)
        if previous != host:
            self._release(previous)
        self._dirty.set()
        return OK

    def disconnect_printer(self):
        host = self._detach()
        self.dev_id = self.host = ""
        self._release(host)
        return OK

    @staticmethod
    def _release(host):
        svc = _service   # only the running service: never start a new one while the plugin unloads
        if host and svc is not None:
            threading.Thread(target=svc.release, args=(host,), name="kobracontrol-release", daemon=True).start()

    def on_load(self):
        _use("agent")

    def on_unload(self):
        with _open_dialogs_lock:
            for closing in _open_dialogs:
                closing.set()
        self.disconnect_printer()
        _unuse("agent")

    def _detach(self):
        host = self.host
        self._stop.set()
        self._dirty.set()
        if host and _service is not None:
            conn = _service.connections.get(host)
            if conn:
                conn.remove_listener(self._on_change)
        return host

    def _refresh_catalog(self, profiles=None):
        """UI thread, no I/O: re-read Spooler's presets (it adds its own at any time), then the slots' links from
        Spoolman on a thread of their own, so sync from AMS knows them without the tab ever opening."""
        try:
            presets, label = filament_catalog()
            users = _user_presets_safe()
            target = _target()
        except Exception as e:
            log("filament presets not readable (%s); trays show generic presets" % e)
            return
        self._catalog = (presets, label, profiles if profiles is not None else self._catalog[2])
        self._user_presets = users
        threading.Thread(target=self._load_links, args=(target,), name="kobracontrol-links", daemon=True).start()

    def _load_links(self, target):
        if not self._links_busy.acquire(blocking=False):
            return   # the last read is still running
        try:
            self._links = service().links_for(target)
        except Exception as e:   # Spoolman down: keep the last links
            log("Spoolman links for the Device tab not read (%s)" % e)
        finally:
            self._links_busy.release()

    def _bound_spools(self):
        """{slot global_index: Spoolman spool} for this printer's slots linked to spools: the tab's (up to date
        with every link made there) when it shows this printer, else the agent's own read."""
        svc = _service
        spools, bindings = self._links
        if svc is not None:
            with svc.lock:
                if svc.target and svc.target.host == self.host and svc.spools:
                    spools, bindings = list(svc.spools), dict(svc.bindings)
        by_id = {s["id"]: s for s in spools}
        return {g: by_id[sid] for g, sid in bindings.items() if sid in by_id}

    def _preferred(self):
        """preferred(slot) for bambu.push_status: the filament_id of the slot's spool's preset, or ""."""
        if time.time() - self._catalog_at >= CATALOG_EVERY:   # this thread may read files, not presets
            self._catalog_at = time.time()
            folder = spooler_bridge.data_dir(_storage())
            profiles = spooler_bridge.read_json(folder, spooler_bridge.PROFILES_FILE)
            with self._lock:
                queue = self._cb.get("queue_on_main")
            if queue is not None:
                queue(lambda: call_safely("filament catalog", self._refresh_catalog, profiles or {}))
        bound = self._bound_spools()
        presets, label, profiles = self._catalog

        def preferred(slot):
            spool = bound.get(slot["global_index"])
            return self._linked_id(spool) or spooler_bridge.tray_filament_id(spool, presets, profiles, label)
        return preferred

    def _linked_id(self, spool):
        """The filament_id of the user preset a spool names in Spoolman (orca_filament_preset), or "" to keep the
        usual id. A name that isn't a compatible user preset is reported once a session."""
        name, users = (spool or {}).get("orca_preset"), self._user_presets
        if not name or users is None:
            return ""
        preset, problem = spooler_bridge.find_user_preset(name, users)
        if preset is None:
            self._preset_notice(name, problem)
            return ""
        _preset_notices.discard(name)   # usable again: a later break warns again
        try:
            key = (preset["file"], os.path.getmtime(preset["file"]))
        except (OSError, ValueError):
            key = (preset["file"], None)
        if key not in self._file_ids:   # read once per file version; a bad file is logged once
            self._file_ids[key] = spooler_bridge.standalone_id(preset, log)
        return self._file_ids[key]

    @staticmethod
    def _preset_notice(name, problem):
        if name in _preset_notices:
            return
        _preset_notices.add(name)
        if problem == "ambiguous":
            text = tr('Spoolman names the filament preset "%s", which matches several of your presets in OrcaSlicer '
                      'when upper and lower case are ignored. Its slot keeps the usual preset.') % name
        else:
            text = tr('Spoolman names the filament preset "%s", which isn\'t one of your own presets for this printer '
                      'in OrcaSlicer. Its slot keeps the usual preset.') % name
        log(text)
        if _service is not None:
            _service.publish({"type": "notice", "text": text})

    def _on_change(self, conn):   # the connection's threads: no I/O, no host calls here
        self._dirty.set()

    def _push_loop(self, stop):
        while not stop.is_set():
            self._dirty.wait(5.0)
            self._dirty.clear()
            if stop.is_set():
                return
            try:
                self._push()
            except Exception as e:   # one bad sample must not end the Device tab's status for the session
                log("Device tab status push failed: %r" % e)
            stop.wait(PUSH_EVERY)

    def _push(self):
        view = service().view_for(self.host)
        if view is None:
            return
        if view["connected"] and not self._was_connected:
            # MoonrakerPrinterAgent perform_connection_async: ConnectStatusOk, then printer_connected. Like it,
            # failures are not reported (the host would drop the machine object); the status shows offline.
            self._emit("local_connect", CONNECT_OK, self.dev_id, "0")
            self._emit("printer_connected", self.dev_id)
        self._was_connected = view["connected"]
        if not view["connected"]:
            return
        data, _ = status_data(view)
        self._message(bambu.push_status(view, data["slots"], data["mode"], NOZZLE_MAX, BED_MAX, self._preferred()))

    # commands -------------------------------------------------------------------------------------------
    def send_message(self, dev_id, json_str, qos, flag):
        return self.send_message_to_printer(dev_id, json_str, qos, flag)

    def send_message_to_printer(self, dev_id, json_str, qos, flag):
        command = bambu.parse_command(json_str)
        kind = command["kind"]
        if kind == "invalid":
            return ERR_INVALID_RESULT
        if kind == "unsupported":
            return bambu.UNSUPPORTED
        view = service().view_for(self.host) if self.host else None
        if kind == "get_version":
            self._message(bambu.version_reply((view or {}).get("firmware"), (view or {}).get("model") or MODEL))
            return OK
        if kind == "get_access_code":
            self._message(bambu.access_code_reply(self.access_code))
            return OK
        if kind == "pushall":
            self._dirty.set()
            return OK
        if kind == "noop":
            if command.get("gcode"):
                self._message(bambu.gcode_reply(command, "G90 \n", True))
            return OK
        if not view or not view["connected"]:
            return ERR_CONNECT
        flag_for = {"pause": "pause", "resume": "resume", "stop": "stop", "home": "move", "move": "move",
                    "set_temp": "heat", "slot_feed": "feed", "slot_retract": "feed", "slot_set": "feed"}
        if kind in flag_for and not can_flags(view)[flag_for[kind]]:
            log("Device tab %s refused: the printer is %s" % (kind, view["state"]))
            return ERR_INVALID_HANDLE
        if kind == "slot_retract" and "tray" not in command and status_data(view)[0]["loaded_slot"] < 0:
            log("Device tab unload refused: %s" % NOTHING_LOADED)
            return ERR_INVALID_HANDLE
        threading.Thread(target=self._run_command, args=(self.host, command, json_str), name="kobracontrol-device",
                         daemon=True).start()
        return OK

    def _run_command(self, host, command, json_str):
        kind, args = command["kind"], {k: v for k, v in command.items() if k not in ("kind", "seq", "gcode")}
        svc, ok = service(), False
        try:
            if "tray" in args:
                data, _ = status_data(svc.view_for(host))
                slot = ace.slot_for_tray(args.pop("tray"), data["slots"])
                if slot is None:
                    raise ValueError("no such tray")
                args["slot"] = slot["global_index"]
            svc.call(host, kind, **args)
            ok = True
        except Exception as e:
            log("Device tab %s failed: %s" % (kind, e))
        if command.get("gcode"):
            param = _parse_json(json_str, {}).get("print", {}).get("param", "")
            self._message(bambu.gcode_reply(command, param, ok))
        self._dirty.set()

    # jobs (job threads: blocking is fine) ------------------------------------------------------------------
    def _job_host(self, params):
        return self.host or host_of(getattr(params, "dev_ip", ""))

    @staticmethod
    def _progress(update_fn):
        last = [-1]

        def progress(sent, total):
            pct = int(sent * 100 / total) if total else 100
            if update_fn and pct != last[0]:
                last[0] = pct
                update_fn(STAGE_UPLOAD, pct, tr("Uploading G-code..."))
        return progress

    @staticmethod
    def _fail(update_fn, code, error):
        log("job failed (%d): %s" % (code, error))
        if update_fn:
            update_fn(STAGE_ERROR, code, str(error))
        return code

    def start_send_gcode_to_sdcard(self, params, update_fn, cancel_fn, wait_fn):
        sync_language()
        host = self._job_host(params)
        if getattr(params, "project_name", "") == "verify_job":   # PrintJob.cpp: a connectivity check only
            try:
                service().ready(host)
                return OK
            except Exception as e:
                log("verify: %s" % e)
                return ERR_CONNECT
        if update_fn:
            update_fn(STAGE_CREATE, 0, tr("Preparing..."))
        # A .3mf member is deflated: reaching its tail decompresses all of it once (about 0.1 s for 72 MB on a laptop).
        warnings = service().check_gcode(params.filename, getattr(params, "plate_index", 1))
        if cancel_fn and cancel_fn():
            return ERR_CANCELED
        warn(warnings)
        try:
            service().send_file(host, params.filename, clean(params.project_name) or clean(params.task_name),
                                getattr(params, "plate_index", 1), self._progress(update_fn), cancel_fn)
        except kobra.Cancelled:
            return ERR_CANCELED
        except Exception as e:
            return self._fail(update_fn, ERR_SG_UPLOAD, e)
        if update_fn:
            update_fn(STAGE_FINISHED, 100, finished_line(tr("File uploaded"), warnings))
        return OK

    def start_local_print(self, params, update_fn, cancel_fn):
        sync_language()
        if update_fn:
            update_fn(STAGE_CREATE, 0, tr("Preparing..."))
        if cancel_fn and cancel_fn():
            return ERR_CANCELED
        host = self._job_host(params)
        path = params.dst_file if getattr(params, "dst_file", "") and os.path.exists(params.dst_file) else params.filename
        trays, filaments = job_filaments(params)
        name = clean(params.project_name) or clean(params.task_name)
        task = job_task(params, get_store().effective())
        if get_store().effective()["print_dialog"]:
            try:
                if update_fn:
                    update_fn(STAGE_CREATE, 0, tr("Choose the slots and options in the Kobra Control window..."))
                choice = ask_print(params, host, path, trays, filaments, task, cancel_fn)
            except printsetup.Cancelled:
                return ERR_CANCELED
            except Exception as e:
                return self._fail(update_fn, ERR_LP_PUBLISH, e)
            trays, filaments, task, name = choice["trays"], choice["filaments"], choice["task"], choice["name"]
        else:
            choice = None   # OrcaSlicer's choice as is: print_job still refuses another material and a busy printer
        warnings = service().check_gcode(path, getattr(params, "plate_index", 1))   # see start_send_gcode_to_sdcard
        if cancel_fn and cancel_fn():
            return ERR_CANCELED
        warn(warnings)
        stage = ["prepare"]

        def on_stage(name):
            stage[0] = name
            if update_fn:
                update_fn(STAGE_UPLOAD if name == "upload" else STAGE_SENDING, 0,
                          tr("Uploading G-code...") if name == "upload" else tr("Starting print..."))
        try:
            service().print_job(host, path, getattr(params, "plate_index", 1),
                                name, trays, filaments, task,
                                self._progress(update_fn), cancel_fn, on_stage,
                                auto_feed=choice["auto_feed"] if choice else None,
                                notice=lambda text: update_fn and update_fn(STAGE_SENDING, 0, text))
        except kobra.Cancelled:
            return ERR_CANCELED
        except Exception as e:
            code = {"upload": ERR_LP_UPLOAD, "start": ERR_LP_PUBLISH}.get(stage[0], ERR_LP_PUBLISH)
            return self._fail(update_fn, code, e)
        if choice:
            try:
                choice["remember"]()
            except Exception as e:   # the print runs; only the remembered options are lost
                log("print setup: options not remembered (%s)" % e)
        if update_fn:
            update_fn(STAGE_FINISHED, 100, finished_line(tr("Print started"), warnings))
        return OK

    def start_local_print_with_record(self, params, update_fn, cancel_fn, wait_fn):
        return self.start_local_print(params, update_fn, cancel_fn)

    def start_print(self, params, update_fn, cancel_fn, wait_fn):
        return bambu.UNSUPPORTED   # cloud printing: the Kobra X is driven over the LAN only

    def start_sdcard_print(self, params, update_fn, cancel_fn):
        sync_language()
        name = os.path.basename(clean(getattr(params, "dst_file", "")) or clean(params.filename))
        try:
            service().call(self._job_host(params), "file_print", name=name, **job_task(params, get_store().effective()))
        except Exception as e:
            return self._fail(update_fn, ERR_LP_PUBLISH, e)
        if update_fn:
            update_fn(STAGE_FINISHED, 100, tr("Print started"))
        return OK

    # no binding or certificates on this printer -------------------------------------------------------------
    def check_cert(self): return OK
    def install_device_cert(self, dev_id, lan_only): return None
    def ping_bind(self, ping_code): return OK
    def bind(self, dev_ip, dev_id, dev_model, sec_link, timezone, improved, update_fn): return OK
    def unbind(self, dev_id): return OK
    def request_bind_ticket(self): return (OK, "")

    # filaments and camera ------------------------------------------------------------------------------------
    def get_filament_sync_mode(self):
        return pa.FilamentSyncMode.Subscription

    def fetch_filament_info(self, dev_id, sync_mode=None):
        self._dirty.set()
        return True

    def _camera_url(self):
        view = service().view_for(self.host) if self.host else None
        return camera_url_for(view, self.host, log, self._camera_refused)   # only a stream on the printer itself

    def get_camera_stream_mode(self):
        """By the URL's scheme: the Kobra X (firmware 2.0.2.8) reports http://<ip>:18088/live/<token>. OrcaSlicer
        plays http, https and rtsp alike through its ffmpeg backend (MediaPlayCtrl.cpp:402, wxMediaCtrl3.cpp:358-383)."""
        scheme = self._camera_url().split("://", 1)[0].lower()
        return {"http": pa.CameraStreamMode.HTTP, "https": pa.CameraStreamMode.HTTPS,
                "rtsp": pa.CameraStreamMode.RTSP}.get(scheme, pa.CameraStreamMode.None_)

    def get_camera_url(self):
        return self._camera_url()   # a getter never sends anything; the stream starts in command_start_camera

    def command_start_camera(self, dev_id):
        """video/startCapture (Kobralink starts the stream before reading it), once per stream URL."""
        conn = service().connections.get(self.host) if self.host else None
        printer = conn.printer if conn else None   # read once: the loop may replace the session meanwhile
        if printer is None or not conn.connected:
            return ERR_CONNECT
        key = (self.host, conn.view()["camera_url_rev"], id(printer))
        if key != self._camera_key:
            self._camera_key = key
            threading.Thread(target=printer.start_camera, name="kobracontrol-capture", daemon=True).start()
        return OK


# ====================================================================== scripts

class CheckConnection(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Check Kobra X connection"

    def execute(self):
        # Scripts run on a worker thread of their own (OrcaSlicer docs/HLSD/python-plugin-async-bridge.md, "Per-
        # invocation worker and loop"), never on the UI thread; still, the whole check is bounded to 20 s.
        sync_language()
        try:
            svc = service()
            if svc.target is None:
                svc.set_target(_target(preset_hints_from_worker(svc)))
            deadline = time.monotonic() + CHECK_SECONDS
            host = svc.wait_located(CHECK_SECONDS).host
            conn = svc.ready(host, timeout=max(1.0, deadline - time.monotonic()))
        except locate.NotFound as e:
            text = tr("Couldn't reach the Kobra X: %s") % e
            if e.pending or e.candidates:   # only the tab can ask OrcaSlicer about them or let the user choose
                text += " " + tr("Open the Kobra Control tab to allow or choose the printer.")
            return orca.ExecutionResult.skipped(text)
        except Exception as e:
            return orca.ExecutionResult.skipped(" ".join([tr("Couldn't reach the Kobra X: %s") % e] + preset_gcode_warnings()))
        view = conn.view()
        data, _ = status_data(view)
        loaded = ", ".join("S%d %s" % (s["global_index"] + 1, s["type"] or "?") for s in data["slots"] if s["status"] == 5)
        return orca.ExecutionResult.success(" ".join([tr("%s at %s (firmware %s), %s. %s") % (
            view["printer_name"] or MODEL, host, view["firmware"] or "?", tr(view["state"]), loaded or tr("No filament loaded."))]
            + preset_gcode_warnings()))


class FindCertificate(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return "Find Anycubic certificate"

    def execute(self):
        sync_language()
        folder = cert_dir()
        if not folder:
            return orca.ExecutionResult.skipped(tr("No storage folder to keep the certificate in."))
        try:
            found = find_and_save_certificate(folder)
        except (certs.CertError, OSError) as e:
            return orca.ExecutionResult.skipped(tr("No Anycubic Slicer certificate: %s") % e)
        if _service is not None:
            for conn in list(_service.connections.values()):
                conn.retry()
        return orca.ExecutionResult.success(tr("Anycubic Slicer certificate saved (found in %s).") % found.source)


@orca.plugin
class KobraControl(orca.base):
    def register_capabilities(self):
        _storage()
        hosts = known_hosts()
        _granted.update(hosts)
        try:   # the upload bridge listens on 127.0.0.1: asked for at load only when it is on
            local = ["http://" + bridge.HOST] if get_store().effective()["bridge_enabled"] else []
        except Exception:
            local = []
        # Network I/O runs on the plugin's own threads. fs_read: OrcaSlicer's per-user temp folder, where Print and
        # Send hand over the sliced .3mf (the certificate is read from the plugin's own package, which needs no
        # grant; Anycubic Slicer Next's folders are read only when the user asks, and asked for then). network:
        # every printer address known now and the SSDP multicast group the network search sends to (a canonical
        # http://host grant also covers raw sockets to that host); a printer found later is asked for on first
        # contact.
        network = ["http://%s" % h for h in hosts] + ["http://" + locate.SSDP_GROUP] + local
        orca.request_permissions(threading=True, fs_read=job_read_grants(), network=list(dict.fromkeys(network)))
        orca.register_capability(KobraAgent)
        orca.register_capability(KobraControlPage)
        orca.register_capability(CheckConnection)
        orca.register_capability(FindCertificate)

