"""The Device tab speaks Bambu JSON: this module translates a `kobra.State.view()` (plus the `ace` slots) to the
`push_status` message OrcaSlicer's DeviceManager parses, and the Device tab's commands to kobracontrol commands.
Pure functions, free of the `orca` module.

Sources (OrcaSlicer v2.5.0): src/slic3r/Utils/MoonrakerPrinterAgent.cpp (MRA), the reference non-Bambu agent,
and src/slic3r/GUI/DeviceManager.cpp (DM), the parser. Line numbers are those of that tag.

parse_command(json_str) returns {"kind", ..., "seq"}; kinds and their fields:
    get_version, get_access_code, pushall              read-only, answered by the agent
    pause, resume, stop
    set_temp      nozzle and/or bed (deg C, as sent; the service clamps)
    set_fan       pct 0-100
    set_speed     mode 1-3 (the Kobra print_speed_mode: 1 quiet, 2 standard, 3 sport, as Kobralink's
                  controls-card.tsx; Bambu spd_lvl uses the same numbers, its 4 = ludicrous is unsupported)
    set_light     on
    home          axes "xyz" or "z"
    move          axis "x"|"y"|"z", distance (mm, signed)
    slot_set      tray (Bambu tray id = ams_id * 4 + slot_id), type, colour "#RRGGBB"
    slot_feed     tray;  slot_retract (unloads whatever is loaded)
    noop          a G90 alone: moves here are always relative, so absolute mode changes nothing
    unsupported   everything else, answered with UNSUPPORTED (-7010)
    invalid       not a JSON object, or a command that is not a string
G-code commands carry "gcode": True: the agent answers them with gcode_reply(), as MRA:1238-1248 does.
"""

import json
import re
import time

UNSUPPORTED = -7010            # IPrinterAgent: "command not supported"
HAS_SDCARD_NORMAL = 1          # DevStorage.h SdcardState
CHAMBER_LIGHT = "chamber_light"

# Material -> OrcaFilamentLibrary family, from MRA:794-841 map_filament_type_to_generic_id. The id itself is
# looked up from the system preset "Generic <family> @System" (filament_id), never hard-coded (MRA:847-851).
FILAMENT_FAMILIES = {
    "PLA": "PLA", "PLA-CF": "PLA-CF", "PLA SILK": "PLA Silk", "PLA-SILK": "PLA Silk",
    "PLA HIGH SPEED": "PLA High Speed", "PLA-HS": "PLA High Speed", "PLA HS": "PLA High Speed",
    "ABS": "ABS", "ASA": "ASA", "PETG": "PETG", "PET": "PETG", "PCTG": "PCTG",
    "PA": "PA", "NYLON": "PA", "PA-CF": "PA-CF", "PPA": "PPA-CF", "PPA-CF": "PPA-CF", "PPA-GF": "PPA-GF",
    "PC": "PC", "PE": "PE", "PP": "PP", "PVA": "PVA", "HIPS": "HIPS", "BVOH": "BVOH", "TPU": "TPU",
    "EVA": "EVA", "PHA": "PHA", "COPE": "CoPE", "SBS": "SBS",
}

# view["state"] -> gcode_state (DM:3558 set_print_state). As MRA:133-150: cancelled and error are FAILED.
# "busy" (an unknown printer state) is RUNNING, so OrcaSlicer never starts a print on a busy printer.
GCODE_STATE = {"idle": "IDLE", "printing": "RUNNING", "busy": "RUNNING", "paused": "PAUSE", "finished": "FINISH",
               "cancelled": "FAILED", "error": "FAILED", "offline": "IDLE"}
# Kobra job phase (print/report action start, live capture fw 2.0.2.8) -> Bambu stage id, shown by the Device
# tab as text (DM:178-260 get_stage_string). Phases with no matching text (checking, cooling, z offset
# calibration) stay 0, "Printing".
STAGES = {"auto_leveling": 1, "hotbed_heating": 2, "frequency_sweeping": 3, "nozzle_heating": 7,
          "nozzle_purging": 14, "nozzle_wiping": 14, "ace_filament_unfeeding": 22, "ace_filament_feeding": 24}
PRINT_STAGE = {"printing": 1, "paused": 2, "finished": 3, "error": 4}   # MRA:2146-2158


def generic_preset_name(material):
    """'Generic <family> @System' for a slot's material, or None when the family is unknown."""
    family = FILAMENT_FAMILIES.get(" ".join(str(material or "").split()).upper())
    return "Generic %s @System" % family if family else None


def _hex(color):
    r, g, b = (max(0, min(255, int(c))) for c in (list(color) + [255, 255, 255])[:3])
    return "%02X%02X%02XFF" % (r, g, b)   # RRGGBBAA, as MRA normalize_color_value


def ams_block(slots, filament_id=None):
    """The `ams` object DevFilaSystemParser::ParseV1_0 reads (MRA:608-701 build_ams_payload): one unit per
    `box_pos` ("info" 0002 = AMS lite, as MRA), trays by slot `index`; bits as upper-case hex strings."""
    units, ams_bits, tray_bits, remain = {}, 0, 0, False
    for slot in sorted(slots, key=lambda s: (s["box_pos"], s["index"])):
        pos, index = slot["box_pos"], slot["index"]
        if index > 3:
            continue
        ams_bits |= 1 << pos
        tray = {"id": str(index), "tag_uid": "0000000000000000"}
        if slot["status"] == 5:
            tray_bits |= 1 << (pos * 4 + index)
            material = slot["type"] or ""
            preset = generic_preset_name(material)
            tray.update(tray_type=material, tray_color=_hex(slot["color"]),
                        tray_info_idx=(filament_id(preset) if filament_id and preset else None) or "")
            tray["cols"], tray["ctype"] = [tray["tray_color"]], 1
            # DevFilaSystem.cpp:783-789: "remain" is the spool's percent left, -1 unknown (ACE consumables_percent)
            percent = slot.get("percent")
            tray["remain"] = int(max(0, min(100, percent))) if isinstance(percent, (int, float)) else -1
            remain = remain or tray["remain"] >= 0
        else:   # MRA:681-686: an empty slot
            tray.update(tray_info_idx="", tray_type="", tray_color="00000000", tray_slot_placeholder="1")
        units.setdefault(pos, []).append(tray)
    return {"ams": [{"id": str(pos), "info": "0002", "tray": trays} for pos, trays in sorted(units.items())],
            "ams_exist_bits": "%X" % ams_bits, "tray_exist_bits": "%X" % tray_bits,
            "calibrate_remain_flag": remain}   # DevFilaSystem.cpp:450: the Device tab shows "remain" only when set


def push_status(view, slots, mode, nozzle_max=320, bed_max=120, filament_id=None):
    """{"print": {...}} for on_local_message_fn. view: State.view(); slots: ace.aggregate_slots(...)[0];
    filament_id(preset name) -> the filament_id of that system preset, or None. `mode` is kept for callers
    that want it in logs; trays are already numbered by box_pos (ace.tray_id)."""
    state = view.get("state", "offline")
    stage = STAGES.get(view.get("kobra_state"), 0) if state in ("printing", "paused") else None
    storage = bool(view.get("connected"))   # the Kobra X always has its internal storage while it answers
    p = {
        "command": "push_status", "msg": 0, "support_mqtt_alive": True,           # MRA:2134-2136
        # A print still in its preparation phase (heating, levelling, ...) is PREPARE, which DM:2549-2556
        # is_in_printing_status() counts as printing, so OrcaSlicer still refuses a new print.
        # A filament change mid-print (layer > 0) is still RUNNING.
        "gcode_state": "PREPARE" if view.get("preparing") and not view.get("layer") else GCODE_STATE.get(state, "RUNNING"),
        "mc_print_stage": PRINT_STAGE.get(state, 0),
        # DM:3712-3727: stg (the stage list; empty means no stage text) and stg_cur (the current stage)
        "stg": [stage] if stage is not None else [], "stg_cur": stage or 0,
        "mc_print_error_code": 0, "print_error": 0,   # MRA:2160-2164: numeric HMS codes only; 0 = no dialog
        # The print dialog refuses LAN printing without storage: DevStorage::ParseV1_0 reads "sdcard", then
        # DM parse_home_flag (DM:1195) reads bits 8-9 of home_flag; both must say present (MRA:2167-2184).
        "sdcard": storage, "home_flag": (HAS_SDCARD_NORMAL if storage else 0) << 8,
        "support_send_to_sd": True,                                                # MRA:2190, DM:3251
        # MRA:2191-2194; the printer's info/report features say whether it can level (no guess when absent)
        "support_bed_leveling": 0 if (view.get("features") or {}).get("auto_leveling_support") is False else 1,
        "nozzle_temp_range": [0, nozzle_max], "bed_temp_range": [0, bed_max],      # MRA:2187, DM:3213
        "nozzle_temper": view.get("nozzle_temp", 0), "nozzle_target_temper": view.get("nozzle_target", 0),
        "bed_temper": view.get("bed_temp", 0), "bed_target_temper": view.get("bed_target", 0),
        # DevFan::ParseV1_0: fan_gear low byte = part cooling fan 0-255 (MRA:2227-2246)
        "fan_gear": int(max(0, min(100, view.get("fan_pct", 0))) * 255 / 100 + 0.5),
        "subtask_name": view.get("filename", ""), "gcode_file": view.get("filename", ""),   # DM:3569, DM:3610
        "mc_percent": int(round(max(0, min(100, view.get("progress", 0))))),               # DM:3431
        "mc_remaining_time": int(max(0, view.get("remaining_s", 0)) // 60),               # DM:3449, minutes
        "layer_num": int(view.get("layer", 0)), "total_layer_num": int(view.get("total_layers", 0)),  # DM:3578
        "spd_lvl": int(view.get("speed_mode")) if view.get("speed_mode") in (1, 2, 3) else 2,  # DevPrintOptions
        "lights_report": [{"node": CHAMBER_LIGHT, "mode": "on" if view.get("light_on") else "off"}],  # DM:3783
        "ipcam": {"ipcam_dev": "1" if view.get("camera_url") else "0"},                             # DM:3923
        "ams": ams_block(slots, filament_id),
    }
    return {"print": p, "t_utc": int(time.time() * 1000)}


def version_reply(firmware, product):
    """MRA:1535-1550 send_version_info."""
    return {"info": {"command": "get_version", "result": "success",
                     "module": [{"name": "ota", "sw_ver": firmware or "", "product_name": product or ""}]}}


def access_code_reply(code):
    """MRA:1552-1559 send_access_code: the access code OrcaSlicer itself passed in (never a printer secret)."""
    return {"system": {"command": "get_access_code", "access_code": code or ""}}


def gcode_reply(command, param, ok):
    """MRA:1238-1248: the answer to a gcode_line command."""
    return {"print": {"command": "gcode_line", "sequence_id": command.get("seq", ""), "param": param,
                      "result": "success" if ok else "failed"}}


# commands ------------------------------------------------------------------------------------------------
_G28 = {"": "xyz", "Z": "z"}   # Kobra homes all or Z alone (Kobralink macro.service.ts); X/Y alone: unsupported
_NUM = r"(-?\d+(?:\.\d+)?)"


def _gcode(text):
    """The few G-code lines the Device tab sends (IPrinterAgent.hpp command_* defaults, DevFan:56)."""
    lines = [ln.strip().upper() for ln in str(text or "").splitlines() if ln.strip()]
    if lines == ["G90"]:
        return {"kind": "noop"}
    if len(lines) == 3 and lines[0] == "G91" and lines[2] == "G90":   # command_axis_control: X/Y/Z only
        m = re.fullmatch(r"G1 ([XYZ])%s(?: F\d+(?:\.\d+)?)?" % _NUM, lines[1])
        if m:
            return {"kind": "move", "axis": m.group(1).lower(), "distance": float(m.group(2))}
    if len(lines) != 1:
        return None
    line = lines[0]
    m = re.fullmatch(r"(M104|M140) S%s" % _NUM, line)
    if m:
        return {"kind": "set_temp", ("nozzle" if m.group(1) == "M104" else "bed"): float(m.group(2))}
    m = re.fullmatch(r"M106 P1 S%s" % _NUM, line)   # P1 = part cooling fan, S 0-255
    if m:
        return {"kind": "set_fan", "pct": int(max(0.0, min(255.0, float(m.group(1)))) * 100 / 255 + 0.5)}
    m = re.fullmatch(r"G28((?: [XYZ])*)", line)
    if m and m.group(1).replace(" ", "") in _G28:
        return {"kind": "home", "axes": _G28[m.group(1).replace(" ", "")]}
    return None


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _print_command(p, name):
    if name in ("pause", "resume", "stop"):
        return {"kind": name}
    if name == "gcode_line":
        out = _gcode(p.get("param")) if isinstance(p.get("param"), str) else None
        return {**out, "gcode": True} if out else None
    if name == "set_bed_temp" and _num(p.get("temp")) is not None:                        # DM command_set_bed
        return {"kind": "set_temp", "bed": _num(p["temp"])}
    if name == "set_nozzle_temp" and _num(p.get("target_temp")) is not None and not p.get("extruder_index"):
        return {"kind": "set_temp", "nozzle": _num(p["target_temp"])}                    # DM:1698-1704
    if name == "set_fan" and p.get("fan_index") == 1 and _num(p.get("speed")) is not None:   # DevFan:61-70
        return {"kind": "set_fan", "pct": int(max(0, min(100, _num(p["speed"]))))}
    if name == "print_speed" and str(p.get("param")) in ("1", "2", "3"):   # DM:1935-1940; "4" (ludicrous): no Kobra mode
        return {"kind": "set_speed", "mode": int(p["param"])}
    if name == "ams_filament_setting":                                                    # DM:1820-1835
        colour = str(p.get("tray_color") or "")
        ams_id, slot_id = _num(p.get("ams_id")), _num(p.get("slot_id"))
        if re.fullmatch(r"[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", colour) and ams_id is not None and slot_id is not None \
                and 0 <= ams_id < 16 and 0 <= slot_id < 4 and str(p.get("tray_type") or "").strip():
            return {"kind": "slot_set", "tray": int(ams_id) * 4 + int(slot_id), "type": str(p["tray_type"]).strip(),
                    "colour": "#" + colour[:6].upper()}
        return None
    if name == "ams_change_filament":                                                     # DM:1740-1760
        ams_id, slot_id = _num(p.get("ams_id")), _num(p.get("slot_id"))
        if slot_id == 255 or p.get("target") == 255:
            return {"kind": "slot_retract"}
        if ams_id is not None and slot_id is not None and 0 <= ams_id < 16 and 0 <= slot_id < 4:
            return {"kind": "slot_feed", "tray": int(ams_id) * 4 + int(slot_id)}
    return None   # skip_objects (Bambu object ids; the Kobra skips by name), ams_control, calibrations, ...


def parse_command(json_str):
    """A Device tab command -> {"kind", ..., "seq"} (see the module docstring)."""
    try:
        msg = json.loads(json_str)
    except (TypeError, ValueError):
        return {"kind": "invalid"}
    if not isinstance(msg, dict):
        return {"kind": "invalid"}
    for section in ("print", "system", "info", "pushing"):
        body = msg.get(section)
        if isinstance(body, dict) and "command" in body:
            break
    else:
        return {"kind": "unsupported", "seq": ""}
    name, seq = body["command"], str(body.get("sequence_id") or "")
    if not isinstance(name, str):
        return {"kind": "invalid"}
    out = None
    if section == "info" and name == "get_version" or section == "system" and name == "get_access_code" \
            or section == "pushing" and name == "pushall":
        out = {"kind": name}
    elif section == "pushing" and name in ("start", "stop"):
        # DevManager.cpp:262-268 sends pushing start on a timer until a push arrives: answer it, never -7010
        out = {"kind": "pushall" if name == "start" else "noop"}
    elif section == "system" and name == "ledctrl":
        if body.get("led_node") == CHAMBER_LIGHT and body.get("led_mode") in ("on", "off"):
            out = {"kind": "set_light", "on": body["led_mode"] == "on"}
    elif section == "print":
        out = _print_command(body, name)
    return {**(out or {"kind": "unsupported"}), "seq": seq}
