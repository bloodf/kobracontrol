"""Spoolman integration, one spool per ACE / print-head slot (`ace` `global_index`). Free of the `orca` module.

Transport: Spoolman's REST API at the configured URL (the Kobra X has no Moonraker to proxy it).

Binding slot -> spool: the spool's `location` is "<printer name> S<n>" (n = global_index + 1), so the binding
lives in Spoolman and every client sees it (the same idea as the U1 Control plugin's "<printer> T<n>").
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

MAX_SLOTS = 32                  # slot numbers above this in a location are not ours
LOCATION_MAX = 64
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # LAN only: never via a proxy


class SpoolmanError(RuntimeError):
    pass


class Spoolman:
    def __init__(self, url="", timeout=5.0, opener=None):
        self.url = (url or "").strip().rstrip("/")
        if self.url and "://" not in self.url:
            self.url = "http://" + self.url
        self.timeout = timeout
        self._open = (opener or _NO_PROXY).open

    def connect(self):
        if not self.url:
            raise SpoolmanError("Spoolman not configured: set its URL in the Kobra Control settings")
        self.call("GET", "/v1/health")
        return {"via": "direct"}

    def call(self, method, path, query=None, body=None):
        url = self.url + "/api" + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self._open(req, timeout=self.timeout) as resp:
                raw = resp.read(32 * 1024 * 1024)
        except urllib.error.HTTPError as e:
            e.close()
            raise SpoolmanError("Spoolman said HTTP %d" % e.code) from None
        except (OSError, ValueError) as e:
            raise SpoolmanError("can't reach Spoolman at %s (%s)" % (self.url, getattr(e, "reason", e))) from None
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            raise SpoolmanError("Spoolman sent an answer that is not JSON") from None

    # ------------------------------------------------------------------ api

    def spools(self):
        return self.call("GET", "/v1/spool", {"allow_archived": "false", "sort": "last_used:desc"}) or []

    def set_location(self, spool_id, location):
        return self.call("PATCH", "/v1/spool/%d" % int(spool_id), body={"location": location[:LOCATION_MAX]})

    def use_weight(self, spool_id, grams):
        return self.call("PUT", "/v1/spool/%d/use" % int(spool_id), body={"use_weight": round(float(grams), 2)})


# ---------------------------------------------------------------------- colours and materials

def norm_colour(value):
    """'#ff0000', 'FF0000FF', 'ff0000' -> '#FF0000'; anything else -> None."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", str(value or "").strip())
    return "#" + m.group(1).upper() if m else None


def colour_distance(a, b):
    """Weighted RGB distance ('redmean'); unknown colours are far apart."""
    a, b = norm_colour(a), norm_colour(b)
    if not a or not b:
        return 765.0
    r1, g1, b1 = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    r2, g2, b2 = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    rm = (r1 + r2) / 2
    return ((2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2) ** 0.5


def material_family(ftype):
    """'PLA-CF' / 'PLA Matte' / 'PLA+' -> 'PLA'."""
    m = re.match(r"[A-Za-z]+", (ftype or "").strip())
    return m.group(0).upper() if m else ""


def slot_colour(slot):
    """'#RRGGBB' of an `ace` slot (its `color` is [r, g, b]; a `colour` hex string is taken as is), or None."""
    if norm_colour(slot.get("colour")):
        return norm_colour(slot["colour"])
    rgb = slot.get("color")
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in rgb[:3]):
        return "#%02X%02X%02X" % tuple(max(0, min(255, v)) for v in rgb[:3])
    return None


# ---------------------------------------------------------------------- matching

def _weight(v):
    """A positive weight in grams, or None (Spoolman leaves these empty when unknown)."""
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def spool_view(spool):
    """Flatten a Spoolman spool for the UI and for matching."""
    f = spool.get("filament") or {}
    colours = f.get("multi_color_hexes")
    colours = [norm_colour(c) for c in colours.split(",")] if isinstance(colours, str) else []
    return {
        "id": spool.get("id"),
        "filament_id": f.get("id"),
        "name": f.get("name") or "",
        "vendor": (f.get("vendor") or {}).get("name") or "Generic",
        "material": f.get("material") or "",
        "colour": norm_colour(f.get("color_hex")) or (colours[0] if colours else None),
        "colours": [c for c in colours if c],
        "remaining": spool.get("remaining_weight"),
        "initial": _weight(spool.get("initial_weight")) or _weight(f.get("weight")),
        "location": spool.get("location") or "",
        "last_used": spool.get("last_used") or "",
        "archived": bool(spool.get("archived")),
        "extruder_temp": f.get("settings_extruder_temp"),
        "bed_temp": f.get("settings_bed_temp"),
    }


def slot_fields(spool):
    """What to write to a slot (the `slot_set` command's type and colour) for a spool view."""
    return {"type": spool["material"], "colour": spool["colour"] or "#FFFFFF"}


def match_score(slot, spool):
    """Lower is better; None = incompatible material. slot: an `ace` slot dict."""
    if not slot.get("type") or not spool.get("material"):
        return None
    if material_family(slot["type"]) != material_family(spool["material"]):
        return None
    score = colour_distance(slot_colour(slot), spool.get("colour"))
    if slot["type"].upper() != spool["material"].upper():
        score += 50
    return score


def best_spool(slot, spools, exclude=(), max_score=120.0):
    """Closest compatible spool for a slot, or None when nothing is close enough."""
    ranked = sorted((s for s in ((match_score(slot, sp), sp) for sp in spools if sp["id"] not in exclude)
                     if s[0] is not None), key=lambda x: x[0])
    return ranked[0][1] if ranked and ranked[0][0] <= max_score else None


def _location_key(text):
    return " ".join(str(text or "").split()).lower()


def location_for(printer_name, slot):
    """Spoolman location that binds slot `slot` (0-based) of this printer: "<printer name> S<n>"."""
    return ("%s S%d" % (" ".join(str(printer_name or "").split()), slot + 1))[:LOCATION_MAX]


def location_score(location, printer_name, slot):
    """2 when a Spoolman location is exactly "<printer name> S<n>" for 0-based `slot`, else 0."""
    return 2 if _location_key(location) == _location_key(location_for(printer_name, slot)) else 0


def bindings_from_locations(spools, printer_name):
    """{slot: spool_id} from spool locations like "Anycubic Kobra X S2" (1-based in the UI). Archived spools
    never bind; between spools with the same location the one used last wins."""
    key = _location_key(printer_name)
    found = {}
    for sp in spools:
        if sp.get("archived"):
            continue
        m = re.fullmatch(r"(.*)\s+s(\d+)", _location_key(sp.get("location")))
        if not m or m.group(1) != key or not 1 <= int(m.group(2)) <= MAX_SLOTS:
            continue
        found.setdefault(int(m.group(2)) - 1, []).append(sp)
    return {slot: max(sps, key=lambda sp: str(sp.get("last_used") or ""))["id"] for slot, sps in found.items()}


def slot_changed(old, new):
    """The slot's filament data changed (loaded spool swapped, colour or type edited, emptied)."""
    keys = ("type", "color", "colour", "status")
    return any((old or {}).get(k) != (new or {}).get(k) for k in keys)
