"""The purge-and-bed-wait add-on (opt-in, off by default, not yet tried on a printer): a copy of the sliced G-code
gets (a) a purge after each tool change (`T0`..`T15`, an ACE filament load) during the print and (b) an `M190` bed
wait before the first layer when the file has none. The original file is never changed. Free of the `orca` module.

The purge after `T<n>`: lift Z, travel to its own lane in the purge area (a strip MARGIN inside the chosen corner of
the file's `; printable_area`), lower Z back, extrude `length` mm while moving LANE_LEN mm along the lane, lift,
travel back to the last X/Y and lower again. Every purge gets the next lane (LANE_STEP apart, then the next row
along the edge), so purges never land on one another; a file with more tool changes than lanes is refused. The lift
is LIFT plus the height the purged line can reach. Purges happen only between the first `;LAYER_CHANGE` and the end
G-code (`; MACHINE_END_GCODE_START` or `; EXECUTABLE_BLOCK_END`), so never before the start G-code's heat-up waits or
in the end G-code. Positioning must be absolute (G90) at a tool change; the extrusion mode is set to relative (M83)
for the purge (again after each G90, which also sets absolute E on Marlin-style firmware) and restored exactly afterwards (M82 with `G92 E<last E>`, or M83). The bed wait uses the
first-layer bed temperature the file itself sets before its first layer (`M140 S<t>`, or the Kobra X start
macro's `G9111 bedTemp=<t>`)."""

import math
import re

from i18n import tr

CORNERS = ("front_left", "front_right", "back_left", "back_right")
MARGIN = 5.0          # mm inside the printable area
BED_MAX = 2000.0      # mm: a coordinate beyond this is not a bed
LINE_MAX = 1 << 20    # bytes read per line at most (a file without line ends is not read whole)
LIFT = 2.0            # mm Z lift for the travel to the purge lane and back, before the purged line's own height
LANE_LEN = 30.0       # mm: each purge is extruded while moving this far along its lane
LANE_STEP = 3.0       # mm between lanes
STRIP = 15.0          # mm: depth of the purge strip along the bed edge (lanes per row = STRIP / LANE_STEP)
ROW_GAP = 5.0         # mm between rows of lanes along the edge
FILAMENT_AREA = math.pi * 1.75 ** 2 / 4   # mm^2 of 1.75 mm filament
BEAD_WIDTH = 1.0      # mm: the purged line is taken to be at least this wide when its height is estimated
TRAVEL_F = 12000      # mm/min, the profile's own travel after a tool change
LIMITS = {"length": (1.0, 50.0), "speed": (1.0, 10.0)}   # 10 mm/s of 1.75 mm filament is ~24 mm^3/s   # mm, mm/s
DEFAULTS = {"length": 15.0, "speed": 5.0, "corner": "front_left"}
TOOLS = 16            # T0..T15: the ACE slots (4 units x 4); T255 and friends are not filament loads
START, END = "; >>> kobracontrol purge add-on", "; <<< kobracontrol purge add-on"
FIRST_LAYER = b";LAYER_CHANGE"
END_GCODE = (b"; MACHINE_END_GCODE_START", b"; EXECUTABLE_BLOCK_END")

_TOOL = re.compile(rb"^T(\d+)\s*(;.*)?$")
_MOVE = re.compile(rb"^G0*[0-3](?![0-9.])")   # G0..G3, also written G01 or with no space before the first word
_E = re.compile(rb"(?<![A-Z])E(-?\d+(?:\.\d*)?|-?\.\d+)")
_AREA = re.compile(rb"^;\s*printable_area\s*=\s*(.+)$")
_BED = re.compile(rb"^(?:M140|M190)\b[^;]*?\bS(\d+(?:\.\d+)?)")
_G9111 = re.compile(rb"^G9111\b[^;]*?\bbedTemp=(\d+(?:\.\d+)?)", re.I)
_WORD = re.compile(rb"(?<![A-Z])([XY])(-?\d+(?:\.\d*)?|-?\.\d+)")


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


def lanes(bed):
    """How many purge lanes fit along one edge of the bed."""
    xmin, _, xmax, _ = bed
    rows = int((xmax - xmin - 2 * MARGIN + ROW_GAP) // (LANE_LEN + ROW_GAP))
    return max(0, rows) * int(STRIP // LANE_STEP)


def lane(opts, bed, index):
    """((x0, y), (x1, y)) of purge number `index` (0-based): rows run inward from the chosen corner along the front or
    back edge, lanes step inward from the edge."""
    xmin, ymin, xmax, ymax = bed
    per_row = int(STRIP // LANE_STEP)
    row, k = divmod(index, per_row)
    sx = 1 if opts["corner"].endswith("left") else -1
    sy = 1 if opts["corner"].startswith("front") else -1
    x0 = (xmin + MARGIN if sx > 0 else xmax - MARGIN) + sx * row * (LANE_LEN + ROW_GAP)
    y = (ymin + MARGIN if sy > 0 else ymax - MARGIN) + sy * k * LANE_STEP
    return (x0, y), (x0 + sx * LANE_LEN, y)


def purge_point(opts, bed):
    return lane(opts, bed, 0)[0]


def lift(opts):
    """LIFT plus the height the purged line can reach (its volume over LANE_LEN x BEAD_WIDTH)."""
    return LIFT + opts["length"] * FILAMENT_AREA / (LANE_LEN * BEAD_WIDTH)


def _num(value):
    return value if isinstance(value, str) else ("%.3f" % value).rstrip("0").rstrip(".")


def purge_lines(opts, bed, back, index=0, restore=("M83",)):
    """The lines inserted after a tool change. back: (x, y) to return to, None when no X/Y is known yet (no return
    move), or two strings (the Settings preview). index: which purge of the file (its lane). restore: the lines that
    put the extrusion mode back as it was."""
    (x0, y), (x1, _) = lane(opts, bed, index)
    up = _num(lift(opts))
    # the move along the lane takes as long as the extrusion at the chosen speed: feed rate in mm/min of XY
    feed = max(1, round(LANE_LEN / (opts["length"] / opts["speed"]) * 60))
    lines = [START, "M83", "G91", "G1 Z%s F1200" % up, "G90", "G1 X%s Y%s F%d" % (_num(x0), _num(y), TRAVEL_F),
             "G91", "G1 Z-%s F1200" % up, "G90", "M83", "G1 X%s Y%s E%s F%d" % (_num(x1), _num(y), _num(opts["length"]), feed),
             "G91", "G1 Z%s F1200" % up, "G90"]
    if back is not None:
        lines.append("G1 X%s Y%s F%d" % (_num(back[0]), _num(back[1]), TRAVEL_F))
    return lines + ["G91", "G1 Z-%s F1200" % up, "G90"] + list(restore) + [END]


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
    absolute_xy, relative_e, last_e, xy, purges, waited = True, False, 0.0, [None, None], 0, False
    printing = ended = False   # between the first layer and the end G-code: the only place a purge goes
    capacity = lanes(info["bed"])
    for raw in _lines(lines):
        line = raw.strip()
        code = line.split(b";", 1)[0].strip().upper()
        if line.startswith(FIRST_LAYER) and not printing:
            printing = True
            if need_wait:
                _emit(write, bed_wait_lines(info["bed_temp"]))
                waited = True
        if line.startswith(END_GCODE):
            ended = True
        write(raw)
        if code in (b"G90", b"G91"):
            absolute_xy = code == b"G90"
        elif code in (b"M82", b"M83"):
            relative_e = code == b"M83"
        elif code[:4] == b"G92 ":
            m = _E.search(code)
            last_e = float(m.group(1)) if m else last_e
        elif _MOVE.match(code):
            if absolute_xy:
                for axis, value in _WORD.findall(code):
                    xy[0 if axis == b"X" else 1] = float(value)
            m = _E.search(code)
            if m:
                last_e = float(m.group(1)) if not relative_e else last_e + float(m.group(1))
        else:
            tool = _TOOL.match(line)
            if not tool or int(tool.group(1)) >= TOOLS or not printing or ended:
                continue
            if not absolute_xy:
                raise PurgeError(tr("the purge add-on needs absolute moves (G90) at each tool change; nothing was sent"))
            if purges >= capacity:
                raise PurgeError(tr("the purge add-on has room for %d purges on this bed and the file changes "
                                    "filament more often; nothing was sent") % capacity)
            if not raw.endswith(b"\n"):
                write(b"\n")
            restore = ("M83",) if relative_e else ("M82", "G92 E%s" % _num(last_e))
            _emit(write, purge_lines(opts, info["bed"], tuple(xy) if None not in xy else None, purges, restore))
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
