"""ACE / multi-colour-box slot model for the Anycubic Kobra X.

Pure logic, standard library only, no I/O. Ported from two GPL-3.0 projects:
  Kobralink (TypeScript): apps/api/src/bridge/ams.ts, packages/shared/src/state.ts
  KX-Bridge (Python, viewit): bridge_ams.py, tools/probe_ams_setinfo.py
Where they disagree the choice is commented "Kobralink:" / "KX-Bridge:" at the
function. Inputs are never mutated; every function returns new objects.

Input: the `multi_color_box` list of a `multiColorBox/report` message, each box
`{id, loaded_slot, auto_feed, slots: [{index, status, type, color, rfid, sku}],
feed_status, drying_status, drying_settings}`. Box `id` -1 is the print head's
own feeder ("toolhead"), whose slots are the spools on the printer's spool
holder; ids >= 0 are ACE units. With an ACE connected the head's fourth inlet
carries the ACE, so the holder has 3 positions: 3 + 4 sources with one ACE.

Filament mode (`detect_filament_mode`):
    "toolhead"   only the head box (or nothing); the external spool is always one slot at least.
    "ace_direct" ACE units only; the printer is fed straight from the ACE.
    "ace_hub"    head box and ACE units together.

Slot dict (`aggregate_slots`):
    global_index  int   position in the flat slot list (rules below)
    box_id        int   reported box id, -1 for the head
    box_pos       int   ams_id (OrcaSlicer's AMS unit): ACE: its box_id;
                        head: 0 without an ACE, else the unit after the last
                        ACE (stable under gaps and report order, as
                        KX-Bridge's multi-ACE tests need)
    index         int   slot index inside its box
    status        int   5 = filament loaded/ready; anything else is not usable
    type          str   material, "" when unknown
    color         [r, g, b]  ints; 3 components kept, 4th (alpha) dropped,
                        missing/short -> [255, 255, 255]
    rfid          int | None
    sku           str | None
    percent       int | None   consumables_percent (spool remaining), None if absent
    weight        int | None   grams, None if absent
    brand         str   brand_name; the firmware's "public" means no brand -> ""
    material_name str   "" when absent
    activity      str   "" (see `slot_activity_map`: loading/unloading/loaded)

global_index rule: box_pos * 4 + slot position, the same number as the tray id
    toolhead:   slot position in the head box (0..n-1)
    ace_direct: box_id * 4 + index   (each ACE truncated to 4 slots)
    ace_hub:    ACE slots box_id * 4 + index, as in ace_direct; the head
                (truncated to 3) after the last ACE: one ACE -> 0..3 ACE,
                4..6 holder.
    KX-Bridge and Kobralink number the head first in hub mode (head 0..2,
    ACE 3 + box_id * 4 + index). Here the ACE keeps its numbers whether or
    not the holder is reported, and a slot's number is the tray id Spooler
    writes into a spool's location ("S<n>", n = box * 4 + slot + 1).
tray id rule (Bambu form, what OrcaSlicer's dialog uses):
    tray_id = box_pos * 4 + index
print `ams_index` rule (`slot_to_print_ams_index`, goes into ams_box_mapping),
both references (KX-Bridge _slot_to_print_ams_index, Kobralink
slotToPrintAmsIndex):
    ace_hub, ACE slot:   4 + box_id * 4 + index
    ace_hub, head slot:  index (0..2)
    otherwise:           global_index
    Neither tray id nor global_index is the print index in hub mode; always
    go through `slot_to_print_ams_index`.

mapping entry: {paint_index, ams_index, paint_color [r,g,b,a],
ams_color [r,g,b,a], material_type}.
"""

import math
from types import MappingProxyType

from i18n import tr

READY_STATUS = 5
_WHITE = [255, 255, 255]

# Immutable template; `aggregate_ace_units` always returns fresh dict copies.
EMPTY_DRYING = MappingProxyType(
    {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0, "humidity": None, "current_temp": None}
)


def _num(value, default=0):
    """JS `Number(v ?? default)` with NaN collapsed to `default`."""
    if value is None:
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(n):
        return default
    return int(n) if n == int(n) else n


def _box_id(box):
    return _num(box.get("id"), -1)


def _is_head(box):
    # Both references: head only when id is explicitly -1 (a missing id is
    # neither head nor ACE).
    return box.get("id") == -1


def detect_filament_mode(boxes, head_tools_model=-1):
    # head_tools_model is accepted (KX-Bridge signature) but, as in both
    # references, does not influence the result.
    head = any(_is_head(b) for b in boxes)
    units = any(_box_id(b) >= 0 for b in boxes)
    if units and head:
        return "ace_hub"
    if units:
        return "ace_direct"
    return "toolhead"


def _brand(name):
    name = "" if name is None else str(name)
    return "" if name.strip().lower() == "public" else name


def _to_slot(raw, global_index, box_id, box_pos, index=None):
    c = raw.get("color")
    c = list(c) if isinstance(c, (list, tuple)) and len(c) >= 3 else _WHITE
    rfid, sku = raw.get("rfid"), raw.get("sku")
    return {
        "global_index": global_index,
        "box_id": box_id,
        "box_pos": box_pos,
        "index": index if index is not None else _num(raw.get("index"), global_index % 4),
        "status": _num(raw.get("status"), 0),
        "type": str(raw.get("type") if raw.get("type") is not None else ""),
        "color": [max(0, min(255, int(_num(v, 0)))) for v in c[:3]],
        "rfid": None if rfid is None else _num(rfid, 0),
        "sku": None if sku is None else str(sku),
        "percent": None if raw.get("consumables_percent") is None else _num(raw["consumables_percent"], None),
        "weight": None if raw.get("weight") is None else _num(raw["weight"], None),
        "brand": _brand(raw.get("brand_name")),
        "material_name": str(raw.get("material_name") or ""),
        "activity": "",
    }


def _indexed(raw_slots, limit):
    """[(local slot number, raw slot)]: a report may list a unit's slots in any order, so a slot's reported "index"
    is its identity (global_index, tray id and print ams_index all derive from it). Only when no slot reports an
    index is the list position used. A slot with a missing, out-of-range or repeated index is skipped, never
    given another slot's number."""
    if not any(s.get("index") is not None for s in raw_slots):
        return list(enumerate(raw_slots[:limit]))
    out, seen = [], set()
    for s in raw_slots:
        i = s.get("index")
        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < limit and i not in seen:
            seen.add(i)
            out.append((i, s))
    return out


def aggregate_slots(boxes, mode):
    """Return (slots, loaded_global_index); loaded is -1 when nothing is loaded."""
    head = next((b for b in boxes if _is_head(b)), None)
    aces = sorted((b for b in boxes if _box_id(b) >= 0), key=_box_id)
    slots = []
    loaded = -1

    if mode == "toolhead":
        if head:
            raw = head.get("slots") or []
            for i, s in _indexed(raw, max(len(raw), 1)):
                slots.append(_to_slot(s, i, -1, 0, i))
            if _num(head.get("loaded_slot"), -1) >= 0:
                loaded = _num(head["loaded_slot"])
        if not slots:
            # No ACE and the printer lists no holder slot (a Kobra S1 Max reports none): the external spool
            # is still a filament source. One slot, ready: there is no sensor to say otherwise.
            slots.append(_to_slot({"status": READY_STATUS}, 0, -1, 0, 0))
        return slots, loaded

    if mode == "ace_direct":
        for unit in aces:
            bid = _box_id(unit)
            pos = bid
            for i, s in _indexed(unit.get("slots") or [], 4):
                slots.append(_to_slot(s, bid * 4 + i, bid, pos, i))
            local = _num(unit.get("loaded_slot"), -1)
            if 0 <= local < 4:
                loaded = bid * 4 + local
        return slots, loaded

    # ace_hub: the ACE units as in ace_direct, then the head (the spool holder)
    # as the unit after the last ACE. An ACE's loaded slot wins over the head's.
    for unit in aces:
        bid = _box_id(unit)
        for i, s in _indexed(unit.get("slots") or [], 4):
            slots.append(_to_slot(s, bid * 4 + i, bid, bid, i))
        local = _num(unit.get("loaded_slot"), -1)
        if 0 <= local < 4:
            loaded = bid * 4 + local
    if head:
        pos = _head_pos(aces)
        for i, s in _indexed(head.get("slots") or [], 3):
            slots.append(_to_slot(s, pos * 4 + i, -1, pos, i))
        local = _num(head.get("loaded_slot"), -1)
        if 0 <= local <= 2 and loaded < 0:
            loaded = pos * 4 + local
    return slots, loaded


def _head_pos(aces):
    """The head's unit in hub mode: the one after the last ACE (0 with none)."""
    return max((_box_id(b) for b in aces), default=-1) + 1


def slot_usable_for_print(slot, mode):
    """state.ts:169 slotUsableForPrint."""
    if slot["status"] != READY_STATUS:
        return False
    if mode == "ace_hub":
        return True
    if mode == "ace_direct":
        return slot["box_id"] >= 0
    return slot["box_id"] == -1


def box_local_to_global(box_id, local_slot, mode, head_pos=0):
    """KX-Bridge _box_local_to_global, with this module's global_index rule. head_pos: the head's unit in
    hub mode (`_head_pos`)."""
    if box_id == -1:
        return (head_pos if mode == "ace_hub" else 0) * 4 + local_slot
    return box_id * 4 + local_slot


def slot_activity_map(boxes, global_loaded, mode, pending_load_slot=-1):
    """{global_index: "loading" | "unloading" | "loaded"}.

    KX-Bridge vs Kobralink disagree (neither has a test). Kobralink maps
    feed_status.current_status 10 -> "feeding", 11 -> "retracting". KX-Bridge
    maps feed_status.type 1 -> "loading", 2 -> "unloading", and treats
    current_status 10/11 (and -1) as completion events that carry no activity.
    KX-Bridge is used here: it handles slot swaps (the old slot shows
    "unloading" while the new one loads) and `pending_load_slot` (the slot the
    user asked for; transient firmware slots that differ are ignored).
    The extra "loaded" marker on the loaded slot is Kobralink's.
    """
    out = {}
    head_pos = _head_pos([b for b in boxes if _box_id(b) >= 0])
    for box in boxes:
        fs = box.get("feed_status") or {}
        status = _num(fs.get("current_status"), -1)
        local = _num(fs.get("slot_index"), -1)
        ftype = _num(fs.get("type"), -1)
        if status in (-1, 10, 11) or local < 0:
            continue
        box_slots = box.get("slots") or []
        fed = next((s for i, s in _indexed(box_slots, max(len(box_slots), 1)) if i == local), None)
        if fed is None or _num(fed.get("status"), 0) != READY_STATUS:
            continue
        act = {1: "loading", 2: "unloading"}.get(ftype)
        if act is None:
            continue
        g = box_local_to_global(_box_id(box), local, mode, head_pos)
        if ftype == 1 and pending_load_slot >= 0 and g != pending_load_slot:
            if global_loaded >= 0 and global_loaded != pending_load_slot:
                out[global_loaded] = "unloading"
            continue
        if ftype == 1 and global_loaded >= 0 and g != global_loaded:
            out[global_loaded] = "unloading"
        out[g] = act
    if global_loaded >= 0 and global_loaded not in out:
        out[global_loaded] = "loaded"
    return out


def slot_to_print_ams_index(slot, mode):
    if mode == "ace_hub":
        return 4 + slot["box_id"] * 4 + slot["index"] if slot["box_id"] >= 0 else slot["index"]
    return slot["global_index"]


def tray_id(slot):
    """Bambu tray id for a slot: box_pos * 4 + index."""
    return slot["box_pos"] * 4 + slot["index"]


def slot_for_tray(tray, slots):
    """Slot with that tray id, or None."""
    return next((s for s in slots if tray_id(s) == tray), None)


def _rgba(slot):
    return [slot["color"][0], slot["color"][1], slot["color"][2], 255]


def _parse_hex(text):
    """'#RRGGBB' / 'RRGGBB' / 'RRGGBBAA' -> [r,g,b,a], or None if invalid."""
    h = str(text or "").strip().lstrip("#")
    if len(h) not in (6, 8):
        return None
    try:
        v = [int(h[i : i + 2], 16) for i in range(0, len(h), 2)]
    except ValueError:
        return None
    return v if len(v) == 4 else v + [255]


def _entry(paint_index, slot, mode, paint_color, material):
    return {
        "paint_index": paint_index,
        "ams_index": slot_to_print_ams_index(slot, mode),
        "paint_color": paint_color,
        "ams_color": _rgba(slot),
        "material_type": material,
    }


def build_assigned_ams_box_mapping(assignments, filaments, slots, mode):
    """assignments: [{paint_index?, slot_index (global), is_used?, paint_color?,
    material?}]; filaments: [{slot_index, color_hex, material}] (optional).
    Returns {"mapping", "unused", "invalid"}.

    Merge of the references (neither has a test): paint_index defaults to the
    assignment's position (KX-Bridge); paint_color is the assignment's own
    [r,g,b,a] (KX-Bridge), else the matching filament's color_hex
    (Kobralink), else white; material is slot type, else assignment material
    (KX-Bridge), else filament material (Kobralink), else PLA. A non-integer
    slot_index counts as invalid (KX-Bridge)."""
    mapping, unused, invalid = [], 0, 0
    for i, a in enumerate(assignments):
        if a.get("is_used") is False:
            unused += 1
            continue
        try:
            g = int(a["slot_index"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if g < 0:
            unused += 1
            continue
        slot = next((s for s in slots if s["global_index"] == g), None)
        if slot is None or not slot_usable_for_print(slot, mode):
            invalid += 1
            continue
        pidx = a.get("paint_index", i)
        paint = next((f for f in filaments if f.get("slot_index") == pidx), None)
        color = a.get("paint_color") or (_parse_hex(paint.get("color_hex")) if paint else None) or [255, 255, 255, 255]
        material = slot["type"] or a.get("material") or (paint.get("material") if paint else None) or "PLA"
        mapping.append(_entry(pidx, slot, mode, list(color), material))
    return {"mapping": mapping, "unused": unused, "invalid": invalid}


def build_auto_ams_box_mapping(loaded, mode):
    """One entry per paint index 0..max (entry N = tool N). A gap must not
    point at its own empty tray (the printer rejects it, KX-Bridge
    tests/test_auto_ams_box_mapping_empty_slot.py), so gaps reuse the highest
    loaded slot. Blank slot type becomes "PLA" (Kobralink; KX-Bridge would keep
    the blank string, untested)."""
    if not loaded:
        return []
    by_index = {s["global_index"]: s for s in loaded}
    top = max(by_index)
    fallback = by_index[top]
    out = []
    for i in range(top + 1):
        s = by_index.get(i, fallback)
        out.append(_entry(i, s, mode, [255, 255, 255, 255], s["type"] or "PLA"))
    return out


def auto_mapping_slots(loaded):
    """{tool: global slot} for build_auto_ams_box_mapping: the slot each tool prints from, a gap's being the
    highest loaded slot's."""
    if not loaded:
        return {}
    by_index = {s["global_index"]: s["global_index"] for s in loaded}
    top = max(by_index)
    return {i: by_index.get(i, top) for i in range(top + 1)}


def mapping_from_trays(tray_ids, filaments, slots, mode):
    """Build ams_box_mapping from OrcaSlicer's Bambu-form choice.

    tray_ids[i] is the tray for project filament i (-1 = unused).
    filaments[i] = {"colour": "#RRGGBB"|"RRGGBBAA", "type": "PLA"}.
    Returns (mapping, problems); every skipped or degraded filament adds a
    human-readable problem."""
    mapping, problems = [], []
    for i, tray in enumerate(tray_ids):
        if tray == -1:
            continue
        fil = filaments[i] if i < len(filaments) else None
        if fil is None:
            problems.append(tr("filament %d: no filament description for tray %d") % (i + 1, tray))
            fil = {"colour": "#FFFFFF"}
        slot = slot_for_tray(tray, slots)
        if slot is None:
            problems.append(tr("filament %d: tray %d does not exist") % (i + 1, tray))
            continue
        if slot["status"] != READY_STATUS:
            problems.append(tr("filament %d: tray %d is empty (slot status %s)") % (i + 1, tray, slot["status"]))
            continue
        if not slot_usable_for_print(slot, mode):
            problems.append(tr("filament %d: tray %d is not usable for print in %s mode") % (i + 1, tray, mode))
            continue
        color = _parse_hex(fil.get("colour"))
        if color is None:
            problems.append(tr("filament %d: invalid colour %r, using white") % (i + 1, fil.get("colour")))
            color = [255, 255, 255, 255]
        mapping.append(_entry(i, slot, mode, color, slot["type"] or fil.get("type") or "PLA"))
    return mapping, problems


def global_to_box_slot(slots, global_index, mode):
    """(box_id, local_slot) for a global index."""
    found = next((s for s in slots if s["global_index"] == global_index), None)
    if found:
        return found["box_id"], found["index"]
    # Not among the slots: by the global_index rule, unit global_index // 4. In hub mode the head is the
    # unit after the last known ACE.
    if mode == "toolhead":
        return -1, global_index
    pos, local = global_index // 4, global_index % 4
    if mode == "ace_hub" and pos == max((s["box_id"] for s in slots), default=-1) + 1:
        return -1, local
    return pos, local


def _minutes(value):
    n = _num(value, 0)
    # ams.ts minutes(): values above 24h of minutes are taken as seconds.
    # JS Math.round rounds halves up; floor(x + .5) matches.
    return max(0, math.floor(n / 60 + 0.5)) if n > 24 * 60 else max(0, int(n))


def _first_float(src, keys, default=None):
    """ams.ts num() / KX-Bridge _num_from(): first present key; `default` if
    that value is not numeric."""
    for k in keys:
        v = src.get(k)
        if v is None:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            return default
        return n if math.isfinite(n) else default
    return default


_HUMIDITY_KEYS = ["humidity", "current_humidity", "cur_humidity", "relative_humidity", "humidity_value"]
_TEMP_KEYS = ["current_temp", "cur_temp", "temperature", "temp", "drying_temp", "chamber_temp"]


def humidity_from(src, default=None):
    return _first_float(src, _HUMIDITY_KEYS, default)


def current_temp_from(src, default=None):
    return _first_float(src, _TEMP_KEYS, default)


def minutes_from(src, key, default=0):
    """Dryer time in minutes; firmware sometimes reports seconds, so values
    above 24h of minutes are divided by 60. Rounding is half-up (Kobralink);
    KX-Bridge uses Python round() (half-even), untested."""
    return _minutes(src.get(key, default))


def _to_drying(box, src):
    humidity = humidity_from(src)
    temp = current_temp_from(src)
    # Real report: box-level `humidity` and `temp` are siblings of drying_status.
    return {
        "status": _num(src.get("status"), 0),
        "target_temp": _num(src.get("target_temp"), 0),
        "duration": _minutes(src.get("duration")),
        "remain_time": _minutes(src.get("remain_time")),
        "humidity": humidity if humidity is not None else humidity_from(box),
        "current_temp": temp if temp is not None else current_temp_from(box),
    }


def aggregate_ace_units(boxes, previous):
    """Return (units, primary_drying). unit = {id, auto_feed, humidity, temp,
    status, model_id, drying}; humidity/temp/status/model_id are the box-level
    report fields (None when absent); only ids 0..3. `previous` (last units) supplies values the report omits."""
    units = []
    for box in boxes:
        uid = _box_id(box)
        if uid < 0 or uid > 3:
            continue
        prev = next((u for u in previous if u["id"] == uid), None)
        raw = box.get("drying_status")
        if raw is None:
            raw = box.get("drying_settings")
        if box.get("auto_feed") is not None:
            auto_feed = _num(box["auto_feed"]) == 1
        else:
            auto_feed = prev["auto_feed"] if prev else False
        if raw is not None:
            drying = _to_drying(box, raw)
        else:
            drying = dict(prev["drying"] if prev else EMPTY_DRYING)
        units.append({
            "id": uid,
            "auto_feed": auto_feed,
            "humidity": humidity_from(box),
            "temp": current_temp_from(box),
            "status": None if box.get("status") is None else _num(box["status"], None),
            "model_id": None if box.get("model_id") is None else _num(box["model_id"], None),
            "drying": drying,
        })
    units.sort(key=lambda u: u["id"])
    primary = next((u for u in units if u["drying"]["status"] != 0), units[0] if units else None)
    return units, dict(primary["drying"] if primary else EMPTY_DRYING)


# Dryer units, evidence (all minutes unless noted):
#  - Real Kobra X report (fw 2.0.2.8): remain_time 898 -> 896 over 126 s, so
#    remain_time counts MINUTES. duration stayed 86400 for the whole run, so it
#    is seconds (24 h) or a constant; it is NOT a reliable total. UI: show
#    remain_time (and target_temp); never duration or an "elapsed" derived
#    from it. `minutes_from` still maps duration > 1440 to seconds -> minutes.
#  - setDry request: Kobralink printer-bridge.ts aceDry (1246) and
#    mqtt-client.ts setDry (410), schema control.ts:63-68 (duration 10..1440,
#    default 240, temp 30..80), and KX-Bridge bridge_endpoints.py
#    handle_api_ace_dry (1480-1556, same clamps) both send duration and
#    remain_time in MINUTES, remain_time = duration. See `set_dry_payload`.
def aggregate_drying_state(data, boxes, current=None):
    """Port of KX-Bridge _update_ace_drying_state: the dashboard's single
    "ace_drying" dict, with a "units" list. `current` is the previous state
    (unchanged copy is returned when the report holds no drying info).

    KX-Bridge vs Kobralink: KX-Bridge `drying_status or drying_settings`
    (an empty dict falls through); Kobralink `??` (an empty dict wins). Here an
    empty dict falls through, as in KX-Bridge. Neither has a test."""
    cur = dict(current or {})
    per_unit = []
    for box in boxes:
        bid = _box_id(box)
        if bid < 0:
            continue
        bs = box.get("drying_status") or box.get("drying_settings")
        bs = bs if isinstance(bs, dict) else {}
        hu = humidity_from(bs, humidity_from(box))
        ct = current_temp_from(bs, current_temp_from(box))
        if bs or hu is not None or ct is not None:
            per_unit.append({
                "id": bid,
                "status": _num(bs.get("status"), 0),
                "target_temp": _num(bs.get("target_temp"), 0),
                "duration": minutes_from(bs, "duration"),
                "remain_time": minutes_from(bs, "remain_time"),
                "humidity": hu,
                "current_temp": ct,
            })
    src = data.get("drying_status") or data.get("drying_settings")
    # KX-Bridge falls back to the FIRST ACE box's dict as the top-level source,
    # which reports an idle unit 0 while unit 1 is drying. Kobralink picks the
    # active unit. Kobralink's rule is used: without a report-level dict the
    # active (else first) unit is the primary. Neither has a test.
    active = [u for u in per_unit if u["status"]]
    primary = active[0] if active else (per_unit[0] if per_unit else {})
    if isinstance(src, dict):
        return {
            "status": _num(src.get("status"), cur.get("status", 0)),
            "target_temp": _num(src.get("target_temp"), cur.get("target_temp", 0)),
            "duration": minutes_from(src, "duration", cur.get("duration", 0)),
            "remain_time": minutes_from(src, "remain_time", cur.get("remain_time", 0)),
            "humidity": humidity_from(src, primary.get("humidity", cur.get("humidity"))),
            "current_temp": current_temp_from(src, primary.get("current_temp", cur.get("current_temp"))),
            "units": per_unit,
        }
    if per_unit:
        return {
            "status": primary["status"],
            "target_temp": primary["target_temp"],
            "duration": primary["duration"],
            "remain_time": primary["remain_time"],
            "humidity": primary["humidity"],
            "current_temp": primary["current_temp"],
            "units": per_unit,
        }
    return cur


def default_ace_dry_presets():
    """KX-Bridge _default_ace_dry_presets (temp in C, duration in seconds)."""
    h = 3600
    return {
        "pla": {"temp": 45, "duration_sec": 4 * h},
        "pla_plus": {"temp": 45, "duration_sec": 4 * h},
        "petg": {"temp": 50, "duration_sec": 4 * h},
        "tpu": {"temp": 55, "duration_sec": 4 * h},
        "abs_asa": {"temp": 45, "duration_sec": 8 * h},
        "pa_pc": {"temp": 55, "duration_sec": 12 * h},
        "custom_1": {"name": "Custom 1", "temp": 45, "duration_sec": 4 * h},
        "custom_2": {"name": "Custom 2", "temp": 45, "duration_sec": 4 * h},
        "custom_3": {"name": "Custom 3", "temp": 45, "duration_sec": 4 * h},
    }


def sanitize_ace_dry_presets(presets):
    """KX-Bridge _sanitize_ace_dry_presets: unknown keys dropped, temp clamped
    30..80 C, duration clamped 10 min..24 h, custom names kept."""
    out = default_ace_dry_presets()
    for key, preset in out.items():
        src = presets.get(key) if isinstance(presets, dict) else None
        if not isinstance(src, dict):
            continue
        try:
            t = int(src.get("temp", preset["temp"]))
        except (TypeError, ValueError):
            t = preset["temp"]
        try:
            d = int(src.get("duration_sec", preset["duration_sec"]))
        except (TypeError, ValueError):
            d = preset["duration_sec"]
        preset["temp"] = max(30, min(80, t))
        preset["duration_sec"] = max(10 * 60, min(24 * 3600, d))
        if key.startswith("custom_"):
            name = str(src.get("name", preset["name"])).strip()
            preset["name"] = name or preset["name"]
    return out


_MATERIAL_ALIASES = {
    "PLAPLUS": "PLA+", "PLA PLUS": "PLA+", "SILK PLA": "PLA SILK", "PLASILK": "PLA SILK",
    "TPE": "TPU", "PETG PLUS": "PETG+", "PA6": "PA", "PA12": "PA", "PA66": "PA",
}


def normalize_material(mat):
    """Upper-case, '-'/'_' -> space, known aliases mapped. KX-Bridge and
    Kobralink (normalizeMaterial) agree; KX-Bridge's extra PLA MATTE/MARBLE/
    WOOD aliases map to themselves, so they are no-ops."""
    m = str(mat).upper().strip().replace("-", " ").replace("_", " ")
    return _MATERIAL_ALIASES.get(m, m)


def material_family(mat):
    """PLA / PLA+ / PLA SILK -> "PLA"; PETG+ -> "PETG"; ... ("" for empty)."""
    if not mat:
        return ""
    m = normalize_material(mat)
    # Longer prefixes first so "PETG" is not swallowed by "PET".
    for fam in ("PETG", "PLA", "ABS", "ASA", "TPU", "PVA", "HIPS", "PA", "PC", "PET"):
        if m.startswith(fam):
            return fam
    return m


def parse_combined_rfid_type(raw_type, vendors):
    """Split a custom-RFID "VENDOR TYPE SERIAL" string (e.g. "GEEETECH PLA Bas")
    into (vendor, material_family). `vendors` is an iterable of known vendor
    names (from the filament library). ("", "") when the first token is not a
    known vendor, so a plain "PLA" is unaffected. KX-Bridge Issue #101."""
    tokens = str(raw_type).split()
    if len(tokens) < 2:
        return "", ""
    known = {v.lower(): v for v in vendors if v}
    vendor = known.get(tokens[0].lower())
    if not vendor:
        return "", ""
    family = material_family(" ".join(tokens[1:]))
    return (vendor, family) if family else ("", "")


def rfid_variant_tokens(raw_type):
    """Lower-case tokens after "VENDOR TYPE" ("GEEETECH PLA Bas" -> ["bas"])."""
    return [t.lower() for t in str(raw_type).split()[2:]]


def match_profile_by_vendor_family(profiles, vendor, family, variant_tokens=None):
    """First profile of (vendor, material family); several matches are ranked
    by how well variant_tokens fit the profile name (word prefix 2, substring
    1, first wins ties). {} when nothing matches."""
    matches = [
        p for p in profiles
        if p.get("vendor", "").lower() == vendor.lower() and material_family(p.get("type", "")) == family
    ]
    if not matches:
        return {}
    if len(matches) == 1 or not variant_tokens:
        return dict(matches[0])
    best, best_score = matches[0], -1
    for p in matches:
        name = p.get("name", "").lower()
        words = name.split()
        score = sum(2 if any(w.startswith(t) for w in words) else 1 if t in name else 0 for t in variant_tokens)
        if score > best_score:
            best, best_score = p, score
    return dict(best)


def select_loaded_slots_for_print(slots, mode, default_slot="auto"):
    """Usable slots, narrowed to `default_slot` (global index, int or numeric
    str) when that slot is usable. Returns (slots, warning | None); an empty
    or unparsable default falls back to all usable slots (Kobralink
    loadedSlotsForPrint, KX-Bridge _select_loaded_slots_for_print)."""
    usable = [s for s in slots if slot_usable_for_print(s, mode)]
    if default_slot == "auto":
        return usable, None
    try:
        want = int(default_slot)
    except (TypeError, ValueError):
        return usable, f"default slot {default_slot!r} is not a slot number, using auto"
    chosen = [s for s in usable if s["global_index"] == want]
    if chosen:
        return chosen, None
    return usable, f"default slot {want} is empty, falling back to auto"


def set_info_payload(box_id, local_slot, type, color):
    """`multiColorBox/setInfo` data to edit one slot (KX-Bridge
    handle_api_ams_set_slot / tools/probe_ams_setinfo.py variant A). Must be
    published on the web/printer topic; a slicer-topic publish is ignored by
    the printer. Type is upper-cased, color must be [r, g, b] 0-255."""
    if not (isinstance(color, (list, tuple)) and len(color) == 3 and all(
            isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in color)):
        raise ValueError("color must be [r, g, b] with integers 0-255")
    return {"multi_color_box": [{"id": int(box_id), "slots": [
        {"index": int(local_slot), "type": str(type).upper(), "color": list(color)}]}]}


def parse_multicolor_report(payload):
    """Normalise a `multiColorBox/report` payload (KX-Bridge _on_multicolor_box
    guards, Issue #100). Returns {"failed", "boxes", "head_tools_model"}.
    state "failed" carries `data` as a 2-element list, not a dict: failed is
    True and boxes is []. Any other non-dict data also gives boxes []."""
    if not isinstance(payload, dict):
        return {"failed": False, "boxes": [], "head_tools_model": None}
    if payload.get("state") == "failed":
        return {"failed": True, "boxes": [], "head_tools_model": None}
    data = payload.get("data")
    if not isinstance(data, dict):
        return {"failed": False, "boxes": [], "head_tools_model": None}
    model = data.get("head_tools_model")
    return {
        "failed": False,
        "boxes": [dict(b) for b in (data.get("multi_color_box") or [])],
        "head_tools_model": None if model is None else _num(model, None),
    }


def set_dry_payload(ace_ids, target_temp=None, duration_minutes=None):
    """`multiColorBox/setDry` data. Start: pass target_temp (30..80 C) and
    duration_minutes (10..1440); each box gets drying_status
    {status 1, target_temp, duration, remain_time == duration}, all in
    MINUTES, exactly as Kobralink and KX-Bridge send. Stop: omit both ->
    {status: 0}. Out-of-range values raise ValueError (Kobralink rejects;
    KX-Bridge clamps)."""
    def _int(v):
        return isinstance(v, int) and not isinstance(v, bool)
    if not ace_ids or not all(_int(i) and 0 <= i <= 3 for i in ace_ids):
        raise ValueError("ace_ids must be a non-empty list of ints 0-3")
    if target_temp is None and duration_minutes is None:
        status = {"status": 0}
    else:
        if not (_int(target_temp) and 30 <= target_temp <= 80):
            raise ValueError("target_temp must be an int 30-80")
        if not (_int(duration_minutes) and 10 <= duration_minutes <= 1440):
            raise ValueError("duration_minutes must be an int 10-1440")
        status = {"status": 1, "target_temp": target_temp, "duration": duration_minutes,
                  "remain_time": duration_minutes}
    return {"multi_color_box": [{"id": i, "drying_status": dict(status)} for i in ace_ids]}
