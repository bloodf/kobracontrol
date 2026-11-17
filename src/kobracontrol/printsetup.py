"""Kobra Control's own print dialog, opened when OrcaSlicer's Print is pressed for a Kobra X: which slot each
project filament prints from, and the print options. What the page shows is built here and what it answers is
checked here, so nothing the page sends is trusted as is. Free of the `orca` module."""

import base64
import xml.etree.ElementTree as ET
import zipfile

import ace
import kobra
from i18n import tr

OPTIONS = ("auto_leveling", "vibration_compensation", "flow_calibration", "timelapse")
FEATURES = {"auto_leveling": "auto_leveling_support", "vibration_compensation": "vibration_compensation_support",
            "flow_calibration": "flow_calibration_support", "timelapse": "camera_timelapse_support"}
UNTESTED = ("flow_calibration", "timelapse")   # sent only when the Kobra Control setting is on (jobs.job_task)
COLOUR_FAR = 0.25        # colour distance (0..1) above which a slot's colour "differs" from the filament's
THUMB_MAX = 512 * 1024   # bytes: a larger plate image is left out of the dialog
INFO_MAX = 8 * 1024 * 1024
MEMORY_MAX = 16          # printers whose last choices are remembered


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------- the sliced plate

def plate_summary(path, plate_index=1):
    """{"thumbnail": base64 PNG or "", "seconds": int, "grams": float, "metres": float, "filaments": {index: {"type", "colour",
    "grams"}}} from a sliced .3mf; empty values for a plain .gcode or anything unreadable. Never raises."""
    out = {"thumbnail": "", "seconds": 0, "grams": 0.0, "metres": 0.0, "filaments": {}}
    plate = int(plate_index) if str(plate_index).isdigit() and int(plate_index) > 0 else 1
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            png = "Metadata/plate_%d.png" % plate
            if png in names and z.getinfo(png).file_size <= THUMB_MAX:
                out["thumbnail"] = base64.b64encode(z.read(png)).decode("ascii")
            info = "Metadata/slice_info.config"
            if info in names and z.getinfo(info).file_size <= INFO_MAX:
                _read_slice_info(ET.fromstring(z.read(info)), plate, out)
    except (OSError, zipfile.BadZipFile, ET.ParseError, ValueError, KeyError, RecursionError):
        pass
    return out


def _num(text, kind=float):
    try:
        return kind(float(text))
    except (TypeError, ValueError):
        return kind(0)


def _read_slice_info(root, plate, out):
    for p in root.iter("plate"):
        meta = {m.get("key"): m.get("value") for m in p.iter("metadata")}
        if meta.get("index") != str(plate):
            continue
        out["seconds"] = max(0, _num(meta.get("prediction"), int))
        out["grams"] = max(0.0, _num(meta.get("weight")))
        for f in p.iter("filament"):
            index = _num(f.get("id"), int) - 1
            if index >= 0:
                out["filaments"][index] = {"type": str(f.get("type") or ""), "colour": str(f.get("color") or ""),
                                           "grams": max(0.0, _num(f.get("used_g")))}
                out["metres"] += max(0.0, _num(f.get("used_m")))
        return


def job_filaments(trays, described, plate):
    """The project filaments this print uses: [{"index", "colour", "type", "family", "grams"}]. OrcaSlicer's dialog chose a
    tray for each one it prints (described: its ams_mapping_info); with no tray chosen at all, the plate's own
    filament list (slice_info) is used."""
    wanted = [i for i, t in enumerate(trays) if t >= 0] or sorted(plate["filaments"])
    out = []
    for i in wanted:
        sliced = plate["filaments"].get(i, {})
        told = described[i] if i < len(described) else {}
        colour = hex6(told.get("colour")) or hex6(sliced.get("colour")) or "#FFFFFF"
        typ = str(told.get("type") or sliced.get("type") or "")
        out.append({"index": i, "colour": colour, "type": typ, "family": ace.material_family(typ),
                    "material": ace.normalize_material(typ) if typ else "",
                    "grams": round(sliced.get("grams", 0.0), 2)})
    return out


# ---------------------------------------------------------------------- matching

def hex6(text):
    """'#RRGGBB' from '#RRGGBB', 'RRGGBB' or 'RRGGBBAA'; '' when invalid."""
    rgba = ace._parse_hex(text)
    return "#%02X%02X%02X" % tuple(rgba[:3]) if rgba else ""


def colour_distance(a, b):
    """0 (same) .. 1 (black vs white) between two colours given as '#RRGGBB' or [r, g, b]."""
    def rgb(c):
        if isinstance(c, (list, tuple)) and len(c) >= 3:
            return [float(x) for x in c[:3]]
        parsed = ace._parse_hex(c)
        return [float(x) for x in parsed[:3]] if parsed else [255.0, 255.0, 255.0]
    x, y = rgb(a), rgb(b)
    return (sum((p - q) ** 2 for p, q in zip(x, y)) ** 0.5) / (3 * 255 ** 2) ** 0.5


def _cost(f, slot):
    """Lower is better: same material, then same family, then the nearest colour."""
    same = ace.normalize_material(f["type"]) == ace.normalize_material(slot["type"])
    family = ace.material_family(f["type"]) == ace.material_family(slot["type"])
    return colour_distance(f["colour"], slot["color"]) + (0 if same else 10 if family else 100)


def auto_match(filaments, slots, mode):
    """{filament index: tray}: globally best (filament, slot) pairs first, so an early filament cannot take a later
    one's exact match, and only slots of the same material family pair up; the rest share their best slot. -1 when no slot is
    usable."""
    usable = [s for s in slots if ace.slot_usable_for_print(s, mode)]
    if not usable:
        return {f["index"]: -1 for f in filaments}
    pairs = sorted((_cost(f, s), f["index"], ace.tray_id(s)) for f in filaments for s in usable
                   if same_family(f["type"], s["type"]))   # a slot of another material is never taken for its own
    out, taken = {}, set()
    for _, fi, tray in pairs:
        if fi not in out and tray not in taken:
            out[fi] = tray
            taken.add(tray)
    for f in filaments:
        if f["index"] not in out:
            out[f["index"]] = ace.tray_id(min(usable, key=lambda s: (_cost(f, s), ace.tray_id(s))))
    return out


def initial_trays(orca_trays, filaments, slots, mode):
    """OrcaSlicer's choice where it names a usable slot, the auto match elsewhere."""
    auto = auto_match(filaments, slots, mode)
    out = {}
    for f in filaments:
        i = f["index"]
        tray = orca_trays[i] if i < len(orca_trays) else -1
        slot = ace.slot_for_tray(tray, slots) if tray >= 0 else None
        out[i] = tray if slot and ace.slot_usable_for_print(slot, mode) else auto[i]
    return out


def same_material(a, b):
    """True when two material names are the same filament (PLA+ = PLA PLUS); "" matches anything."""
    return not a or not b or ace.normalize_material(a) == ace.normalize_material(b)


def same_family(a, b):
    return not a or not b or ace.material_family(a) == ace.material_family(b)


def check(filaments, slots, mode, trays):
    """(blocking, warnings, hints) for a choice, each [{"id", "kind", "f", "tray"}]:
    blocking (no print): "none" (no slot), "empty" (missing, empty or unusable slot), "material" (another material
    family: only the same filament can be chosen);
    warnings (need the user's "use anyway"): "variant" (same family, another kind, e.g. PLA in a PLA Silk slot);
    hints (shown only): "colour" (a clearly different colour)."""
    blocking, warnings, hints = [], [], []
    for f in filaments:
        i, tray = f["index"], trays.get(f["index"], -1)
        item = lambda kind: {"id": "%s:%d:%d" % (kind, i, tray), "kind": kind, "f": i, "tray": tray}
        slot = ace.slot_for_tray(tray, slots) if tray >= 0 else None
        if tray < 0:
            blocking.append(item("none"))
        elif slot is None or not ace.slot_usable_for_print(slot, mode):
            blocking.append(item("empty"))
        elif not same_family(f["type"], slot["type"]):
            blocking.append(item("material"))
        elif not same_material(f["type"], slot["type"]):
            warnings.append(item("variant"))
        elif colour_distance(f["colour"], slot["color"]) > COLOUR_FAR:
            hints.append(item("colour"))
    return blocking, warnings, hints


# ---------------------------------------------------------------------- options

def offered_options(defaults, features, orca_task, remembered):
    """[{"key", "on", "lock"}] in OPTIONS order. lock "unsupported": the printer reported no such feature;
    "setting": the Kobra Control setting keeps it off (auto-leveling turned off, or an untested option not opted
    in). A locked option is off and stays off. Otherwise the remembered choice, else OrcaSlicer's dialog's."""
    out = []
    for key in OPTIONS:
        lock = ""
        if (features or {}).get(FEATURES[key]) is False:
            lock = "unsupported"
        elif key == "auto_leveling" and defaults.get(key) is False or key in UNTESTED and defaults.get(key) is not True:
            lock = "setting"
        on = False if lock else bool(remembered[key]) if isinstance(remembered.get(key), bool) else bool(orca_task.get(key))
        out.append({"key": key, "on": on, "lock": lock})
    return out


def remembered_for(memory, printer):
    value = (memory or {}).get(printer)
    return value if isinstance(value, dict) else {}


def remember(memory, printer, options):
    """memory with this printer's options as its newest entry (at most MEMORY_MAX printers)."""
    kept = {k: v for k, v in (memory or {}).items() if k != printer}
    kept[printer] = {k: bool(v) for k, v in options.items() if k in OPTIONS}
    return dict(list(kept.items())[-MEMORY_MAX:])


def clean_memory(value):
    """The stored memory with anything malformed dropped (settings validation)."""
    if not isinstance(value, dict):
        return None
    out = {}
    for printer, opts in list(value.items())[-MEMORY_MAX:]:
        if isinstance(printer, str) and printer and isinstance(opts, dict):
            out[printer[:120]] = {k: v for k, v in opts.items() if k in OPTIONS and isinstance(v, bool)}
    return out


# ---------------------------------------------------------------------- the page

def spool_names(spools, bindings):
    """{global slot index: "Vendor Name"} for the slots linked to a Spoolman spool."""
    by_id = {s.get("id"): s for s in spools or []}
    out = {}
    for g, sid in (bindings or {}).items():
        s = by_id.get(sid)
        if s:
            out[g] = " ".join(x for x in (s.get("vendor"), s.get("name")) if x) or "#%s" % sid
    return out


def page_slots(data, names):
    """The slots as the dialog shows them."""
    return [{"tray": ace.tray_id(s), "global_index": s["global_index"], "box_id": s["box_id"], "index": s["index"],
             "type": s["type"], "family": ace.material_family(s["type"]),
             "material": ace.normalize_material(s["type"]) if s["type"] else "", "colour": hex6("%02X%02X%02X" % tuple(s["color"][:3])), "usable": bool(s.get("usable")),
             "spool": names.get(s["global_index"], "")} for s in data["slots"]]


def page_data(printer, job, filaments, data, names, trays, options, auto_feed, remember_on):
    return {"printer": printer, "job": job, "filaments": filaments, "slots": page_slots(data, names),
            "trays": {str(k): v for k, v in trays.items()}, "options": options, "auto_feed": auto_feed,
            "remember": bool(remember_on)}


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def refuse(blocking):
    """Raise for the first blocking problem of check()."""
    if not blocking:
        return
    b = blocking[0]
    if b["kind"] == "material":
        raise kobra.KobraError(tr("filament %d is another material than its slot holds; the print was not started") % (b["f"] + 1))
    raise kobra.KobraError(tr("filament %d has no usable slot; nothing was sent") % (b["f"] + 1))


def refuse_other_material(trays, filaments, slots, mode):
    """Raise when a project filament goes to a slot of another material family (trays[i]: its tray, -1 unused;
    filaments[i]: {"colour", "type"}). Checked before the upload and again right before print/start, with the print
    setup and without it."""
    fils = [{"index": i, "colour": (filaments[i] if i < len(filaments) else {}).get("colour") or "#FFFFFF",
             "type": (filaments[i] if i < len(filaments) else {}).get("type") or ""} for i, t in enumerate(trays) if t >= 0]
    blocking, _, _ = check(fils, slots, mode, dict(enumerate(trays)))
    refuse([b for b in blocking if b["kind"] == "material"])


def task_name(text, fallback):
    """The print's name from the dialog's field: printable characters, at most 120; the fallback when blank."""
    name = " ".join("".join(c for c in str(text or "") if c.isprintable()).split())[:120]
    return name or fallback


def read_answer(answer, filaments, slots, mode, trays, options, auto_feed):
    """The page's answer, checked against what the printer has now. Returns {"trays": {f: tray}, "task", "auto_feed",
    "remember" (None: not answered)}. Raises Cancelled, or KobraError when a slot is unusable or a material warning was not confirmed
    exactly as shown (another choice, or the slots changed meanwhile)."""
    if not isinstance(answer, dict) or answer.get("cancelled"):
        raise Cancelled()
    chosen = dict(trays)
    picked = answer.get("trays") if isinstance(answer.get("trays"), dict) else {}
    for f, tray in picked.items():
        if str(f).isdigit() and int(f) in chosen and _int(tray) is not None:
            chosen[int(f)] = tray
    blocking, warnings, _ = check(filaments, slots, mode, chosen)
    refuse(blocking)
    acked = answer.get("acknowledged")
    if warnings and (not isinstance(acked, list) or sorted(map(str, acked)) != sorted(w["id"] for w in warnings)):
        raise kobra.KobraError(tr("the material warnings were not confirmed for these slots; nothing was sent"))
    wanted = answer.get("options") if isinstance(answer.get("options"), dict) else {}
    task = {o["key"]: False if o["lock"] else bool(wanted.get(o["key"], o["on"])) for o in options}
    feed = None if auto_feed is None else bool(answer.get("auto_feed", auto_feed))
    return {"trays": chosen, "task": task, "auto_feed": feed, "name": answer.get("name") if isinstance(answer.get("name"), str) else None,
            "remember": answer["remember"] if isinstance(answer.get("remember"), bool) else None}


def tray_list(trays, filaments, size):
    """(tray ids, [{"colour", "type"}]) indexed by project filament, as jobs.print_job takes them."""
    ids = [-1] * max([size] + [i + 1 for i in trays])
    fils = [{"colour": "#FFFFFF", "type": ""} for _ in ids]
    for f in filaments:
        ids[f["index"]] = trays.get(f["index"], -1)
        fils[f["index"]] = {"colour": f["colour"], "type": f["type"]}
    return ids, fils
