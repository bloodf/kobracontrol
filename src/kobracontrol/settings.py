"""One flat, validated settings store (page, printer agent, scripts). Free of the `orca` module.
No secrets are kept here: the printer's MQTT credentials live in memory only."""

import json
import os
import threading

import spoolman

DEFAULT_PRINTER_NAME = "Anycubic Kobra X"
UI_LANGUAGES = ("auto", "en", "pt-BR")   # "auto": OrcaSlicer's language, then the system's
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
    "spooler_hint_dismissed": False,
}


def printer_label(name):
    """The printer name as stored: whitespace collapsed, at most 56 characters, never empty."""
    return " ".join(str(name or "").split())[:56] or DEFAULT_PRINTER_NAME


def _clean(key, value):
    """The value to store for key, or None when it is not valid."""
    default = DEFAULTS[key]
    if key == "ui_language":
        return value if value in UI_LANGUAGES else None
    if type(value) is not type(default):
        return None
    if key == "spoolman_url":
        return spoolman.clean_url(value, strict=False)
    if key == "printer_name":
        return printer_label(value)
    return value.strip() if isinstance(value, str) else value


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
