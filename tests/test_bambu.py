"""Run: python3 -m unittest tests/test_bambu.py -v"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import ace  # noqa: E402
import bambu  # noqa: E402
import kobra  # noqa: E402


def view(**kw):
    state = kobra.State("Anycubic Kobra X")
    state.connected = True
    v = state.view()
    v.update(kw)
    v["state"] = kobra.normalise(v["kobra_state"])
    return v


def slots_of(boxes):
    mode = ace.detect_filament_mode(boxes)
    return ace.aggregate_slots(boxes, mode)[0], mode


ACE0 = {"id": 0, "loaded_slot": 1, "slots": [
    {"index": 0, "status": 5, "type": "PLA", "color": [255, 0, 0]},
    {"index": 1, "status": 5, "type": "PETG", "color": [0, 128, 255]},
    {"index": 2, "status": 0, "type": "", "color": [0, 0, 0]},
    {"index": 3, "status": 5, "type": "WEIRD", "color": [1, 2, 3]}]}
ACE1 = {"id": 1, "slots": [{"index": 0, "status": 5, "type": "ABS", "color": [9, 9, 9]}]}


class PushStatus(unittest.TestCase):
    def push(self, v=None, boxes=(), **kw):
        slots, mode = slots_of(list(boxes))
        return bambu.push_status(v or view(), slots, mode, **kw)["print"]

    def test_core_fields(self):
        p = self.push(view(kobra_state="printing", progress=41.6, remaining_s=754, layer=12, total_layers=200,
                           nozzle_temp=219.5, nozzle_target=220, bed_temp=59, bed_target=60, fan_pct=50,
                           filename="cube.gcode", speed_mode=3, light_on=True))
        self.assertEqual(p["command"], "push_status")
        self.assertEqual(p["sequence_id"], "0")   # else OrcaSlicer logs "command_handle_response, error reponse." per push
        self.assertEqual(p["gcode_state"], "RUNNING")
        self.assertEqual(p["mc_percent"], 42)
        self.assertEqual(p["mc_remaining_time"], 12)
        self.assertEqual((p["layer_num"], p["total_layer_num"]), (12, 200))
        self.assertEqual((p["nozzle_temper"], p["nozzle_target_temper"]), (219.5, 220))
        self.assertEqual((p["bed_temper"], p["bed_target_temper"]), (59, 60))
        self.assertEqual(p["fan_gear"], 128)
        self.assertEqual(p["subtask_name"], "cube.gcode")
        self.assertEqual(p["gcode_file"], "cube.gcode")
        self.assertEqual(p["spd_lvl"], 3)
        self.assertEqual(self.push(view(speed_mode=4))["spd_lvl"], 2)   # the Kobra has modes 1-3 only
        self.assertEqual(p["lights_report"], [{"node": "chamber_light", "mode": "on"}])
        self.assertEqual((p["mc_print_error_code"], p["print_error"]), (0, 0))
        json.dumps(p)

    def test_states(self):
        for kobra_state, want in (("free", "IDLE"), ("printing", "RUNNING"), ("auto_leveling", "RUNNING"),
                                  ("paused", "PAUSE"), ("finished", "FINISH"), ("stoped", "FAILED"),
                                  ("failed", "FAILED"), ("mystery", "RUNNING")):
            self.assertEqual(self.push(view(kobra_state=kobra_state))["gcode_state"], want, kobra_state)

    def test_job_phases_become_device_tab_stages(self):
        """DM:3712-3727 reads stg/stg_cur; get_stage_string (DM:178-260) names them."""
        for phase, stage in (("hotbed_heating", 2), ("nozzle_heating", 7), ("auto_leveling", 1),
                             ("frequency_sweeping", 3), ("ace_filament_feeding", 24), ("ace_filament_unfeeding", 22),
                             ("nozzle_purging", 14), ("nozzle_wiping", 14), ("nozzle_cooling", 0), ("printing", 0),
                             ("z_offset_calibrating", 0)):
            p = self.push(view(kobra_state=phase))
            self.assertEqual((p["stg_cur"], p["stg"]), (stage, [stage]), phase)
        self.assertEqual(self.push()["stg"], [])   # idle: no stage list, so no stage text

    def test_filament_change_mid_print_stays_running(self):
        p = self.push(view(kobra_state="ace_filament_feeding", preparing=True, layer=40))
        self.assertEqual((p["gcode_state"], p["stg_cur"]), ("RUNNING", 24))

    def test_preparing_is_prepare(self):
        self.assertEqual(self.push(view(kobra_state="auto_leveling", preparing=True))["gcode_state"], "PREPARE")

    def test_storage_flags_let_orca_send(self):
        p = self.push()
        self.assertIs(p["sdcard"], True)
        self.assertEqual(p["home_flag"] >> 8 & 3, 1)   # DevStorage::HAS_SDCARD_NORMAL in bits 8-9
        self.assertIs(p["support_send_to_sd"], True)

    def test_offline_reports_no_storage(self):
        v = view()
        v["connected"], v["state"] = False, "offline"
        p = self.push(v)
        self.assertIs(p["sdcard"], False)
        self.assertEqual(p["home_flag"] >> 8 & 3, 0)

    def test_temperature_ranges(self):
        p = self.push(nozzle_max=320, bed_max=120)
        self.assertEqual(p["nozzle_temp_range"], [0, 320])
        self.assertEqual(p["bed_temp_range"], [0, 120])

    def test_camera(self):
        self.assertEqual(self.push(view(camera_url="rtsp://x/1"))["ipcam"]["ipcam_dev"], "1")
        self.assertEqual(self.push()["ipcam"]["ipcam_dev"], "0")

    def test_ams_trays(self):
        p = self.push(boxes=[ACE0, ACE1])
        ams = p["ams"]
        self.assertEqual([u["id"] for u in ams["ams"]], ["0", "1"])
        trays = ams["ams"][0]["tray"]
        self.assertEqual([t["id"] for t in trays], ["0", "1", "2", "3"])
        self.assertEqual(trays[0]["tray_type"], "PLA")
        self.assertEqual(trays[0]["tray_color"], "FF0000FF")
        self.assertEqual(trays[0]["tray_info_idx"], "OFDSrzZ8")   # Generic PLA @System
        self.assertEqual(trays[1]["tray_info_idx"], "OFYPdQJh")   # Generic PETG @System
        self.assertEqual(trays[2]["tray_type"], "")          # empty slot
        self.assertEqual(trays[3]["tray_info_idx"], "")      # no generic preset for that material
        self.assertEqual(ams["ams_exist_bits"], "3")
        self.assertEqual(ams["tray_exist_bits"], "1B")       # trays 0, 1, 3 and 4 (ACE 1 slot 0)

    def test_tray_ids_prefer_the_linked_spools_preset_then_generic_by_material(self):
        own = {0: "SPLA1B2C3D4E5"}   # slot 0 is linked to a spool whose Spooler preset carries this id
        p = self.push(boxes=[ACE0, ACE1], preferred=lambda s: own.get(s["global_index"], ""))
        trays = [t for unit in p["ams"]["ams"] for t in unit["tray"]]
        self.assertEqual([t["tray_info_idx"] for t in trays], ["SPLA1B2C3D4E5", "OFYPdQJh", "", "", "OFY9muEs", "", "", ""])

    def test_generic_id_by_the_real_material(self):
        self.assertEqual(bambu.generic_filament_id("PETG"), "OFYPdQJh")
        self.assertEqual(bambu.generic_filament_id("pla matte"), "OFmY0l6t")
        self.assertEqual(bambu.material_family("PLA+"), "PLA")       # not in the table: by word
        self.assertEqual(bambu.material_family("PETG HF"), "PETG")
        self.assertEqual(bambu.material_family("PLA-CF Matte"), "PLA-CF")   # longest family
        self.assertIsNone(bambu.material_family("PETGX"))
        self.assertEqual(bambu.generic_filament_id("WEIRD"), "")
        self.assertTrue(set(bambu.FILAMENT_FAMILIES.values()) <= set(bambu.GENERIC_IDS))   # an id for every family

    def test_remaining_percent(self):   # DevFilaSystem.cpp:783-789 tray "remain"; :450 calibrate_remain_flag
        box = {"id": 0, "slots": [{"index": 0, "status": 5, "type": "PLA", "color": [1, 2, 3], "consumables_percent": 37},
                                  {"index": 1, "status": 5, "type": "PLA", "color": [1, 2, 3]}]}
        ams = self.push(boxes=[box])["ams"]
        self.assertEqual([t.get("remain") for t in ams["ams"][0]["tray"]], [37, -1, None, None])
        self.assertIs(ams["calibrate_remain_flag"], True)
        self.assertIs(self.push(boxes=[ACE1])["ams"]["calibrate_remain_flag"], False)

    def test_flow_calibration_bit_follows_features(self):
        """home_flag bit 16 shows Flow Dynamics Calibration in OrcaSlicer's Print dialog (DM parse_home_flag)."""
        on = lambda **f: self.push(view(features=f))["home_flag"] >> 16 & 1
        self.assertEqual(on(flow_calibration_support=True), 1)
        self.assertEqual(on(flow_calibration_support=False), 0)
        self.assertEqual(self.push()["home_flag"] >> 16 & 1, 1)   # not reported yet: shown, the job drops it if unsupported
        self.assertEqual(self.push(view(features={"flow_calibration_support": True}))["home_flag"] >> 8 & 3, 1)   # storage kept
        self.assertNotIn("support_auto_flow_calibration", self.push())   # on/off, never "auto"

    def test_timelapse_support_only_when_the_printer_says(self):
        """is_support_timelapse defaults to false in OrcaSlicer (DeviceManager.hpp): without it Timelapse is greyed out."""
        self.assertIs(self.push(view(features={"camera_timelapse_support": True}))["support_timelapse"], True)
        self.assertIs(self.push(view(features={"camera_timelapse_support": False}))["support_timelapse"], False)
        self.assertIs(self.push()["support_timelapse"], False)   # unknown: not claimed

    def test_bed_leveling_follows_features(self):
        self.assertEqual(self.push(view(features={"auto_leveling_support": False}))["support_bed_leveling"], 0)
        self.assertEqual(self.push(view(features={"auto_leveling_support": True}))["support_bed_leveling"], 1)
        self.assertEqual(self.push()["support_bed_leveling"], 1)   # not reported: no guess against it

    def test_no_boxes_external_spool_only(self):
        """No ACE, no reported holder slot: the external spool is the one tray OrcaSlicer can pick."""
        ams = self.push()["ams"]
        self.assertEqual([(u["id"], u["display_name"], u["tray"][0]["id"]) for u in ams["ams"]],
                         [("0", "Spool holder", "0")])
        self.assertEqual((ams["ams_exist_bits"], ams["tray_exist_bits"]), ("1", "1"))

    def test_hub_mode_ace_then_spool_holder(self):
        """The 3 spool-holder positions (box -1) and the 4 ACE slots: 7 sources in two 4-tray units, the ACE first."""
        head = {"id": -1, "slots": [{"index": 0, "status": 5, "type": "PLA", "color": [1, 1, 1]},
                                    {"index": 1, "status": 0, "type": "", "color": [0, 0, 0]},
                                    {"index": 2, "status": 5, "type": "PETG", "color": [20, 40, 60]}]}
        ams = self.push(boxes=[head, ACE0])["ams"]
        self.assertEqual([(u["id"], u["display_name"]) for u in ams["ams"]], [("0", "ACE 1"), ("1", "Spool holder")])
        self.assertEqual(ams["ams"][0]["tray"][1]["tray_type"], "PETG")
        holder = ams["ams"][1]["tray"]
        self.assertEqual([t["id"] for t in holder], ["0", "1", "2", "3"])   # the Device tab draws 4-tray units only
        self.assertEqual([t["tray_type"] for t in holder], ["PLA", "", "PETG", ""])
        self.assertEqual(holder[2]["tray_color"], "14283CFF")
        self.assertEqual([t.get("tray_slot_placeholder") for t in holder], [None, "1", None, "1"])
        self.assertEqual(ams["ams_exist_bits"], "3")
        self.assertEqual(ams["tray_exist_bits"], "5B")   # ACE 0, 1, 3; holder 1 and 3 (trays 4, 6)

    def test_two_aces_and_the_spool_holder(self):
        """Chained ACE units (box ids 0, 1) are units 0 and 1, the holder unit 2: N x 4 + 3 sources."""
        head = {"id": -1, "slots": [{"index": i, "status": 5, "type": "PLA", "color": [i, i, i]} for i in range(3)]}
        ams = self.push(boxes=[head, ACE0, ACE1])["ams"]
        self.assertEqual([(u["id"], u["display_name"]) for u in ams["ams"]],
                         [("0", "ACE 1"), ("1", "ACE 2"), ("2", "Spool holder")])
        self.assertEqual(ams["ams_exist_bits"], "7")
        slots, mode = slots_of([head, ACE0, ACE1])
        self.assertEqual([ace.slot_to_print_ams_index(s, mode) for s in slots if s["box_id"] == 1], [8])
        self.assertEqual([ace.slot_to_print_ams_index(s, mode) for s in slots if s["box_id"] < 0], [0, 1, 2])

    def test_unit_names(self):
        ams = self.push(boxes=[ACE0, ACE1])["ams"]["ams"]
        self.assertEqual([u["display_name"] for u in ams], ["ACE 1", "ACE 2"])
        self.assertEqual(len(ams[1]["tray"]), 4)


class Replies(unittest.TestCase):
    def test_version(self):
        r = bambu.version_reply("2.1.0", "Anycubic Kobra X")
        self.assertEqual(r["info"]["command"], "get_version")
        self.assertEqual(r["info"]["module"][0], {"name": "ota", "sw_ver": "2.1.0", "product_name": "Anycubic Kobra X"})

    def test_access_code(self):
        self.assertEqual(bambu.access_code_reply("1234"), {"system": {"command": "get_access_code", "access_code": "1234"}})


def cmd(obj):
    return bambu.parse_command(json.dumps(obj))


class ParseCommand(unittest.TestCase):
    def test_print_controls(self):
        for name in ("pause", "resume", "stop"):
            self.assertEqual(cmd({"print": {"command": name, "sequence_id": "3"}})["kind"], name)

    def test_info_system_pushing(self):
        self.assertEqual(cmd({"info": {"command": "get_version"}})["kind"], "get_version")
        self.assertEqual(cmd({"system": {"command": "get_access_code"}})["kind"], "get_access_code")
        self.assertEqual(cmd({"pushing": {"command": "pushall"}})["kind"], "pushall")
        # M7: the host sends pushing start on a timer until it sees a push (DevManager.cpp:262-268): never -7010
        self.assertEqual(cmd({"pushing": {"command": "start"}})["kind"], "pushall")
        self.assertEqual(cmd({"pushing": {"command": "stop"}})["kind"], "noop")

    def test_temperatures(self):
        self.assertEqual(cmd({"print": {"command": "set_bed_temp", "temp": 60}}), {"kind": "set_temp", "bed": 60, "seq": ""})
        self.assertEqual(cmd({"print": {"command": "set_nozzle_temp", "target_temp": 210, "extruder_index": 0}})["nozzle"], 210)
        self.assertEqual(cmd({"print": {"command": "set_nozzle_temp", "target_temp": 210, "extruder_index": 1}})["kind"],
                         "unsupported")

    def test_gcode_subset(self):
        def g(text):
            return cmd({"print": {"command": "gcode_line", "param": text, "sequence_id": "7"}})
        self.assertEqual(g("M104 S215\n"), {"kind": "set_temp", "nozzle": 215, "seq": "7", "gcode": True})
        self.assertEqual(g("M140 S0\n")["bed"], 0)
        self.assertEqual(g("M106 P1 S255 \n")["pct"], 100)
        self.assertEqual(g("M106 P1 S128 \n")["pct"], 50)
        self.assertEqual(g("M106 P2 S255 \n")["kind"], "unsupported")
        self.assertEqual(g("G28 \n")["axes"], "xyz")
        self.assertEqual(g("G28 X\n")["kind"], "unsupported")
        self.assertEqual(g("G28 Z\n")["axes"], "z")
        self.assertEqual(g("G91 \nG1 X10.0 F3000\nG90 \n"), {"kind": "move", "axis": "x", "distance": 10.0, "seq": "7",
                                                               "gcode": True})
        self.assertEqual(g("G91 \nG1 Z-1.0 F600\nG90 \n")["distance"], -1.0)
        self.assertEqual(g("G90 \n")["kind"], "noop")
        for unsupported in ("M83 \nG0 E10.0 F300\n", "G29 \n", "M112\n", "G1 X10\n", "M104 S20 T1\n", "", "M104\n"):
            self.assertEqual(g(unsupported)["kind"], "unsupported", unsupported)

    def test_fan_speed_light(self):
        self.assertEqual(cmd({"print": {"command": "set_fan", "fan_index": 1, "speed": 40}})["pct"], 40)
        self.assertEqual(cmd({"print": {"command": "set_fan", "fan_index": 3, "speed": 40}})["kind"], "unsupported")
        self.assertEqual(cmd({"print": {"command": "print_speed", "param": "3"}}), {"kind": "set_speed", "mode": 3, "seq": ""})
        self.assertEqual(cmd({"print": {"command": "print_speed", "param": "4"}})["kind"], "unsupported")   # ludicrous
        self.assertEqual(cmd({"print": {"command": "print_speed", "param": "9"}})["kind"], "unsupported")
        self.assertEqual(cmd({"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "off"}}),
                         {"kind": "set_light", "on": False, "seq": ""})
        self.assertEqual(cmd({"system": {"command": "ledctrl", "led_node": "work_light", "led_mode": "on"}})["kind"],
                         "unsupported")

    def test_ams(self):
        self.assertEqual(cmd({"print": {"command": "ams_filament_setting", "ams_id": 1, "slot_id": 2,
                                        "tray_color": "00FF00FF", "tray_type": "PETG"}}),
                         {"kind": "slot_set", "tray": 6, "type": "PETG", "colour": "#00FF00", "seq": ""})
        self.assertEqual(cmd({"print": {"command": "ams_change_filament", "ams_id": 0, "slot_id": 3, "target": 3}}),
                         {"kind": "slot_feed", "tray": 3, "seq": ""})
        self.assertEqual(cmd({"print": {"command": "ams_change_filament", "ams_id": 0, "slot_id": 255, "target": 255}}),
                         {"kind": "slot_retract", "seq": ""})
        self.assertEqual(cmd({"print": {"command": "ams_control", "param": "resume"}})["kind"], "unsupported")
        self.assertEqual(cmd({"print": {"command": "ams_filament_setting", "ams_id": 0, "slot_id": 0,
                                        "tray_color": "zz", "tray_type": "PLA"}})["kind"], "unsupported")

    def test_unsupported_and_invalid(self):
        self.assertEqual(cmd({"print": {"command": "skip_objects", "obj_list": [1]}})["kind"], "unsupported")
        self.assertEqual(cmd({"print": {"command": "calibration"}})["kind"], "unsupported")
        self.assertEqual(cmd({"camera": {"command": "ipcam_record_set"}})["kind"], "unsupported")
        self.assertEqual(bambu.parse_command("{nope")["kind"], "invalid")
        self.assertEqual(bambu.parse_command("[1]")["kind"], "invalid")
        self.assertEqual(cmd({"print": {"command": 3}})["kind"], "invalid")

    def test_gcode_reply(self):
        r = bambu.gcode_reply({"kind": "set_temp", "seq": "7", "gcode": True}, "M104 S1\n", True)
        self.assertEqual(r, {"print": {"command": "gcode_line", "sequence_id": "7", "param": "M104 S1\n", "result": "success"}})


class BadSlotIndex(unittest.TestCase):
    def test_negative_index_is_skipped(self):   # L9: one bad slot never breaks every push
        box = {"id": 0, "slots": [{"index": -1, "status": 5, "type": "PLA", "color": [1, 2, 3]},
                                  {"index": 1, "status": 5, "type": "PLA", "color": [1, 2, 3]}]}
        slots, mode = slots_of([box])
        trays = bambu.push_status(view(), slots, mode)["print"]["ams"]["ams"][0]["tray"]
        self.assertEqual([t["id"] for t in trays if t.get("tray_type")], ["1"])


if __name__ == "__main__":
    unittest.main()
