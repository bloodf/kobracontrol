"""Interop with the Spooler plugin (github.com/bloodf/spooler), which turns Spoolman filaments into
OrcaSlicer filament presets in the local bundle "spooler". Free of the `orca` module.

preset meta: {"name", "bundle_id", "compatible_printers": [..], "colour": "#RRGGBB", "vendor"}
"""

import json
import os
import re

import filmatch
import spoolman

BUNDLE_ID = "spooler"
URL = "https://github.com/bloodf/spooler"
NAME_PREFIX = "_local/spooler/"
DATA_SUBDIR = "spooler"                  # <Orca data dir>/spooler/, the data dir being the parent of orca_plugins
SETTINGS_FILE = "spooler_settings.json"
PROFILES_FILE = "profiles.json"          # {"version": 1, "filaments": {"<filament id>": {"<printer label>": "<preset>"}},
                                         #  "spools": {"<spool id>": {...}}, "ids": {"<preset>": "<filament_id>"}};
                                         #  "spools" only with presets per spool
KEEP_SLOTS_FILE = "keep_slots.json"      # {"active": true, "printer": "<label>", "ts": <unix s>}, refreshed ~5 s
KEEP_SLOTS_FRESH = 30.0                  # seconds
PROFILES_VERSION = 1
COLOUR_CAP = 120.0   # redmean distance beyond which "nearest colour" is no longer the same spool


def detect(bundle_ids, filament_presets_meta, settings_file_exists=False):
    count = sum(1 for m in filament_presets_meta or () if m.get("bundle_id") == BUNDLE_ID)
    installed = BUNDLE_ID in (bundle_ids or ()) or count > 0 or bool(settings_file_exists)
    return {"installed": installed, "presets": count}


def data_dir(storage_path):
    """Spooler's data folder from this plugin's storage path ("" when no orca_plugins folder above it)."""
    cur = os.path.abspath(storage_path or "")
    while os.path.dirname(cur) != cur:
        if os.path.basename(cur) == "orca_plugins":
            return os.path.join(os.path.dirname(cur), DATA_SUBDIR)
        cur = os.path.dirname(cur)
    return ""


def read_json(folder, name):
    """Parsed JSON object from folder/name; None when missing, unreadable or not an object."""
    if not folder:
        return None
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def keep_slots_active(marker, now, printer_labels=()):
    """Spooler's "Keep Slots Synced" is running for this printer: "active" is true, "ts" was refreshed within
    KEEP_SLOTS_FRESH seconds, and its "printer" label matches one of printer_labels. Spooler's label is the
    printer model, or "<model> <nozzle>" when two presets share a model.
    A fresh marker without a usable "printer" label (or nothing to compare it with) also counts as a match:
    the printer it is for is unknown, so kobracontrol pauses its automatic sync rather than risk two automations
    writing the same project slots. Manual sync is never paused. A marker of the wrong shape counts as
    inactive."""
    if not isinstance(marker, dict) or marker.get("active") is not True:
        return False
    ts = marker.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)) or abs(now - ts) >= KEEP_SLOTS_FRESH:
        return False
    printer = marker.get("printer")
    label = printer.strip().lower() if isinstance(printer, str) else ""
    wanted = [str(p).strip().lower() for p in printer_labels if p]
    return not label or not wanted or any(label == w or label.startswith(w + " ") or w.startswith(label + " ")
                                          for w in wanted)


def profiles_problem(profiles):
    """Why a profiles.json can't be used ("" when it can, or when there is none): callers then fall back
    to colour matching."""
    if profiles is None:
        return ""
    if profiles.get("version") != PROFILES_VERSION or isinstance(profiles.get("version"), bool):
        return "unsupported version %r" % (profiles.get("version"),)
    if not isinstance(profiles.get("filaments"), dict):
        return "\"filaments\" is not an object"
    return ""


def profile_lookup(profiles, filament_id, printer_label, spool_id=None):
    """Preset name Spooler published for a Spoolman spool (its own preset, made when Spooler has presets per
    spool) or else its filament, on the printer with this label; None when there is none (also for a file of
    another version or shape)."""
    if not isinstance(profiles, dict) or profiles_problem(profiles):
        return None
    spools = profiles.get("spools") if isinstance(profiles.get("spools"), dict) else {}
    for table, key in ((spools, spool_id), (profiles["filaments"], filament_id)):
        name = _label_lookup(table.get(str(key)), printer_label) if key is not None else None
        if name:
            return name
    return None


def _label_lookup(entry, printer_label):
    if not isinstance(entry, dict) or not entry:
        return None
    label = str(printer_label or "").casefold()
    names = [(str(k).casefold(), v) for k, v in entry.items() if isinstance(v, str) and v]
    for key, name in names:
        if key == label:
            return name
    for key, name in names:  # "Anycubic Kobra X 0.4" style labels when the model is duplicated
        if label and key.startswith(label):
            return name
    return None


def as_list(value):
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [p.strip().strip('"') for p in str(value or "").split(";") if p.strip()]


def spooler_presets(names_meta, printer_names=()):
    """Spooler presets usable with the current printer (any when it, or the preset's list, is unknown)."""
    wanted = {n for n in printer_names if n}
    out = []
    for m in names_meta or ():
        if m.get("bundle_id") != BUNDLE_ID:
            continue
        compatible = as_list(m.get("compatible_printers"))
        if not compatible or not wanted or wanted & set(compatible):
            out.append(m)
    return out


def _norm(text):
    return re.sub(r"[^a-z0-9+]", "", str(text or "").lower())


def _bare(name):
    return name[len(NAME_PREFIX):] if name.startswith(NAME_PREFIX) else name


def preset_for_spool(presets, spool, profiles=None, printer_label=""):
    """Name of the Spooler preset for a bound spool: Spooler's published profiles.json entry, else the
    nearest colour of the same vendor + material."""
    published = profile_lookup(profiles, spool.get("filament_id"), printer_label, spool.get("id"))
    if published:
        by_bare = {_bare(p["name"]).casefold(): p["name"] for p in presets}
        if _bare(published).casefold() in by_bare:
            return by_bare[_bare(published).casefold()]
    vendor, material = _norm(spool.get("vendor")), _norm(spool.get("material"))
    near = []
    for p in presets:
        bare = _norm(_bare(p["name"]))
        same_vendor = _norm(p.get("vendor")) == vendor if p.get("vendor") else vendor in bare
        if material and material in bare and vendor and same_vendor:
            near.append((spoolman.colour_distance(spool.get("colour"), p.get("colour")), len(p["name"]), p["name"]))
    near.sort()
    return near[0][2] if near and near[0][0] <= COLOUR_CAP else None


def tray_filament_id(spool, presets, profiles=None, printer_label=""):
    """The filament_id a printer agent reports for a tray holding this Spoolman spool (tray_info_idx), or "".
    OrcaSlicer's sync from AMS (PresetBundle::sync_ams_list) loads the compatible base preset carrying that
    id; Spooler's presets are standalone ones with ids of their own, which only profiles.json "ids" tells
    (OrcaSlicer's plugin API doesn't show a preset's filament_id). presets: Spooler's preset meta
    {"name", "bundle_id", "colour", "vendor"} usable with this printer. "" leaves it to the Generic id."""
    if not spool or not isinstance(profiles, dict) or not isinstance(profiles.get("ids"), dict):
        return ""
    name = preset_for_spool(presets, spool, profiles, printer_label)
    ids = {_bare(str(k)).casefold(): v for k, v in profiles["ids"].items() if isinstance(v, str)}
    return ids.get(_bare(name).casefold(), "") if name else ""


def find_user_preset(name, presets):
    """(preset, problem) for the name a spool's orca_filament_preset gives. presets: the user's own filament presets
    as {"name", "compatible", "file", "inherits"}. The exact name, else the only case-insensitive match, and only
    one OrcaSlicer counts as compatible with the selected printer. problem: "" with a preset; else "ambiguous"
    (several case-insensitive matches, none exact) or "missing" (none, or not compatible)."""
    found = [p for p in presets if p["name"] == name] or [p for p in presets if p["name"].casefold() == name.casefold()]
    if len(found) > 1:
        return None, "ambiguous"
    return (found[0], "") if found and found[0]["compatible"] else (None, "missing")


def standalone_id(preset, log=None):
    """The filament_id OrcaSlicer's sync from AMS loads this user preset by, or "". Sync only loads a preset that
    is its own base: one inheriting a parent carries the parent's id and loads the parent, so it gets "". A
    standalone preset's id is the "filament_id" in its JSON file (OrcaSlicer's plugin API doesn't show it)."""
    path = (preset.get("file") or "") if preset and not preset.get("inherits") else ""
    data = read_json(os.path.dirname(path), os.path.basename(path)) if path else None
    if path and data is None and log:
        log("filament preset file not readable: %s" % path)
    fid = data.get("filament_id") if data else None
    return fid.strip() if isinstance(fid, str) else ""


def cached_standalone_id(preset, cache, log=None):
    """standalone_id(), read once per version of the preset's file: cache is {(file, mtime, size, inherits): filament_id}."""
    try:
        st = os.stat(preset["file"])
        key = (preset["file"], st.st_mtime_ns, st.st_size, bool(preset.get("inherits")))   # size too: a rewrite can keep a coarse mtime
    except (OSError, ValueError, TypeError):
        key = (preset.get("file"), None, None, None)   # gone or unreadable: never a cached id of an older version
    if key not in cache:
        cache[key] = standalone_id(preset, log)
    return cache[key]


# --- Matching a slot to a preset (filmatch) ------------------------------------------------------------------------
# A slot is reported to OrcaSlicer's sync from AMS with a filament_id (tray_info_idx), so only presets whose id is known
# can be chosen: Spooler's (profiles.json "ids"), the user's standalone ones (their file) and the Generic preset of the
# slot's material (filmatch.GENERIC_IDS). The preset picked by hand for what a slot holds (its spool, RFID tag, SKU, or
# vendor + material) is kept in matches.json: Spooler's (shared with Spooler and U1 Control) read first and written
# while Spooler is installed, else Kobra Control's own.
MATCH_CHOICES = 5   # candidates a slot card offers
_stores = {}        # path -> ((mtime, size), store): matches.json read again only when it changed


def match_paths(storage):
    """(paths to read, Spooler's first; the path to write, "" when there is none) for this plugin's storage folder."""
    folder = data_dir(storage)
    shared = os.path.join(folder, filmatch.MATCHES_FILE) if folder else ""
    own = os.path.join(storage, filmatch.MATCHES_FILE) if storage else ""
    spooler_on = bool(shared) and os.path.isfile(os.path.join(folder, SETTINGS_FILE))
    return [p for p in (shared, own) if p], shared if spooler_on else own


def load_stores(paths):
    out = []
    for path in paths:
        try:
            st = os.stat(path)
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = None
        cached = _stores.get(path)
        if not cached or cached[0] != stamp:
            cached = _stores[path] = (stamp, filmatch.load_matches(path) if stamp else {"version": 1, "entries": {}})
        out.append(cached[1])
    return out


def match_context(presets, label, users, profiles, stores, file_ids, log=None):
    """What slot_match needs, read once: the presets a slot can be reported as, {name: filament_id}. presets: Spooler's
    preset meta compatible with the printer; users: the user's own presets ({"name", "compatible", "file", "inherits"})."""
    spooler_ids = {_bare(str(k)).casefold(): v for k, v in ((profiles or {}).get("ids") or {}).items() if isinstance(v, str) and v}
    ids = {p["name"]: spooler_ids[_bare(p["name"]).casefold()] for p in presets if _bare(p["name"]).casefold() in spooler_ids}
    for user in users or ():
        fid = cached_standalone_id(user, file_ids, log) if user.get("compatible") else ""
        if fid:
            ids[user["name"]] = fid
    return {"presets": presets, "label": label, "users": users or [], "profiles": profiles, "stores": stores, "ids": ids}


def ofd_folder(storage):
    """The folder the Open Filament Database's index is kept in: Spooler's (shared) while Spooler is installed, else
    this plugin's own; "" when there is none."""
    folder = data_dir(storage)
    if folder and os.path.isfile(os.path.join(folder, SETTINGS_FILE)):
        return os.path.join(folder, filmatch.OFD_DIR)
    return os.path.join(storage, filmatch.OFD_DIR) if storage else ""


def slot_ofd(profiles, slot, spool):
    """OFD presets for what a slot holds: its spool's (or the slot's own) manufacturer and material."""
    vendor = (spool or {}).get("vendor") or slot.get("brand") or ""
    name = " ".join(str(x) for x in ((spool or {}).get("name"), slot.get("material_name")) if x)
    return filmatch.rank_ofd(profiles, vendor, str(slot.get("type") or ""), name, MATCH_CHOICES)


def _slot_colour(slot):
    c = list(slot.get("color") or [])[:3]
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(x))) for x in c) if len(c) == 3 else ""


def _slot_presets(ctx, slot, spool):
    """(head, {name: filament_id} the slot can be reported as, ranked candidates of its material)."""
    material = str(slot.get("type") or "")
    family = filmatch.generic_family(material)
    generic = "Generic %s" % family if family else ""
    known = {**ctx["ids"], **({generic: filmatch.GENERIC_IDS[family]} if generic else {})}
    head = {"type": material, "vendor": (spool or {}).get("vendor") or slot.get("brand") or "", "sub_type": "",
            "colour": _slot_colour(slot)}
    return head, known, generic, filmatch.rank_filament_presets(list(known), head, None, ctx["label"])


def slot_match(ctx, slot, spool):
    """The preset the Device tab reports for a slot, and why: {"slot", "name", "id", "source", "score", "reasons",
    "confident", "candidates", "keys", "remembered_key"}. source: "linked" (the spool's orca_filament_preset),
    "remembered" (picked by hand), "spooler" (Spooler's preset of the spool), "generic" or "none"."""
    head, known, generic, ranked = _slot_presets(ctx, slot, spool)
    fits = {r["name"] for r in ranked}
    keys = filmatch.observation_keys((spool or {}).get("id"), slot.get("rfid") or "", slot.get("sku") or "", head["vendor"], head["type"])
    name, source, used = "", "none", ""
    linked = find_user_preset(spool["orca_preset"], ctx["users"])[0] if (spool or {}).get("orca_preset") else None
    if linked and known.get(linked["name"]):
        name, source = linked["name"], "linked"
    for key in keys if not name else ():
        name = next((n for n in filmatch.recall(ctx["stores"], [key], ctx["label"]) if n in fits), "")
        if name:
            source, used = "remembered", key
            break
    if not name and spool:
        mine = preset_for_spool(ctx["presets"], spool, ctx["profiles"], ctx["label"])
        if mine and known.get(mine):
            name, source = mine, "spooler"
    if not name and generic:
        name, source = generic, "generic"
    row = next((r for r in ranked if r["name"] == name), {})
    top = bool(ranked) and ranked[0]["name"] == name
    return {"slot": slot.get("global_index"), "name": name, "id": known.get(name, ""), "source": source,
            "score": row.get("score"), "reasons": row.get("reasons") or [],
            "confident": source in ("linked", "remembered", "spooler") or (top and filmatch.confident(ranked, filmatch.PRESET_MARGIN)),
            "candidates": ranked[:MATCH_CHOICES], "keys": keys, "remembered_key": used}


def remember_slot(ctx, slot, spool, name, paths, write):
    """A slot card's Change: remember name for what the slot holds (its most specific key) on this printer; None
    forgets the choice made by hand. Raises ValueError for a preset that can't be reported for the slot's material."""
    match = slot_match(ctx, slot, spool)
    if name is None:
        for path in paths if match["remembered_key"] else ():
            filmatch.remember(path, {match["remembered_key"]: ""}, ctx["label"])
            filmatch.remember(path, {match["remembered_key"]: ""})
        return
    if name not in {r["name"] for r in _slot_presets(ctx, slot, spool)[3]} or not match["keys"] or not write:
        raise ValueError(name)
    filmatch.remember(write, {match["keys"][0]: name}, ctx["label"])
