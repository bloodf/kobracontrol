"""One flat, validated settings store (page, printer agent, scripts). Free of the `orca` module.
No secrets are kept here: the printer's MQTT credentials live in memory only, the upload bridge's key in its own
file (bridge.py)."""

import json
import os
import threading

import i18n
import printsetup
import spoolman

DEFAULT_PRINTER_NAME = "Anycubic Kobra X"
UI_LANGUAGES = ("auto",) + i18n.LANGUAGES   # "auto": OrcaSlicer's language, then the system's
DEFAULTS = {
    "host": "",                          # printer address override; "" = the one in the printer preset
    "printer_name": DEFAULT_PRINTER_NAME,  # also the Spoolman location prefix of the slot bindings
    "ui_language": "auto",
    "ffmpeg_path": "",                   # "" = look ffmpeg up on PATH
    "camera_enabled": False,
    "auto_leveling": True,               # print options default
    "vibration_compensation": True,      # also the default of OrcaSlicer prints: its Print dialog has no such option
    "flow_calibration": False,
    "timelapse": False,
    "spoolman_url": "",
    "spoolman_auto": True,               # bind a spool when a slot changes
    "spoolman_report_usage": True,       # deduct each slot's grams when a print finishes
    "spoolman_refresh_s": 30,            # the page re-reads Spoolman this often while it shows (0 = off; 10-300)
    "spooler_hint_dismissed": False,
    "setup_hint_dismissed": False,       # the Dashboard's "Print from OrcaSlicer" steps: "Don't show again"
    "print_dialog": True,                # "Show print setup before sending": Kobra Control's window after OrcaSlicer's Print
    "remember_print_options": True,      # its options start from the last ones chosen for that printer
    "print_memory": {},                  # printer -> {option: bool}, the last options chosen (printsetup.remember)
    "bridge_enabled": False,             # Upload-and-Print bridge (bridge.py): opt-in
    "bridge_port": 8765,
    "dashboard": {},   # the Dashboard's layouts (clean_dashboard); {} = the page's default
}
PORT_RANGE = (1024, 65535)
REFRESH_RANGE = (10, 300)


DASHBOARD_MAX_BYTES = 32_000   # the page's dashboard layouts (settings "dashboard"), serialized


def clean_dashboard(value):
    """The page's dashboard layouts as stored: {"v": 1, "active": n, "layouts": [{"name", "items": [{"id", "x", "y",
    "w", "h", "cfg"}]}]}. The shape and the size only: the page itself drops widgets it does not know and brings sizes
    within each widget's limits. None when the value is not a dashboard (the stored one is kept)."""
    if not isinstance(value, dict) or value.get("v") != 1:
        return None
    layouts = value.get("layouts")
    if not isinstance(layouts, list) or not 1 <= len(layouts) <= 12:
        return None
    out = []
    for layout in layouts:
        if not isinstance(layout, dict) or not isinstance(layout.get("name"), str) or not isinstance(layout.get("items"), list) \
                or len(layout["items"]) > 40:
            return None
        items = []
        for it in layout["items"]:
            if not isinstance(it, dict) or not isinstance(it.get("id"), str) or not 0 < len(it["id"]) <= 40 \
                    or not all(type(it.get(k)) is int and 0 <= it[k] <= 200 for k in ("x", "y", "w", "h")):
                return None
            item = {k: it[k] for k in ("id", "x", "y", "w", "h")}
            cfg = it.get("cfg")
            if cfg is not None:
                if not isinstance(cfg, dict) or not all(isinstance(k, str) and type(v) in (str, int, float, bool) for k, v in cfg.items()):
                    return None
                item["cfg"] = dict(cfg)
            items.append(item)
        out.append({"name": layout["name"][:40], "items": items})
    active = value.get("active")
    clean = {"v": 1, "active": active if type(active) is int and 0 <= active < len(out) else 0, "layouts": out}
    return clean if len(json.dumps(clean)) <= DASHBOARD_MAX_BYTES else None


def printer_label(name):
    """The printer name as stored: whitespace collapsed, at most 56 characters, never empty."""
    return " ".join(str(name or "").split())[:56] or DEFAULT_PRINTER_NAME


def _clean(key, value):
    """The value to store for key, or None when it is not valid."""
    default = DEFAULTS[key]
    if key == "ui_language":
        return value if value in UI_LANGUAGES else None
    if key == "spoolman_refresh_s":
        return value if type(value) is int and (value == 0 or REFRESH_RANGE[0] <= value <= REFRESH_RANGE[1]) else None
    if key == "bridge_port":
        return value if type(value) is int and PORT_RANGE[0] <= value <= PORT_RANGE[1] else None
    if type(value) is not type(default):
        return None
    if key == "spoolman_url":
        return spoolman.clean_url(value, strict=False)
    if key == "printer_name":
        return printer_label(value)
    if key == "print_memory":
        return printsetup.clean_memory(value)
    if key == "dashboard":
        return clean_dashboard(value)
    return value.strip() if isinstance(value, str) else value


def invalid(changes):
    """The known keys of changes whose value would not be stored, sorted."""
    return sorted(k for k, v in changes.items() if k in DEFAULTS and _clean(k, v) is None)


class Store:
    """JSON file at `path`, or load() -> text / save(text) callables when no path is available."""

    def __init__(self, path=None, load=None, save=None):
        self.path, self._load, self._save = path, load, save
        self.lock = threading.RLock()
        self.data = self._read()

    def _read(self):
        try:
            if self.path:
                with open(self.path, encoding="utf-8") as f:
                    text = f.read()
            elif self._load:
                text = self._load()
            else:
                return {}
            data = json.loads(text)
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data):
        text = json.dumps(data, indent=1, sort_keys=True)
        if self.path:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.path)
        elif self._save:
            self._save(text)
        self.data = data

    def effective(self):
        with self.lock:
            out = dict(DEFAULTS)
            for key in DEFAULTS:
                if key in self.data:
                    clean = _clean(key, self.data[key])
                    if clean is not None:
                        out[key] = clean
            return out

    def raw(self):
        with self.lock:
            return dict(self.data)

    def update(self, changes):
        """Validate and persist {key: value}; unknown or invalid keys are ignored. Returns effective()."""
        with self.lock:
            data = dict(self.data)
            for key, value in (changes if isinstance(changes, dict) else {}).items():
                clean = _clean(key, value) if key in DEFAULTS else None
                if clean is not None:
                    data[key] = clean
            if data != self.data:
                self._write(data)
            return self.effective()
