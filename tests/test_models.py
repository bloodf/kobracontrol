"""Other Anycubic models over the LAN (profiles.py): the model table, per-model limits, the read-only mode for a model
code Kobra Control does not know, the one-client printers, and report payloads of a Kobra 3 and a Kobra S1 Max.

The payloads are re-typed from public sources, with their addresses and ids replaced: the Kobra 3 info/report from
Rinkhals' firmware/mqtt.md (firmware 2.3.5.3), the Kobra S1 Max ones from anycubic_ha_local's tests/fixtures
(firmware 2.6.9.6, MIT). No printer was contacted. Run: python3 -m unittest tests/test_models.py -v"""

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import ace  # noqa: E402
import connection  # noqa: E402
import files  # noqa: E402
import kobra  # noqa: E402
import profiles  # noqa: E402
import service  # noqa: E402
from fake_kobra import FakeKobra  # noqa: E402
from test_service import FakeCamera, FakeSpoolman, wait  # noqa: E402

K3_INFO = {"printerName": "My Kobra 3", "project": None, "model": "Anycubic Kobra 3", "ip": "192.168.1.20",
           "version": "2.3.5.3", "state": "free",
           "urls": {"fileUploadurl": "http://192.168.1.20:18910/gcode_upload?s=token",
                    "rtspUrl": "http://192.168.1.20:18088/flv"},
           "temp": {"curr_hotbed_temp": 23, "curr_nozzle_temp": 28, "target_hotbed_temp": 0, "target_nozzle_temp": 0},
           "print_speed_mode": 2, "fan_speed_pct": 0, "aux_fan_speed_pct": 0, "box_fan_level": 0}
S1MAX_INFO = {"printerName": "Anycubic Kobra S1 Max", "model": "Anycubic Kobra S1 Max", "version": "2.6.9.6",
              "ip": "192.168.1.50", "state": "busy",
              "temp": {"curr_hotbed_temp": 39, "curr_nozzle_temp": 45, "curr_chamber_temp": 43,
                       "target_hotbed_temp": 0, "target_nozzle_temp": 0, "target_chamber_temp": 0},
              "fan_speed_pct": 0, "aux_fan_speed_pct": 0, "box_fan_level": 0, "print_speed_mode": 2,
              "project": {"progress": 42, "curr_layer": 120, "total_layers": 900, "remain_time": 30, "print_time": 10,
                          "state": "printing", "print_status": 2, "filename": "demo_PETG.gcode.3mf", "pause": 0},
              "urls": {"rtspUrl": "http://192.168.1.50:18088/flv"},
              "features": {"drying_first_support": True, "camera_timelapse_support": True}}
# An S1 Max with one ACE and no head feeder box (-1): the Kobra X's box -1 is absent on every K3/S1 capture.
S1MAX_BOXES = [{"id": 0, "loaded_slot": 1,
                "drying_status": {"status": 1, "target_temp": 45, "duration": 240, "humidity": 30},
                "slots": [{"index": 0, "type": "PLA", "color": [255, 255, 255], "status": 5},
                          {"index": 1, "sku": "AHPEFG-102", "type": "PETG", "color": [67, 82, 59], "status": 5,
                           "consumables_percent": 95}]}]


class Table(unittest.TestCase):
    def test_codes_and_names(self):
        self.assertEqual(profiles.get("20030")["name"], "Anycubic Kobra X")
        self.assertEqual(profiles.get(20024)["bed_max"], 110)
        self.assertIsNone(profiles.get("99999"))
        self.assertEqual(profiles.by_name("Anycubic Kobra S1 Max 0.4 nozzle")[0], "20029")
        self.assertEqual(profiles.by_name("Anycubic Kobra S1 0.4 nozzle")[0], "20025")
        self.assertEqual(profiles.by_name("Kobra 3 V2")[0], "20027")
        self.assertEqual(profiles.by_name("Prusa MK4"), (None, None))

    def test_only_verified_model_is_the_kobra_x(self):
        self.assertEqual([k for k, p in profiles.PROFILES.items() if p["verified"]], ["20030"])

    def test_preset_matching(self):
        yes = ["Anycubic Kobra X 0.4 nozzle", "Anycubic Kobra 3 0.4 nozzle", "Anycubic Kobra 3 V2 0.6 nozzle",
               "Anycubic Kobra S1 Max", "Kobra S1 (user)", "My Kobra 3 Combo", "Anycubic Kobra 4 0.4 nozzle",
               "Anycubic Kobra 3 Max 0.4 nozzle", "kobra_x"]
        no = ["Anycubic Kobra 2 Pro 0.4 nozzle", "Anycubic Kobra 2 Neo", "Anycubic Kobra 1", "Anycubic Kobra",
              "Bambu Lab X1 Carbon", "Kobra 30", ""]
        for name in yes:
            self.assertTrue(profiles.is_anycubic_lan(name), name)
        for name in no:
            self.assertFalse(profiles.is_anycubic_lan(name), name)

    def test_same_model(self):
        self.assertTrue(profiles.same_model("Anycubic Kobra 3", "20024"))
        self.assertFalse(profiles.same_model("Anycubic Kobra X", "20024"))
        self.assertTrue(profiles.same_model("", "20024"))
        self.assertFalse(profiles.same_model("Anycubic Kobra 3", "20030"))   # the Kobra X check as before
        self.assertTrue(profiles.same_model("Anycubic Kobra Z", "99999", "Anycubic Kobra Z"))

    def test_file_plan_follows_the_printer(self):
        details = {"printer_model": "Anycubic Kobra S1"}
        self.assertTrue(files.plan(details, [], "ace_direct", "", "20025")["info"]["model_ok"])
        self.assertFalse(files.plan(details, [], "ace_direct")["info"]["model_ok"])   # default: a Kobra X

    def test_limits(self):
        self.assertEqual(profiles.limits("20030"), {"nozzle_max": 320, "bed_max": 120})
        self.assertEqual(profiles.limits("20026"), {"nozzle_max": 300, "bed_max": 90})
        self.assertEqual(profiles.limits("1"), {"nozzle_max": 0, "bed_max": 0})


class Payloads(unittest.TestCase):
    def test_kobra3_info_report(self):
        s = kobra.State()
        s.set_model("20024", "Anycubic Kobra 3")
        s.connected = True
        s.apply("info/report", {"type": "info", "action": "report", "state": "done", "code": 200, "data": K3_INFO})
        v = s.view()
        self.assertEqual((v["model"], v["firmware"], v["state"], v["mode_id"]),
                         ("Anycubic Kobra 3", "2.3.5.3", "idle", "20024"))
        self.assertEqual(v["camera_url"], "http://192.168.1.20:18088/flv")
        self.assertEqual(connection.camera_url_for(v, "192.168.1.20"), "http://192.168.1.20:18088/flv")
        data, _ = service.status_data(v)
        self.assertEqual(data["limits"], {"nozzle_max": 300, "bed_max": 110})
        self.assertEqual(data["profile"]["known"], True)
        self.assertEqual(data["profile"]["verified"], False)
        self.assertTrue(data["can"]["heat"] and data["can"]["move"] and data["can"]["print"])

    def test_s1max_print_and_ace_without_head_box(self):
        s = kobra.State()
        s.set_model("20029", "")
        s.connected = True
        s.apply("info/report", {"type": "info", "action": "report", "state": "done", "data": S1MAX_INFO})
        s.apply("multiColorBox/report", {"type": "multiColorBox", "action": "getInfo", "state": "success",
                                         "data": {"multi_color_box": S1MAX_BOXES}})
        v = s.view()
        self.assertEqual((v["state"], v["filename"], v["progress"]), ("printing", "demo_PETG.gcode.3mf", 42))
        self.assertEqual(ace.detect_filament_mode(v["multi_color_box"]), "ace_direct")
        data, _ = service.status_data(v)
        self.assertEqual([x["type"] for x in data["slots"]][:2], ["PLA", "PETG"])
        self.assertEqual(data["limits"]["nozzle_max"], 350)

    def test_unknown_model_is_read_only(self):
        view = {"connected": True, "state": "idle", "mode_id": "29999"}
        can = service.can_flags(view)
        self.assertFalse(any(can[k] for k in ("move", "heat", "feed", "print")))
        printing = service.can_flags({**view, "state": "printing"})
        self.assertTrue(printing["pause"] and printing["stop"])   # a print started elsewhere can still be stopped
        self.assertTrue(service.can_flags({**view, "mode_id": "20030"})["heat"])
        self.assertFalse(service.can_flags({**view, "mode_id": "20021"})["print"])   # Kobra 2: no LAN profile


class Fleet(unittest.TestCase):
    """The service against FakeKobra pretending to be another model."""

    def start(self, mode_id, model):
        fake = FakeKobra().start()
        self.addCleanup(fake.stop)
        fake.mode_id, fake.model = mode_id, model
        fake.reply("info", "query", {"printerName": "P", "version": "2.3.5.3", "project": None,
                                     "urls": {"fileUploadurl": fake.upload_url, "rtspUrl": ""}}, state="done")
        fake.reply("print", "query", {}, state="free")
        fake.reply("multiColorBox", "getInfo", {"multi_color_box": S1MAX_BOXES})
        self.published = []
        svc = service.Service(self.published.append, lambda m: None, cert_dir=tempfile.mkdtemp(), tls=lambda: None,
                              http_port=fake.http_port, mqtt_port=fake.mqtt_port, camera_factory=FakeCamera,
                              relay_factory=FakeCamera, spoolman_factory=FakeSpoolman)
        self.addCleanup(svc.close)
        svc.set_target(service.Target(fake.host))
        return fake, svc

    def run_cmd(self, svc, cmd, **args):
        rid = "r%s%f" % (cmd, time.monotonic())
        svc.submit(rid, cmd, args)
        return wait(lambda: next((m for m in self.published if m.get("type") == "reply" and m.get("id") == rid), None))

    def test_kobra3_topics_and_bed_limit(self):
        fake, svc = self.start("20024", "Anycubic Kobra 3")
        conn = svc.connections[fake.host]
        wait(lambda: conn.connected and conn.view()["mode_id"] == "20024")
        self.assertEqual(conn.view()["model"], "Anycubic Kobra 3")
        self.assertEqual(self.run_cmd(svc, "set_temp", nozzle=999, bed=999)["result"], {"nozzle": 300, "bed": 110})
        self.assertIn("/20024/", fake.requests[-1]["topic"])

    def test_unknown_code_refuses_heat_with_a_reason(self):
        fake, svc = self.start("29999", "Anycubic Kobra 9")
        conn = svc.connections[fake.host]
        wait(lambda: conn.connected)
        error = self.run_cmd(svc, "set_temp", nozzle=200)["error"]
        self.assertIn("29999", error)
        self.assertIn("does not know this printer model", error)
        self.assertFalse([r for r in fake.requests if isinstance(r["msg"], dict) and r["msg"].get("type") == "tempature"])

    def test_one_client_printer_stops_retrying(self):
        fake = FakeKobra().start()
        self.addCleanup(fake.stop)
        fake.mode_id, fake.connack_code = "20025", 5   # another app holds the broker: every login refused
        fake.reply("info", "query", {"printerName": "S1", "project": None}, state="done")
        fake.reply("print", "query", {}, state="free")
        fake.reply("multiColorBox", "getInfo", {"multi_color_box": []})
        with mock.patch.object(connection, "RETRY_FIRST", 0.05), mock.patch.object(connection, "RETRY_MAX", 0.05):
            conn = connection.Connection(fake.host, lambda: None, lambda m: None, http_port=fake.http_port,
                                         mqtt_port=fake.mqtt_port).start()
            self.addCleanup(conn.stop)
            wait(lambda: conn.held)
            calls = len(fake.ctrl_calls)
            self.assertIn("takes one app at a time", conn.error)
            self.assertIn("Anycubic Kobra S1", conn.error)
            time.sleep(0.4)
            self.assertEqual(len(fake.ctrl_calls), calls)   # no more attempts on a timer
            fake.connack_code = None
            conn.retry()                                    # the user's Retry tries again
            wait(lambda: conn.connected)
            self.assertFalse(conn.held)

    def test_kobra_x_keeps_retrying(self):
        fake = FakeKobra().start()
        self.addCleanup(fake.stop)
        fake.connack_code = 5
        with mock.patch.object(connection, "RETRY_FIRST", 0.02), mock.patch.object(connection, "RETRY_MAX", 0.02):
            conn = connection.Connection(fake.host, lambda: None, lambda m: None, http_port=fake.http_port,
                                         mqtt_port=fake.mqtt_port).start()
            self.addCleanup(conn.stop)
            wait(lambda: len(fake.ctrl_calls) > connection.HELD_AFTER + 1)
            self.assertFalse(conn.held)


if __name__ == "__main__":
    unittest.main()
