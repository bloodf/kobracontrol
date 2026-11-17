"""The purge-and-bed-wait add-on (opt-in, off by default): a copy of the sliced G-code gets (a) a purge after each
tool change (`T<n>`, an ACE filament load) and (b) an `M190` bed wait before the first layer when the file has
none. The original file is never changed. Free of the `orca` module.

The purge after `T<n>`: lift Z by LIFT (relative), travel to a point MARGIN inside a corner of the bed (the file's
`; printable_area`), extrude `length` mm at `speed` mm/s, travel back to the last X/Y, lower Z by LIFT. It needs
absolute positioning (G90) and relative extrusion (M83, the Kobra X profile's own setting) at the tool change, and
refuses the file otherwise: nothing is sent. The bed wait uses the first-layer bed temperature the file itself
sets before its first layer (`M140 S<t>`, or the Kobra X start macro's `G9111 bedTemp=<t>`)."""

import math
import re

from i18n import tr

CORNERS = ("front_left", "front_right", "back_left", "back_right")
MARGIN = 5.0          # mm inside the printable area
BED_MAX = 2000.0      # mm: a coordinate beyond this is not a bed
LINE_MAX = 1 << 20    # bytes read per line at most (a file without line ends is not read whole)
LIFT = 2.0            # mm Z lift for the travel to the purge point and back
TRAVEL_F = 12000      # mm/min, the profile's own travel after a tool change
LIMITS = {"length": (1.0, 100.0), "speed": (1.0, 20.0)}   # mm, mm/s
DEFAULTS = {"length": 30.0, "speed": 5.0, "corner": "front_left"}
START, END = "; >>> kobracontrol purge add-on", "; <<< kobracontrol purge add-on"
FIRST_LAYER = b";LAYER_CHANGE"

_TOOL = re.compile(rb"^T(\d+)\s*(;.*)?$")
_AREA = re.compile(rb"^;\s*printable_area\s*=\s*(.+)$")
_BED = re.compile(rb"^(?:M140|M190)\b[^;]*?\bS(\d+(?:\.\d+)?)")
_G9111 = re.compile(rb"^G9111\b[^;]*?\bbedTemp=(\d+(?:\.\d+)?)", re.I)
_WORD = re.compile(rb"\b([XY])(-?\d+(?:\.\d*)?|-?\.\d+)")


class PurgeError(ValueError):
    pass


def options(cfg):
    """{"length", "speed", "corner"} from settings, clamped to LIMITS."""
    out = {}
    for key, (low, high) in LIMITS.items():
        value = cfg.get("purge_" + key, DEFAULTS[key])
        out[key] = min(high, max(low, float(value))) if isinstance(value, (int, float)) and not isinstance(value, bool) else DEFAULTS[key]
    corner = cfg.get("purge_corner")
    out["corner"] = corner if corner in CORNERS else DEFAULTS["corner"]
    return out


def parse_area(text):
    """(xmin, ymin, xmax, ymax) from "0x0,260x0,260x260,0x260", None when unreadable."""
    try:
        points = [tuple(float(v) for v in p.strip().split("x")) for p in str(text).split(",") if p.strip()]
        xs, ys = [p[0] for p in points], [p[1] for p in points]
    except (ValueError, IndexError):
        return None
    if not all(math.isfinite(v) and abs(v) <= BED_MAX for v in xs + ys):
        return None
    if len(points) < 3 or max(xs) - min(xs) < 4 * MARGIN or max(ys) - min(ys) < 4 * MARGIN:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def purge_point(opts, bed):
    xmin, ymin, xmax, ymax = bed
    x = xmin + MARGIN if opts["corner"].endswith("left") else xmax - MARGIN
    y = ymin + MARGIN if opts["corner"].startswith("front") else ymax - MARGIN
    return x, y


def _num(value):
    return value if isinstance(value, str) else ("%.3f" % value).rstrip("0").rstrip(".")


def purge_lines(opts, bed, back):
    """The lines inserted after a tool change. back: (x, y) to return to, None when no X/Y is known yet (no return
    move), or two strings (the Settings preview)."""
    x, y = purge_point(opts, bed)
    lines = [START, "G91", "G1 Z%s F1200" % _num(LIFT), "G90", "G1 X%s Y%s F%d" % (_num(x), _num(y), TRAVEL_F),
             "G1 E%s F%d" % (_num(opts["length"]), round(opts["speed"] * 60))]
    if back is not None:
        lines.append("G1 X%s Y%s F%d" % (_num(back[0]), _num(back[1]), TRAVEL_F))
    return lines + ["G91", "G1 Z-%s F1200" % _num(LIFT), "G90", END]


def bed_wait_lines(temp):
    return [START, "M190 S%s ; wait for the first-layer bed temperature" % _num(temp), END]


def preview(opts, bed, temp_text):
    """What Settings shows: the bed wait, then one purge."""
    return {"bed_wait": bed_wait_lines(temp_text), "purge": purge_lines(opts, bed, ("<X>", "<Y>")),
            "point": [_num(v) for v in purge_point(opts, bed)]}


def scan(lines):
    """What the transform needs from the whole file: {"bed", "bed_temp", "has_m190"}. The bed comes from the
    configuration block Orca writes at the end; the temperature and an existing M190 only count before the first
    layer."""
    info = {"bed": None, "bed_temp": None, "has_m190": False}
    first_layer = False
    for raw in _lines(lines):
        line = raw.strip()
        if line.startswith(FIRST_LAYER):
            first_layer = True
        m = _AREA.match(line)
        if m:
            info["bed"] = parse_area(m.group(1).decode("ascii", "replace"))
        if first_layer:
            continue
        if line.startswith(b"M190"):
            info["has_m190"] = True
        m = _BED.match(line) or _G9111.match(line)
        if m and info["bed_temp"] is None and float(m.group(1)) > 0:
            info["bed_temp"] = float(m.group(1))
    return info


def transform(lines, write, opts, info):
    """Write `lines` (bytes, with their line ends) through `write`, with the add-on's lines inserted. Returns
    {"purges": n, "bed_wait": bool}. Raises PurgeError (and the caller sends nothing) when the file can't take them."""
    if info["bed"] is None:
        raise PurgeError(tr("the purge add-on found no bed size (printable_area) in the sliced file; nothing was sent"))
    need_wait = not info["has_m190"]
    if need_wait and info["bed_temp"] is None:
        raise PurgeError(tr("the purge add-on found no first-layer bed temperature in the sliced file; nothing was sent"))
    absolute_xy, relative_e, xy, purges, waited = True, False, [None, None], 0, False
    for raw in _lines(lines):
        line = raw.strip()
        code = line.split(b";", 1)[0].strip().upper()
        if need_wait and not waited and line.startswith(FIRST_LAYER):
            _emit(write, bed_wait_lines(info["bed_temp"]))
            waited = True
        write(raw)
        if code in (b"G90", b"G91"):
            absolute_xy = code == b"G90"
        elif code in (b"M82", b"M83"):
            relative_e = code == b"M83"
        elif code[:3] in (b"G0 ", b"G1 ") and absolute_xy:
            for axis, value in _WORD.findall(code):
                xy[0 if axis == b"X" else 1] = float(value)
        elif _TOOL.match(line):
            if not absolute_xy or not relative_e:
                raise PurgeError(tr("the purge add-on needs absolute moves (G90) and relative extrusion (M83) at "
                                    "each tool change; nothing was sent"))
            if not raw.endswith(b"\n"):
                write(b"\n")
            _emit(write, purge_lines(opts, info["bed"], tuple(xy) if None not in xy else None))
            purges += 1
    return {"purges": purges, "bed_wait": waited}


def _lines(source):
    """The lines of a binary file, LINE_MAX bytes at most each (an iterable of lines passes through)."""
    if not hasattr(source, "readline"):
        yield from source
        return
    while True:
        line = source.readline(LINE_MAX)
        if not line:
            return
        yield line


def _emit(write, lines):
    write(("\n".join(lines) + "\n").encode("ascii"))
