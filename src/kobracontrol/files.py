"""Pure helpers for the printer's local file list (the `files` and `file_details` of `kobra.State.view()`):
page rows, name checks for print and delete, the print/start payload. Free of the `orca` module.

There are no downloads: neither Kobralink nor KX-Bridge has a way to fetch a file back from the printer
(the printer only lists, details, deletes and prints; a file's thumbnail comes inline in file_details)."""

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


class FilesMixin:
    """For service.Service: needs _printer() (a connected kobra.Printer), _view() (slots and mode) and _require_idle()."""

    _details_lock = threading.Lock()

    def _dcache(self):
        """{file name: file_details} fetched so far (thumbnails); kept for the life of the service."""
        with self._details_lock:
            return self.__dict__.setdefault("_details", {})

    def cmd_files(self):
        """Fresh list of the printer's files, as page rows (thumbnails known so far included)."""
        printer = self._printer()
        listing = printer.list_files()
        details = dict(self._dcache())
        return {"files": rows(listing, details)}

    def cmd_file_details(self, name):
        details = self._printer().file_details(valid_name(name))
        self._dcache()[name] = details
        return {"name": name, "thumbnail": _thumbnail(details)}

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
        self._printer().delete_files(names)
        cache = self._dcache()
        for n in names:
            cache.pop(n, None)
        return self.cmd_files()
