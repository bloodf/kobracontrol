import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import files  # noqa: E402
import kobra  # noqa: E402
from fake_kobra import FakeKobra  # noqa: E402

LISTING = [{"filename": "b.gcode", "size": 200, "timestamp": 20}, {"filename": "a.gcode", "size": 100, "timestamp": 10}]


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
        self.assertEqual(p["filepath"], "/a.gcode")
        self.assertEqual(p["task_settings"]["auto_leveling"], 1)
        self.assertEqual(p["task_settings"]["vibration_compensation"], 0)

    def test_unknown_or_bad_names_are_refused(self):
        with self.assertRaises(ValueError):
            files.print_payload(LISTING, "nope.gcode", [])
        with self.assertRaises(ValueError):
            files.print_payload(LISTING, "../a.gcode", [])

    def test_skip_parts_are_copied_as_strings(self):
        p = files.print_payload(LISTING, "a.gcode", [], skip_parts=["o1", 2])
        self.assertEqual(p["task_settings"]["model_objects_skip_parts"], ["o1", "2"])


class FakePrinter:
    def __init__(self):
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
