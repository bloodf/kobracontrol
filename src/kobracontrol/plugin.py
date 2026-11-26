"""OrcaSlicer glue: the Anycubic Kobra X printer agent, the Kobra Control tab and two scripts. The only module
that imports `orca`. Printer work runs in service.py on the plugin's own threads; everything here that runs
on OrcaSlicer's UI thread only queues work and returns."""

import json
import os
import pkgutil
import re
import socket
import sys
import tempfile
import threading
import time

import orca

import ace
import bambu
import bridge
import certs
import cloud
import gcode_check
import i18n
import locate
import kobra
import peers
import printsetup
import profiles


import requirements
import settings
import spooler_bridge
from i18n import tr
from service import (LIMITS, NOTHING_LOADED, Service, Target, camera_url_for, can_flags,
                     find_and_save_certificate, status_data)

VERSION = "0.0.0-dev"
AGENT_ID = "kobracontrol"
AGENT_NAME = "Anycubic (kobracontrol)"   # the id stays "kobracontrol": existing printer presets keep working
MODEL = "Anycubic Kobra X"                # the model shown before a printer answers (the first supported one)
TLS_DIR = "tls"          # never "cert(s)": the plugin sandbox refuses such path components
LEDGER_FILE = "usage_ledger.json"
SPOOLS_FILE = "spools.json"   # the last Spoolman list, shown at once while the live one is read
ADDRESSES_FILE = "addresses.json"   # printer preset -> the Kobra X found for it (locate.Addresses)
CHECK_SECONDS = 20.0                # Check Kobra X connection: locating and connecting together
_granted = set()   # printer addresses declared at load or allowed since: the search probes only these by itself
_refused = set()   # addresses refused in OrcaSlicer's dialog this session: asked again only on a user action
_queue_on_main = None   # OrcaSlicer's queue_on_main, once it hands it to the printer agent
_last_hints = ("", "", "")   # preset_hints() as last read on the UI thread, for the script's worker thread
_last_setup = {}             # preset_setup() as last read on the UI thread, for the page's config message
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
_match_file_ids = {}      # (preset file, mtime, size) -> filament_id, for the slot cards' preset match
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


def is_kobra(*values):
    """A printer preset for an Anycubic model Kobra Control reaches over the LAN (profiles.py)."""
    return profiles.is_anycubic_lan(*(clean(v) for v in values if v))


def model_of(view):
    """The printer's model name for OrcaSlicer: its profile's, else what it reports, else MODEL."""
    profile = profiles.get((view or {}).get("mode_id"))
    return profile["name"] if profile else (view or {}).get("model") or MODEL


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


if __package__:   # the built wheel
    # Imported with the package, not on first use: OrcaSlicer imports the package outside the plugin's audit scope,
    # but a module first imported later (from get_icon) writes its bytecode cache inside it, and that write is an
    # audited "open" on a descriptor, with no path, shown to the user as a permission prompt without a target.
    from . import _assets  # noqa: E402


def _asset(name):
    """Packaged: the icon from _assets, the page from app.html next to the modules (pkgutil reads it from a folder
    or a zip alike). During development: from src/kobracontrol/ui."""
    if __package__:
        if name == "icon.png":
            return _assets.ICON_PNG
        data = pkgutil.get_data(__package__, name)
        if data is None:
            raise FileNotFoundError("%s is missing from the kobracontrol package" % name)
        return data.decode("utf-8")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", name)
    if name.endswith(".png"):
        with open(path, "rb") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
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


WEBVIEW_PAGE_LIMIT = 1_572_864   # bytes of UTF-8 HTML: WebView2 (Windows) takes at most 2 MiB of base64 and draws a bigger page blank


def page_html(language="auto", mode="app", data=None):
    """The Kobra Control tab ("app"), or the print dialog ("print", with its data). A print dialog page that would be
    too big for WebView2 leaves out the plate image."""
    boot = {"version": VERSION, "lang": _host_language(),
            "pref": language if language in settings.UI_LANGUAGES else "auto", "mode": mode, "data": data}
    html = _asset("app.html").replace("__BOOT__", json_for_html(boot), 1)
    size = len(html.encode("utf-8"))
    if mode == "print" and size > WEBVIEW_PAGE_LIMIT and data.get("job", {}).get("thumbnail"):
        log("print setup page is %d bytes, over WebView2's %d; the plate image is left out" % (size, WEBVIEW_PAGE_LIMIT))
        return page_html(language, mode, {**data, "job": {**data["job"], "thumbnail": ""}})
    return html


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
                               spools_path=os.path.join(folder, SPOOLS_FILE) if folder else None,
                               addresses_path=os.path.join(folder, ADDRESSES_FILE) if folder else None, granted=_granted,
                               **_service_options)
        elif publish is not None:
            _service.publish = publish
        _service.peers = _link
        if _link is not None:
            _link.presence.printers = _service.shared_printers
        if _service.cloud is None:
            sync_cloud(_service)
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
            _link.presence.printers = _service.shared_printers
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


def _own_ofd_presets():
    """UI thread, no I/O: the presets of Kobra Control's own OFD bundle compatible with the selected printer, as
    {"name", "file"} (their filament_id is read from the file later); [] when they can't be read."""
    try:
        collection = orca.host.preset_bundle().filaments
        return [{"name": p.name, "file": p.file or ""} for p in (collection.preset(i) for i in range(collection.size()))
                if (getattr(p, "bundle_id", "") or "") == spooler_bridge.OFD_BUNDLE and getattr(p, "is_compatible", COMPATIBLE_DEFAULT)]
    except Exception as e:
        log("own OFD presets not readable (%r)" % e)
        return []


def ofd_parent_config(name):
    """UI thread, no I/O: the settings of the system preset an OFD preset inherits ({key: text}); None when there is none."""
    try:
        preset = orca.host.preset_bundle().filaments.find_preset(name) if isinstance(name, str) and name else None
        if preset is None or not getattr(preset, "is_system", False):
            return None
        return {str(k): str(preset.config_value(k)) for k in preset.config_keys() if preset.config_value(k) is not None}
    except Exception as e:
        log("OFD parent %r not readable (%r)" % (name, e))
        return None


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
    if agent != AGENT_ID and not is_kobra(preset.config_value("printer_model"), preset.name,
                                            preset.config_value("inherits")):
        return "", preset.name, agent
    host = host_of(preset.config_value("print_host")) or host_of(bundle.full_config_value("print_host"))
    return host, preset.name, agent


def preset_setup():
    """How the selected printer preset reaches the printer, for the page's setup hints: {"kobra": a Kobra X preset,
    "agent": its printer agent, "host_type": its print host type (OctoPrint, PrusaLink...), "host": its print host's
    address}. A Kobra X has no OctoPrint server: Print and Send work through the kobracontrol printer agent only."""
    bundle = orca.host.preset_bundle()
    preset = bundle.current_printer_preset()

    def value(key):
        return clean(preset.config_value(key)) or clean(bundle.full_config_value(key))
    return {"kobra": value("printer_agent") == AGENT_ID or is_kobra(preset.config_value("printer_model"), preset.name,
                                                                         preset.config_value("inherits")),
            "agent": value("printer_agent"), "host_type": value("host_type"), "host": host_of(value("print_host"))}


def dev_id_from_address(host, port):
    """OrcaSlicer's MachineObject::dev_id_from_address: the preset's print host without scheme and path, with
    printhost_port in place of its own port when one is set. select_machine() looks the printer up by this id."""
    text = clean(host)
    for scheme in ("http://", "https://"):
        if text.startswith(scheme):
            text = text[len(scheme):]
    text = text.split("/", 1)[0]
    port = clean(port)
    return "%s:%s" % (text.split(":", 1)[0], port) if port else text


def agent_address(connected=("", "")):
    """UI thread: (dev_id, host) of the printer the agent stands for: the selected preset's print host (under the
    dev_id select_machine() looks for), else `connected` (the agent's printer), else the printer the tab found;
    ("", "") with none. The preset comes first: after a switch to another preset its printer is the one to announce."""
    try:
        bundle = orca.host.preset_bundle()
        preset = bundle.current_printer_preset()
        value = lambda key: clean(preset.config_value(key)) or clean(bundle.full_config_value(key))   # noqa: E731
        print_host, port = value("print_host"), value("printhost_port")
    except Exception as e:   # no preset bundle yet
        log("printer preset not readable (%s)" % e)
        print_host = port = ""
    if print_host and host_of(print_host):
        return dev_id_from_address(print_host, port), host_of(print_host)
    if connected[1]:
        return connected
    target = _service.target if _service is not None else None
    host = target.host if target is not None else ""
    return host, host


def ui_preset_hints():
    """UI thread only: preset_hints(), kept for worker threads; ("", "", "") when no preset can be read yet.
    preset_setup() is kept with them, for the page's config message."""
    global _last_hints, _last_setup
    try:
        _last_hints = preset_hints()
        _last_setup = preset_setup()
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
        if agent != AGENT_ID and not is_kobra(preset.config_value("printer_model"), preset.name,
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


def cloud_host():
    """"cloud:<id>" when Settings turn Anycubic Cloud on and choose a cloud printer, else "": the tab and the printer
    agent then drive that printer through the cloud, whatever the printer preset's address."""
    cfg = get_store().effective()
    return cloud.HOST_PREFIX + cfg["cloud_printer"] if cfg["cloud_enabled"] and cfg["cloud_printer"] else ""


def cloud_hosts():
    return (cloud.API_HOST, cloud.MQTT_HOST) + cloud.UPLOAD_HOSTS


def sync_cloud(svc, ask=False):
    """Give the service the Anycubic account while Settings have the cloud on, take it away when off. ask (UI thread,
    the user just turned it on): let OrcaSlicer ask about the cloud hosts now, with an audited name lookup, as for a
    printer address; at load they are in the permission request instead."""
    cfg, folder = get_store().effective(), _storage()
    if not (cfg["cloud_enabled"] and folder):
        svc.cloud = None
        return
    if svc.cloud is None:
        svc.cloud = cloud.Account(os.path.join(folder, cloud.TOKEN_FILE), log)
        for host in cloud_hosts() if ask else ():
            try:
                socket.getaddrinfo(host, 443)
            except OSError as e:   # PermissionError: refused; the first request says so again
                log("network access to %s: %s" % (host, e))


def _target(hints=None):
    """The tab's target. hints: preset_hints() already read on the UI thread; None reads them here (UI thread)."""
    cfg = get_store().effective()
    preset_host, preset_name, agent = ui_preset_hints() if hints is None else hints
    return Target(cloud_host() or host_of(cfg.get("host")), settings.printer_label(cfg.get("printer_name")),
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


def permission_origin(url):
    """scheme://host of a Spoolman address, the form OrcaSlicer's load-time network grant covers every port and path
    of (a runtime approval covers only the exact URL it saw); "" for none."""
    origin = peers.normalize_origin(url)
    if not origin:
        return ""
    scheme, _, rest = origin.partition("://")
    host = rest.split("/", 1)[0]
    return "%s://%s" % (scheme, host[:host.index("]") + 1] if host.startswith("[") else host.split(":", 1)[0])


def remember_spoolman(url):
    """Keep the Spoolman origin in use (Settings, or Spooler's), so the next load asks OrcaSlicer for it once: Kobra
    Control's Spoolman reads run on worker threads, where an address not granted is only refused."""
    origin = permission_origin(url)
    try:
        known = get_store().effective()["spoolman_origins"]
        if origin and origin not in known:
            get_store().update({"spoolman_origins": known + [origin]})
    except Exception as e:   # never fails the page's config
        log("Spoolman address not remembered (%s)" % e)


def spoolman_grants():
    """The Spoolman origins for the load-time network request: Settings' and the ones used before."""
    try:
        cfg = get_store().effective()
        found = [permission_origin(cfg.get("spoolman_url"))] + cfg["spoolman_origins"]
    except Exception as e:
        log("settings not readable at load (%s)" % e)
        return []
    return [o for o in dict.fromkeys(found) if o]


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


def allow_now(svc, what):
    """UI thread only: Check everything's Allow button. Raises the audited event OrcaSlicer judges, without any
    network I/O, so its permission dialog shows inline and a Yes is saved: for the printer getaddrinfo of its numeric
    LAN address (as grant_on_ui_thread, but asked even when declared at load: that grant may have been refused); for
    Spoolman a urllib.Request event for its bare scheme://host, which OrcaSlicer saves host-wide (every port and path),
    like the load-time grant. True when allowed; False when refused or there is nothing to allow."""
    target = svc.target
    if what == "printer":
        host = target.host if target is not None else ""
        if not locate.lan_address(host):
            return False
        try:
            svc._ask_orcaslicer(host)
        except PermissionError:
            _refused.add(host)
            log("network access to %s not allowed" % host)
            return False
        except OSError:
            pass
        _refused.discard(host)
        _granted.add(host)
        conn = svc.connections.get(host)
        if conn is not None:
            conn.retry()   # the next attempt uses the new grant now, not after the backoff
        return True
    if what == "spoolman":
        url = target.spoolman_url if target is not None else ""
        origin = permission_origin(url)
        if not origin:
            return False
        remember_spoolman(url)   # asked for at load from now on too
        try:
            sys.audit("urllib.Request", origin, None, {}, "GET")
        except PermissionError:
            log("network access to %s not allowed" % origin)
            return False
        return True
    return False


# ====================================================================== Kobra Control tab

class KobraControlPage(orca.pages.PagesPluginCapabilityBase):
    def get_name(self):
        return "Kobra Control"

    def get_icon(self):
        """The icon file in the plugin storage folder (data_dir(), writable for the plugin); none without it."""
        png = _asset("icon.png")
        # A different base name from the old kobracontrol.svg: OrcaSlicer strips the extension and tries <name>.svg
        # before <name>.png, so a leftover SVG of the same name would win.
        for folder in [f for f in [_storage()] if f]:
            path = os.path.join(folder, "kobracontrol-icon.png")
            try:
                try:
                    with open(path, "rb") as f:
                        same = f.read() == png
                except OSError:
                    same = False
                if not same:
                    with open(path, "wb") as f:
                        f.write(png)
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
            elif kind == "allow_now":   # UI thread: Check everything's Allow (printer or Spoolman)
                self.post_message({"type": "reply", "id": data.get("id"), "result": {"allowed": allow_now(svc, data.get("what"))}})
            elif kind == "bridge_new_key":   # the old key stops working at once
                bridge_key(renew=True)
                self.post_message(self._config_message())
                self.post_message({"type": "reply", "id": data.get("id"), "result": {"renewed": True}})
            elif kind == "ui_language":
                get_store(self).update({"ui_language": data.get("value")})
                sync_language()
            elif kind == "dashboard":   # the Dashboard's layouts, saved by the page; an invalid value keeps the stored one
                get_store(self).update({"dashboard": data.get("value")})
            elif kind == "ofd":   # Settings: the Open Filament Database line; refresh: Read again (only while it is on)
                threading.Thread(target=self._ofd_state, args=(data,), name="kobracontrol-ofd", daemon=True).start()
            elif kind in ("preset_matches", "preset_pick"):   # slot cards: the preset each slot is reported as, and Change
                presets, label = filament_catalog()
                users = _user_presets_safe()
                own = _own_ofd_presets()
                # An OFD pick names its parent: its settings are read here, on the UI thread (the worker checks the name).
                parent = ofd_parent_config(data.get("inherits")) if kind == "preset_pick" and isinstance(data.get("ofd"), str) else None
                threading.Thread(target=self._slot_matches, args=(svc, kind, data, presets, label, users, own, parent),
                                 name="kobracontrol-matches", daemon=True).start()
            elif kind == "spoolman_refresh":   # Settings: how often the page re-reads Spoolman; invalid keeps the stored one
                get_store(self).update({"spoolman_refresh_s": data.get("value")})
                self._post_config()
            elif kind == "save_settings":
                changes = dict(data.get("settings") or {})
                bad = settings.invalid(changes)
                if bad:
                    raise ValueError(tr("not a valid setting: %s; nothing was saved") % ", ".join(bad))
                get_store(self).update(changes)
                sync_bridge(lambda: self.post_message(self._config_message()))
                sync_cloud(svc, ask=bool(changes.get("cloud_enabled")))
                target = _target()
                grant_on_ui_thread(svc, target.preset_host, user=True)
                svc.set_target(target, retry=True)   # a new address connects at once; the same one now
                result = {"saved": True}
                self._requirements(svc, self._post_config(), force=True)   # a Settings save checks again too
                self.post_message({"type": "reply", "id": data.get("id"), "result": result})
        except Exception as e:
            self.post_message({"type": "reply", "id": data.get("id"), "error": str(e)})

    def _install_ofd(self, storage, slots, spools, data, parent, label, users, ctx, paths, write):
        """A slot card's Change to an OFD proposal (worker thread): installed by Spooler or into Kobra Control's own
        bundle, then remembered for the slot. Returns a note for the page ("" when it is in use now)."""
        slot = next((sl for sl in slots if sl["global_index"] == data.get("slot")), None)
        if slot is None or not get_store(self).effective().get("ofd_enabled"):
            raise ValueError(tr("That preset can't be used for this slot."))
        spool = spools.get(slot.get("spool_id"))
        folder = spooler_bridge.ofd_folder(storage)
        entry = next((p for p in spooler_bridge.filmatch.ofd_index(folder, offline=True)["profiles"] if p["id"] == data["ofd"]), None)
        if entry is None or entry["inherits"] != data.get("inherits"):
            raise ValueError(tr("That preset can't be used for this slot."))
        try:
            how, what = spooler_bridge.install_ofd(storage, slot, spool, data["ofd"], parent, label,
                                                   orca.host.preset.bundles.reload_local, VERSION, [u["file"] for u in users])
        except ValueError as e:
            raise ValueError(tr("The Open Filament Database preset can't be used: %s") % e) from None
        if how == "spooler":
            return tr("Spooler puts it into its preset of spool #%s on its next sync") % what
        keys = spooler_bridge.slot_match(ctx, slot, spool)["keys"]
        if keys and write:
            spooler_bridge.filmatch.remember(write, {keys[0]: "%s%s/%s" % ("_local/", spooler_bridge.OFD_BUNDLE, what)}, label)
        return tr("Installed; the Device tab reports it once OrcaSlicer lists it")

    def _ofd_state(self, data):
        """Worker thread: Settings' OFD line, {"on"} and, while on, {"fetched", "version", "count", "stale", "error"}."""
        try:
            folder = spooler_bridge.ofd_folder(_storage()) if get_store(self).effective().get("ofd_enabled") else ""
            if folder:
                found = spooler_bridge.filmatch.ofd_index(folder, force=data.get("refresh") is True)
                result = {"on": True, "count": len(found["profiles"]), **{k: found[k] for k in ("fetched", "version", "stale", "error")}}
            else:
                result = {"on": False}
            self.post_message({"type": "reply", "id": data.get("id"), "result": result})
        except Exception as e:
            self.post_message({"type": "reply", "id": data.get("id"), "error": str(e)})

    def _slot_matches(self, svc, kind, data, presets, label, users, own=(), parent=None):
        """Worker thread (reads files): answer the page with every ready slot's preset match, after a Change."""
        try:
            storage = _storage()
            profiles = spooler_bridge.read_json(spooler_bridge.data_dir(storage), spooler_bridge.PROFILES_FILE) or {}
            paths, write = spooler_bridge.match_paths(storage)
            ctx = spooler_bridge.match_context(presets, label, users, profiles, spooler_bridge.load_stores(paths), _match_file_ids, log, own)
            note = ""
            with svc.lock:
                host = svc.target.host if svc.target else ""
                spools, bindings = {sp["id"]: sp for sp in svc.spools}, dict(svc.bindings)
            view = svc.view_for(host) if host else None
            slots = [sl for sl in (status_data(view, bindings=bindings)[0]["slots"] if view else []) if sl.get("status") == 5]
            if kind == "preset_pick" and isinstance(data.get("ofd"), str):
                note = self._install_ofd(storage, slots, spools, data, parent, label, users, ctx, paths, write)
            elif kind == "preset_pick":
                slot = next((sl for sl in slots if sl["global_index"] == data.get("slot")), None)
                name = data.get("name")
                try:
                    if slot is None:
                        raise ValueError(name)
                    spooler_bridge.remember_slot(ctx, slot, spools.get(slot.get("spool_id")), name if name is None else str(name), paths, write)
                except ValueError:
                    raise ValueError(tr("That preset can't be used for this slot.")) from None
                ctx["stores"] = spooler_bridge.load_stores(paths)
            ofd_dir = spooler_bridge.ofd_folder(storage) if get_store(self).effective().get("ofd_enabled") else ""
            profiles = spooler_bridge.filmatch.ofd_index(ofd_dir)["profiles"] if ofd_dir else []   # a day old: read again
            matches = [{**{k: v for k, v in spooler_bridge.slot_match(ctx, sl, spools.get(sl.get("spool_id"))).items() if k not in ("keys", "id")},
                        "ofd": spooler_bridge.slot_ofd(profiles, sl, spools.get(sl.get("spool_id"))) if profiles else []}
                       for sl in slots]
            self.post_message({"type": "reply", "id": data.get("id"), "result": {"matches": matches, "note": note}})
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
        if target is not None and target.spoolman_url:
            remember_spoolman(target.spoolman_url)
        located = {"address": target.host, "source": target.source, "preset_host": target.preset_host,
                   "preset_agent": target.preset_agent, "spoolman_url": target.spoolman_url,
                   "spoolman_source": target.spoolman_source} if target else None
        return {"type": "config", "settings": cfg, "certificate": certificate_state(), "spooler": spooler, "setup": dict(_last_setup),
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
                                 "model": model_of(data)}, job, fils, data, names,
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
        self._catalog = ([], "")             # (Spooler presets, printer label) for tray ids; the UI thread owns it
        self._profiles = {}                  # Spooler's profiles.json; the push thread owns it
        self._ofd_presets = []               # Kobra Control's own OFD presets ({"name", "file"}), for tray ids
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
        return pa.AgentInfo(AGENT_ID, AGENT_NAME, VERSION, tr("Anycubic Kobra X, Kobra 3 and Kobra S1 printers over the LAN (MQTT), by kobracontrol"))

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
        """UI thread. Announces the printer before any connect_printer, as MoonrakerPrinterAgent does, and at once (not
        queued): OrcaSlicer 2.5's select_machine(), which runs right after this, looks the preset's print host up only
        among this agent's machines. An entry saved for that address under another agent (an OctoPrint physical
        printer, a Moonraker preset) stays hidden from it, and a preset with no print host has no entry at all: the
        Device tab shows no printer and Print can't find one. Discovery with that dev_id gives the entry to this agent
        or creates it (DeviceManager::on_machine_alive)."""
        if start:
            dev_id, host = agent_address((self.dev_id, self.host))
            if host:
                self._announce(dev_id, host)
        return True

    def _announce(self, dev_id, host):
        """MoonrakerPrinterAgent announce_printhost_device: the configured printer, never a network scan."""
        view = (_service.view_for(host) if _service is not None else None) or {}
        with self._lock:
            fn = self._cb.get("ssdp")
        if fn is not None:
            call_safely("ssdp", fn, json.dumps({
                "dev_name": view.get("printer_name") or model_of(view), "dev_id": dev_id or host, "dev_ip": host, "dev_type": model_of(view),
                "dev_signal": "0", "connect_type": "lan", "bind_state": "free", "sec_link": "secure", "ssdp_version": "v1"}))

    def get_user_selected_machine(self):
        return self.selected

    def set_user_selected_machine(self, dev_id):
        self.selected = dev_id or ""
        return OK

    def bind_detect(self, dev_ip, sec_link, detect):
        view = service().view_for(host_of(dev_ip)) or {}
        detect.dev_id = self.dev_id if self.host and self.host == host_of(dev_ip) else dev_ip
        detect.dev_name = view.get("printer_name") or model_of(view)
        detect.model_id = model_of(view)
        detect.version = view.get("firmware") or ""
        detect.connect_type = "lan"
        detect.bind_state = "free"
        return OK

    # connection -----------------------------------------------------------------------------------------
    def connect_printer(self, params):
        """UI thread: remember the printer, attach to its shared connection (whose own thread does the I/O)."""
        host = cloud_host() or host_of(getattr(params, "host", ""))
        if not host or not getattr(params, "dev_id", ""):
            return ERR_INVALID_HANDLE
        sync_language()
        grant_on_ui_thread(service(), host, user=True)
        previous = self._detach()
        self.dev_id, self.host, self.access_code = params.dev_id, host, getattr(params, "password", "") or ""
        self._catalog_at = 0.0   # the first push re-reads Spooler's profiles.json
        self._links = ([], {})   # another printer's links never reach this one's trays
        _storage()               # plugin.storage() answers only inside a callback: cache it for the push thread
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

    def _refresh_catalog(self):
        """UI thread, no I/O: re-read Spooler's presets (it adds its own at any time), then the slots' links from
        Spoolman on a thread of their own, so sync from AMS knows them without the tab ever opening."""
        try:
            presets, label = filament_catalog()
            users = _user_presets_safe()
            target = _target()
        except Exception as e:
            log("filament presets not readable (%s); trays show generic presets" % e)
            return
        self._catalog = (presets, label)
        self._ofd_presets = _own_ofd_presets()
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
            # profiles.json is plain file I/O owned by this thread: it never waits for the UI queue. _storage() is
            # cached by connect_printer (plugin.storage() answers only inside a callback).
            self._profiles = spooler_bridge.read_json(spooler_bridge.data_dir(_storage()), spooler_bridge.PROFILES_FILE) or {}
            with self._lock:
                queue = self._cb.get("queue_on_main")
            if queue is not None:
                queue(lambda: call_safely("filament catalog", self._refresh_catalog))
        bound = self._bound_spools()
        presets, label = self._catalog
        profiles = self._profiles
        # A preset picked by hand on a slot card (matches.json) comes after the spool's own link, before Spooler's.
        stores = spooler_bridge.load_stores(spooler_bridge.match_paths(_storage())[0])
        ctx = spooler_bridge.match_context(presets, label, self._user_presets, profiles, stores, self._file_ids, log, self._ofd_presets) \
            if any(st.get("entries") for st in stores) else None

        def preferred(slot):
            spool = bound.get(slot["global_index"])
            picked = spooler_bridge.slot_match(ctx, slot, spool) if ctx else {}
            return self._linked_id(spool) or (picked["id"] if picked.get("source") == "remembered" else "") \
                or spooler_bridge.tray_filament_id(spool, presets, profiles, label)
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
        return spooler_bridge.cached_standalone_id(preset, self._file_ids, log)   # read once per file version

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
        self._message(bambu.push_status(view, data["slots"], data["mode"], data["limits"]["nozzle_max"],
                                          data["limits"]["bed_max"], self._preferred()))

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
            self._message(bambu.version_reply((view or {}).get("firmware"), model_of(view)))
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
        """The printer the job names (PrintParams.dev_ip, as OrcaSlicer's Multi-device tab sends it), else the
        connected one: never the connected printer for a job that names another."""
        return cloud_host() or host_of(getattr(params, "dev_ip", "")) or self.host

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
        return bambu.UNSUPPORTED   # cloud printing: Kobra Control drives the printer over the LAN only

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
        return "Check printer connection"

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
            text = tr("Couldn't reach the printer: %s") % e
            if e.pending or e.candidates:   # only the tab can ask OrcaSlicer about them or let the user choose
                text += " " + tr("Open the Kobra Control tab to allow or choose the printer.")
            return orca.ExecutionResult.skipped(text)
        except Exception as e:
            return orca.ExecutionResult.skipped(" ".join([tr("Couldn't reach the printer: %s") % e] + preset_gcode_warnings()))
        view = conn.view()
        data, _ = status_data(view)
        loaded = ", ".join("S%d %s" % (s["global_index"] + 1, s["type"] or "?") for s in data["slots"] if s["status"] == 5)
        return orca.ExecutionResult.success(" ".join([tr("%s at %s (firmware %s), %s. %s") % (
            view["printer_name"] or model_of(view), host, view["firmware"] or "?", tr(view["state"]), loaded or tr("No filament loaded."))]
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
        network = ["http://%s" % h for h in hosts] + ["http://" + locate.SSDP_GROUP] + local + spoolman_grants()
        try:   # Anycubic Cloud's hosts only while it is on (opt-in)
            network += ["https://" + h for h in cloud_hosts()] if get_store().effective()["cloud_enabled"] else []
        except Exception:
            pass
        try:   # the Open Filament Database only while it is on (opt-in)
            network += [spooler_bridge.filmatch.OFD_ORIGIN] if get_store().effective()["ofd_enabled"] else []
        except Exception:
            pass
        orca.request_permissions(threading=True, fs_read=job_read_grants(), network=list(dict.fromkeys(network)))
        orca.register_capability(KobraAgent)
        orca.register_capability(KobraControlPage)
        orca.register_capability(CheckConnection)
        orca.register_capability(FindCertificate)

