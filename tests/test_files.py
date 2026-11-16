import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import ace  # noqa: E402
import files  # noqa: E402
import kobra_captures as cap  # noqa: E402
import kobra  # noqa: E402
from fake_kobra import FakeKobra  # noqa: E402

LISTING = [{"filename": "b.gcode", "size": 200, "timestamp": 20}, {"filename": "a.gcode", "size": 100, "timestamp": 10}]


def _slot(g, type_, status=5, color=(1, 2, 3)):
    return {"global_index": g, "box_id": 0, "box_pos": 1, "index": g, "status": status, "type": type_, "color": list(color)}


class PlanTests(unittest.TestCase):
    """files.plan: what a file needs (from file/fileDetails) next to the slots its print would use."""
    DETAILS = cap.FILE_FILEDETAILS["data"]["file_details"]

    def test_captured_details(self):
        slots = [_slot(0, "PLA"), _slot(1, "PETG"), _slot(2, "", status=0), _slot(3, "PETG", color=(9, 9, 9))]
        plan = files.plan(self.DETAILS, slots, "ace_direct", "Anycubic Kobra X")
        self.assertEqual(plan["info"], {"estimated_s": 25816, "layers": 1875, "filament_g": 102.99, "layer_height": 0.16,
                                        "nozzle_temp": 205, "bed_temp": 60, "nozzle": 0.4,
                                        "printer_model": "Anycubic Kobra X", "model_ok": True})
        self.assertEqual(plan["materials"], [
            {"paint_index": 0, "material": "PLA", "colour": "#E10600", "grams": 84.11, "slot": 0, "slot_type": "PLA",
             "slot_colour": "#010203", "check": "ok"},
            {"paint_index": 3, "material": "PLA", "colour": "#658946", "grams": 18.88, "slot": 3, "slot_type": "PETG",
             "slot_colour": "#090909", "check": "differs"}])

    def test_plan_follows_the_auto_mapping(self):
        """The slot shown for each filament is the one print/start would map (ace.build_auto_ams_box_mapping)."""
        slots = [_slot(0, "PLA"), _slot(1, "", status=0), _slot(2, "PLA")]
        details = {"paint_infos": [{"paint_index": i, "material_type": "PLA", "filament_used": 1} for i in range(4)]}
        plan = files.plan(details, slots, "ace_direct", "Anycubic Kobra X")
        loaded, _ = ace.select_loaded_slots_for_print(slots, "ace_direct")
        mapping = {e["paint_index"]: e["ams_index"] for e in ace.build_auto_ams_box_mapping(loaded, "ace_direct")}
        self.assertEqual({m["paint_index"]: m["slot"] for m in plan["materials"]}, {0: 0, 1: 2, 2: 2, 3: None})
        self.assertEqual({p: g for p, g in mapping.items()}, {0: 0, 1: 2, 2: 2})
        self.assertEqual([m["check"] for m in plan["materials"]], ["ok", "ok", "ok", "missing"])

    def test_nothing_loaded_and_other_model(self):
        details = {"paint_infos": [{"paint_index": 0, "material_type": "pla "}], "printer_model": "Anycubic Kobra 3"}
        plan = files.plan(details, [_slot(0, "PLA", status=0)], "ace_direct", "Anycubic Kobra X")
        self.assertEqual(plan["materials"][0]["check"], "missing")
        self.assertFalse(plan["info"]["model_ok"])

    def test_hostile_details(self):
        for details in (None, [], {"paint_infos": "x"}, {"paint_infos": [None, 5, {"paint_index": "a"}, {"paint_index": True}]},
                        {"estimated_time_s": float("inf"), "layer_count": "x", "print_parameters": {"temperatures": []}},
                        {"paint_infos": [{"paint_index": 0, "material_type": ["x"], "paint_color": "red", "filament_used": -5}]}):
            plan = files.plan(details, [_slot(0, "PLA")], "ace_direct", "Anycubic Kobra X")
            json.dumps(plan, allow_nan=False)
            self.assertTrue(plan["info"]["model_ok"])
        bad = files.plan({"paint_infos": [{"paint_index": 0, "material_type": ["x"], "paint_color": "red", "filament_used": -5}]},
                         [_slot(0, "PLA")], "ace_direct", "")["materials"][0]
        self.assertEqual((bad["material"], bad["colour"], bad["grams"], bad["check"]), ("", "", 0, "ok"))


class RowTests(unittest.TestCase):
    def test_rows_keep_order_and_add_thumbnail_only_when_details_are_known(self):
        rows = files.rows(LISTING, {"a.gcode": {"thumbnail": "iVBORw0KGgo="}})
        self.assertEqual([r["name"] for r in rows], ["b.gcode", "a.gcode"])
        self.assertIsNone(rows[0]["thumbnail"])
        self.assertEqual(rows[1]["thumbnail"], "data:image/png;base64,iVBORw0KGgo=")
        self.assertEqual((rows[1]["size"], rows[1]["timestamp"]), (100, 10))

    def test_bad_input_and_bad_thumbnails_are_dropped(self):
        listing = [{"filename": "ok.gcode", "size": 1, "timestamp": 2}, {"filename": ""}, {"filename": "x/y.gcode"},
                   "junk", {"filename": 5}, {"filename": "c.gcode", "size": "7", "timestamp": None}]
        details = {"ok.gcode": {"thumbnail": "<script>alert(1)</script>"}, "c.gcode": {"thumbnail": 5}}
        rows = files.rows(listing, details)
        self.assertEqual([r["name"] for r in rows], ["ok.gcode", "c.gcode"])
        self.assertEqual([r["thumbnail"] for r in rows], [None, None])
        self.assertEqual(rows[1]["size"], 0)
        self.assertEqual(files.rows(None), [])
        self.assertEqual(files.rows("x", "y"), [])

    def test_huge_thumbnail_is_dropped_and_data_url_passes_only_for_png(self):
        big = "A" * (files.THUMB_MAX + 4)
        self.assertIsNone(files.rows(LISTING, {"a.gcode": {"thumbnail": big}})[1]["thumbnail"])
        ok = files.rows(LISTING, {"a.gcode": {"thumbnail": "data:image/png;base64,AAAA"}})[1]["thumbnail"]
        self.assertEqual(ok, "data:image/png;base64,AAAA")
        bad = files.rows(LISTING, {"a.gcode": {"thumbnail": "data:text/html;base64,AAAA"}})[1]["thumbnail"]
        self.assertIsNone(bad)

    def test_inputs_are_not_mutated(self):
        listing = [dict(f) for f in LISTING]
        files.rows(listing, {"a.gcode": {"thumbnail": "AAAA"}})
        self.assertEqual(listing, LISTING)


class NameTests(unittest.TestCase):
    def test_valid_names(self):
        for name in ("a.gcode", "My part (1).gcode", "Ünï.gcode", "a..b.gcode"):
            self.assertEqual(files.valid_name(name), name)

    def test_invalid_names(self):
        for bad in ("", ".", "..", "a/b.gcode", "a\\b.gcode", "a\x00.gcode", "a\nb", "\x7f", "  ", None, 5,
                    "x" * 300, "/etc/passwd", "../x"):
            with self.assertRaises(ValueError, msg=repr(bad)):
                files.valid_name(bad)

    def test_valid_names_list(self):
        self.assertEqual(files.valid_names(["a.gcode", "b.gcode", "a.gcode"]), ["a.gcode", "b.gcode"])
        for bad in ([], "a.gcode", None, ["a", "../b"], ["a"] * 0, ["f%d" % i for i in range(files.MAX_DELETE + 1)]):
            with self.assertRaises(ValueError, msg=repr(bad)):
                files.valid_names(bad)


class PayloadTests(unittest.TestCase):
    def test_payload_uses_the_listed_size(self):
        mapping = [{"paint_index": 0, "ams_index": 1}]
        p = files.print_payload(LISTING, "a.gcode", mapping, auto_leveling=True, vibration_compensation=False)
        self.assertEqual(p, kobra.print_file_payload("a.gcode", 100, mapping, {"auto_leveling": True,
                                                                              "vibration_compensation": False,
                                                                              "skip_parts": []}))
        self.assertEqual(p["filepath"], "/")
        self.assertEqual(p["task_settings"]["auto_leveling"], 1)
        self.assertEqual(p["task_settings"]["vibration_compensation"], 0)

    def test_payload_flow_calibration_and_timelapse(self):
        p = files.print_payload(LISTING, "a.gcode", [], flow_calibration=True, timelapse=True)
        self.assertEqual((p["task_settings"]["flow_calibration"], p["task_settings"]["timelapse"]["status"]), (1, 1))
        p = files.print_payload(LISTING, "a.gcode", [])
        self.assertEqual((p["task_settings"]["flow_calibration"], p["task_settings"]["timelapse"]["status"]), (0, 0))

    def test_unknown_or_bad_names_are_refused(self):
        with self.assertRaises(ValueError):
            files.print_payload(LISTING, "nope.gcode", [])
        with self.assertRaises(ValueError):
            files.print_payload(LISTING, "../a.gcode", [])

    def test_skip_parts_are_copied_as_strings(self):
        p = files.print_payload(LISTING, "a.gcode", [], skip_parts=["o1", 2])
        self.assertEqual(p["task_settings"]["model_objects_skip_parts"], ["o1", "2"])


class FakePrinter:
    def __init__(self, ip=""):
        self.creds = type("C", (), {"ip": ip, "device_id": "d" + ip})()
        self.files, self.started, self.deleted, self.details = [dict(f) for f in LISTING], [], [], {"thumbnail": "AAAA"}

    def list_files(self):
        return [dict(f) for f in self.files]

    def file_details(self, name):
        return self.details

    def start_print(self, payload):
        self.started.append(payload)

    def delete_files(self, names):
        self.deleted += names
        self.files = [f for f in self.files if f["filename"] not in names]


class Host(files.FilesMixin):
    def __init__(self, printer=None, slots=(), mode="ace_direct"):
        self.printer, self.idle_checks = printer or FakePrinter(), 0
        self.slots, self.mode = list(slots), mode

    def _view(self):
        return {"slots": self.slots, "mode": self.mode}

    def _printer(self):
        return self.printer

    def _require_idle(self):
        self.idle_checks += 1


class MixinTests(unittest.TestCase):
    def test_list_details_print_delete(self):
        h = Host()
        self.assertIsNone(h.cmd_files()["files"][1]["thumbnail"])
        self.assertEqual(h.cmd_file_details("a.gcode")["thumbnail"], "data:image/png;base64,AAAA")
        self.assertEqual(h.cmd_files()["files"][1]["thumbnail"], "data:image/png;base64,AAAA")
        h.cmd_file_print("a.gcode", auto_leveling=True)
        self.assertEqual((h.idle_checks, h.printer.started[0]["filename"], h.printer.started[0]["filesize"]), (1, "a.gcode", 100))
        self.assertEqual([r["name"] for r in h.cmd_file_delete(["a.gcode"])["files"]], ["b.gcode"])
        self.assertEqual(h.printer.deleted, ["a.gcode"])

    def test_thumbnails_are_per_printer_and_forgotten_when_the_file_is_gone(self):
        first = FakePrinter("10.0.0.1")
        h = Host(first)
        h.cmd_file_details("a.gcode")
        self.assertIsNotNone(h.cmd_files()["files"][1]["thumbnail"])
        other = FakePrinter("10.0.0.2")                   # the service now talks to another printer
        h.printer = other
        self.assertIsNone(h.cmd_files()["files"][1]["thumbnail"])
        h.printer = first
        self.assertIsNotNone(h.cmd_files()["files"][1]["thumbnail"])
        first.files = [f for f in first.files if f["filename"] != "a.gcode"]
        h.cmd_files()                                      # a.gcode deleted outside kobracontrol
        first.files.append({"filename": "a.gcode", "size": 1, "timestamp": 1})
        self.assertIsNone(h.cmd_files()["files"][-1]["thumbnail"])

    def test_bad_names_never_reach_the_printer(self):
        h = Host()
        for call in (lambda: h.cmd_file_details("../x"), lambda: h.cmd_file_print("../x"),
                     lambda: h.cmd_file_delete(["a.gcode", "x/y"]), lambda: h.cmd_file_print("missing.gcode")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual((h.printer.started, h.printer.deleted), ([], []))


def loaded_slot(i, box=0, type_="PLA", color=(255, 0, 0)):
    return {"global_index": box * 4 + i, "box_id": box, "box_pos": box, "index": i, "status": 5, "type": type_,
            "color": list(color), "rfid": None, "sku": None, "activity": ""}


class AutoMappingTests(unittest.TestCase):
    """A stored file is printed with the automatic ACE mapping; payloads are what FakeKobra receives."""

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        creds = kobra.fetch_credentials(self.fake.host, port=self.fake.http_port, timeout=3)
        self.printer = kobra.Printer(creds, mqtt_port=self.fake.mqtt_port, http_port=self.fake.http_port)
        self.addCleanup(self.printer.close)
        self.printer.connect()
        self.fake.reply("file", "listLocal", {"records": [dict(f) for f in LISTING]}, state="success", code=200)
        self.fake.reply("print", "start", {}, state="success", code=0)

    def sent(self, slots):
        host = Host(self.printer, slots)
        host.cmd_file_print("a.gcode", auto_leveling=True)
        self.assertEqual(host.idle_checks, 1)
        return self.fake.wait_request("print", "start")["data"]

    def test_two_loaded_slots_make_a_two_entry_mapping_and_use_ams(self):
        data = self.sent([loaded_slot(0), loaded_slot(1, color=(0, 255, 0))])
        self.assertTrue(data["ams_settings"]["use_ams"])
        self.assertEqual([e["paint_index"] for e in data["ams_settings"]["ams_box_mapping"]], [0, 1])
        self.assertEqual([e["ams_index"] for e in data["ams_settings"]["ams_box_mapping"]], [0, 1])
        self.assertEqual((data["filename"], data["filesize"], data["task_settings"]["auto_leveling"]), ("a.gcode", 100, 1))

    def test_nothing_loaded_means_empty_mapping_and_no_ams(self):
        empty = loaded_slot(0)
        empty["status"] = 0
        data = self.sent([empty])
        self.assertEqual((data["ams_settings"]["use_ams"], data["ams_settings"]["ams_box_mapping"]), (False, []))
        data = self.sent([])
        self.assertFalse(data["ams_settings"]["use_ams"])


if __name__ == "__main__":
    unittest.main()
