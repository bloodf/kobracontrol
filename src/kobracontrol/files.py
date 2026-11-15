"""Pure helpers for the printer's local file list (the `files` and `file_details` of `kobra.State.view()`):
page rows, name checks for print and delete, the print/start payload. Free of the `orca` module.

There are no downloads: neither Kobralink nor KX-Bridge has a way to fetch a file back from the printer
(the printer only lists, details, deletes and prints; a file's thumbnail comes inline in file_details)."""

import math
import re
import threading

import ace
import kobra

MAX_NAME = 255
MAX_DELETE = 200
THUMB_MAX = 1024 * 1024                      # characters of base64 kept per thumbnail
_B64 = re.compile(r"^[A-Za-z0-9+/=\s]+$")
_DATA_PNG = re.compile(r"^data:image/png;base64,[A-Za-z0-9+/=]+$")


def valid_name(name):
    """The file name unchanged, or ValueError: no path separators, no control characters, not "." or ".."."""
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME or name in (".", ".."):
        raise ValueError("not a valid file name")
    if "/" in name or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("a file name has no path separators or control characters")
    return name


def valid_names(names):
    """Checked, de-duplicated names (order kept) for a delete; ValueError for none, too many or a bad one."""
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError("no files chosen")
    if len(names) > MAX_DELETE:
        raise ValueError("too many files at once (at most %d)" % MAX_DELETE)
    return list(dict.fromkeys(valid_name(n) for n in names))


def _thumbnail(details):
    raw = details.get("thumbnail") if isinstance(details, dict) else None
    if not isinstance(raw, str) or not raw or len(raw) > THUMB_MAX:
        return None
    if raw.startswith("data:"):
        return raw if _DATA_PNG.match(raw) else None
    return "data:image/png;base64," + "".join(raw.split()) if _B64.match(raw) else None


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def rows(files, details=None):
    """Rows for the page, in the printer's order (newest first): {"name", "size", "timestamp", "thumbnail"}.
    details: {file name: file_details dict} for the files whose details were requested; thumbnail is a PNG
    data URL, or None while unknown."""
    details = details if isinstance(details, dict) else {}
    out = []
    for f in files if isinstance(files, list) else []:
        name = f.get("filename") if isinstance(f, dict) else None
        try:
            valid_name(name)
        except ValueError:
            continue
        out.append({"name": name, "size": _number(f.get("size")), "timestamp": _number(f.get("timestamp")),
                    "thumbnail": _thumbnail(details.get(name))})
    return out


def print_payload(files, name, mapping, auto_leveling=False, vibration_compensation=False, skip_parts=None):
    """print/start data for a file that is on the printer (ValueError when it is not in `files`)."""
    valid_name(name)
    found = next((f for f in files or [] if isinstance(f, dict) and f.get("filename") == name), None)
    if found is None:
        raise ValueError("%s is not on the printer" % name)
    task = {"auto_leveling": bool(auto_leveling), "vibration_compensation": bool(vibration_compensation),
            "skip_parts": [str(p) for p in skip_parts or []]}
    return kobra.print_file_payload(name, _number(found.get("size")), mapping, task)


def _finite(value, digits=2):
    """A finite, non-negative number rounded to `digits`, else None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        return None
    return round(value, digits) if digits else int(value)


def _hex(rgb):
    if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        return ""
    try:
        return "#%02X%02X%02X" % tuple(max(0, min(255, int(c))) for c in rgb[:3])
    except (TypeError, ValueError, OverflowError):
        return ""


def _material(value):
    return " ".join(value.split()).upper() if isinstance(value, str) else ""


def plan(details, slots, mode, model=""):
    """What a printer file needs, next to the slots a print of it from the Files page would use.

    details: the printer's file_details; slots, mode: status.data. Returns {"info": {estimated_s, layers,
    filament_g, layer_height, nozzle_temp, bed_temp, nozzle (None when unknown), printer_model, model_ok},
    "materials": [{paint_index, material, colour, grams, slot (global index, None when the print maps no slot),
    slot_type, slot_colour, check: "ok" | "differs" | "missing"}]}. Read-only: nothing is sent to the printer.
    The slot of each filament follows ace.build_auto_ams_box_mapping, the mapping cmd_file_print sends: tool N
    prints from the usable slot N, else from the highest usable slot; a tool above it has no entry."""
    d = details if isinstance(details, dict) else {}
    params = d.get("print_parameters") if isinstance(d.get("print_parameters"), dict) else {}
    basic = params.get("basic_info") if isinstance(params.get("basic_info"), dict) else {}
    temps = params.get("temperatures") if isinstance(params.get("temperatures"), dict) else {}
    printer_model = d.get("printer_model") if isinstance(d.get("printer_model"), str) else ""
    info = {"estimated_s": _finite(d.get("estimated_time_s"), 0), "layers": _finite(d.get("layer_count"), 0),
            "filament_g": _finite(d.get("total_filament_used")), "layer_height": _finite(basic.get("layer_height")),
            "nozzle_temp": _finite(temps.get("nozzle_temp"), 0), "bed_temp": _finite(temps.get("bed_temp"), 0),
            "nozzle": _finite(d.get("nozzle_diameter")), "printer_model": printer_model,
            "model_ok": not printer_model or bool(re.search(r"kobra[ _-]*x\b", printer_model, re.I))}
    usable = {s["global_index"]: s for s in ace.select_loaded_slots_for_print(slots, mode)[0]}
    top = max(usable) if usable else None
    materials = []
    for p in d.get("paint_infos") if isinstance(d.get("paint_infos"), list) else []:
        index = p.get("paint_index") if isinstance(p, dict) else None
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            continue
        slot = usable.get(index, usable.get(top)) if top is not None and index <= top else None
        material = _material(p.get("material_type"))
        check = "missing" if slot is None else ("differs" if material and _material(slot["type"]) != material else "ok")
        materials.append({"paint_index": index, "material": material, "colour": _hex(p.get("paint_color")),
                          "grams": _finite(p.get("filament_used")) or 0, "slot": slot["global_index"] if slot else None,
                          "slot_type": slot["type"] if slot else "", "slot_colour": _hex(slot["color"]) if slot else "",
                          "check": check})
    return {"info": info, "materials": materials}


class FilesMixin:
    """For service.Service: needs _printer() (a connected kobra.Printer), _view() (slots and mode) and _require_idle()."""

    _details_lock = threading.Lock()

    def _dcache(self, printer):
        """{file name: file_details} fetched so far from this printer (thumbnails). One dict per printer, so
        a file of the same name on another printer never shows this one's thumbnail."""
        creds = getattr(printer, "creds", None)
        key = (getattr(creds, "ip", ""), getattr(creds, "device_id", ""))
        with self._details_lock:
            return self.__dict__.setdefault("_details", {}).setdefault(key, {})

    def cmd_files(self):
        """Fresh list of the printer's files, as page rows (thumbnails known so far included)."""
        printer = self._printer()
        listing = printer.list_files()
        cache = self._dcache(printer)
        with self._details_lock:
            names = {f.get("filename") for f in listing}
            for gone in [n for n in cache if n not in names]:   # deleted (maybe re-uploaded): details are stale
                del cache[gone]
            details = dict(cache)
        return {"files": rows(listing, details)}

    def cmd_file_details(self, name):
        printer = self._printer()
        details = printer.file_details(valid_name(name))
        self._dcache(printer)[name] = details
        view = self._view()
        return {"name": name, "thumbnail": _thumbnail(details),
                **plan(details, view["slots"], view["mode"], view.get("model") or "")}

    def cmd_file_print(self, name, auto_leveling=False, vibration_compensation=False):
        self._require_idle()
        printer = self._printer()
        view = self._view()
        loaded, _ = ace.select_loaded_slots_for_print(view["slots"], view["mode"])
        mapping = ace.build_auto_ams_box_mapping(loaded, view["mode"])   # as Kobralink and KX-Bridge do
        payload = print_payload(printer.list_files(), name, mapping, auto_leveling, vibration_compensation)
        printer.start_print(payload)
        return {"started": name}

    def cmd_file_delete(self, names):
        names = valid_names(names)
        printer = self._printer()
        printer.delete_files(names)
        cache = self._dcache(printer)
        for n in names:
            cache.pop(n, None)
        return self.cmd_files()
