"""Service end to end against FakeKobra on 127.0.0.1. Run: python3 -m unittest tests/test_service.py -v"""

import glob
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import kobra  # noqa: E402
import service  # noqa: E402
from fake_kobra import FakeKobra  # noqa: E402

ACE0 = {"id": 0, "loaded_slot": -1, "auto_feed": 1, "slots": [
    {"index": 0, "status": 5, "type": "PLA", "color": [255, 0, 0]},
    {"index": 1, "status": 5, "type": "PETG", "color": [0, 0, 255]},
    {"index": 2, "status": 0, "type": "", "color": [0, 0, 0]},
    {"index": 3, "status": 5, "type": "PLA", "color": [0, 255, 0]}]}
READ_ONLY = {("info", "query"), ("print", "query"), ("multiColorBox", "getInfo")}


def wait(pred, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


class FakeCamera:
    def __init__(self, get_url, on_frame, ffmpeg_path="", on_error=None, log=print):
        self.get_url, self.on_frame, self.on_error = get_url, on_frame, on_error
        self.calls = []

    def set_ffmpeg(self, path):
        self.calls.append(("ffmpeg", path))

    def start(self):
        self.calls.append("start")

    def stop(self):
        self.calls.append("stop")

    def ack(self):
        self.calls.append("ack")

    def close(self):
        self.calls.append("close")


class FakeSpoolman:
    spools_data = [{"id": 7, "location": "", "filament": {"id": 1, "name": "Red", "material": "PLA",
                                                         "color_hex": "FF0000", "vendor": {"name": "V"}}}]

    def __init__(self, url):
        self.url = url
        FakeSpoolman.locations = getattr(FakeSpoolman, "locations", {})

    def connect(self):
        return {"via": "direct"}

    def spools(self):
        return [dict(s, location=FakeSpoolman.locations.get(s["id"], "")) for s in self.spools_data]

    def set_location(self, sid, loc):
        FakeSpoolman.locations[sid] = loc

    def use_weight(self, sid, grams):
        pass


class Base(unittest.TestCase):
    state = "free"

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        f = self.fake
        f.reply("info", "query", {"printerName": "KX", "version": "2.1.0", "project": {"state": self.state, "taskid": "42"},
                                  "urls": {"fileUploadurl": f.upload_url, "rtspUrl": "rtsp://127.0.0.1:1/live"},
                                  "temp": {"curr_nozzle_temp": 25, "target_nozzle_temp": 0}})
        f.reply("print", "query", {"taskid": "42"}, state=self.state)
        f.reply("multiColorBox", "getInfo", {"multi_color_box": [ACE0]})
        self.tmp = tempfile.mkdtemp()
        self.published, self.logs = [], []
        self.svc = service.Service(self.published.append, self.logs.append, cert_dir=self.tmp, tls=lambda: None,
                                   http_port=f.http_port, mqtt_port=f.mqtt_port, camera_factory=FakeCamera,
                                   spoolman_factory=FakeSpoolman)
        self.addCleanup(self.svc.close)
        self.svc.set_target(service.Target(f.host, spoolman_url="http://spoolman.invalid"))
        self.conn = self.svc.connections[f.host]
        wait(lambda: self.conn.connected and self.conn.view()["multi_color_box"])

    def run_cmd(self, cmd, timeout=8.0, **args):
        rid = "r%d" % len(self.published) + cmd + str(time.monotonic())
        self.svc.submit(rid, cmd, args)
        return wait(lambda: next((m for m in self.published if m.get("type") == "reply" and m.get("id") == rid), None),
                    timeout)

    def sent(self, type_, action):
        return [r["msg"] for r in self.fake.requests if isinstance(r["msg"], dict)
                and (r["msg"].get("type"), r["msg"].get("action")) == (type_, action)]

    def kinds(self):
        return {(r["msg"]["type"], r["msg"]["action"]) for r in self.fake.requests if isinstance(r["msg"], dict)}

    def set_state(self, state):
        self.fake.report("print/report", {"type": "print", "action": "update", "state": state,
                                          "data": {"taskid": "42", "filename": "a.gcode", "progress": 10}})
        wait(lambda: self.conn.view()["kobra_state"] == state)


class Connect(Base):
    def test_fresh_connect_sends_only_read_only_queries(self):
        wait(lambda: READ_ONLY <= self.kinds())
        time.sleep(0.3)
        self.assertEqual(self.kinds(), READ_ONLY)
        self.assertEqual(len(self.fake.ctrl_calls), 1)

    def test_connect_command(self):
        reply = self.run_cmd("connect")
        self.assertEqual(reply["result"]["limits"], {"nozzle_max": 320, "bed_max": 120})
        self.assertEqual(reply["result"]["firmware"], "2.1.0")

    def test_status_while_leased(self):
        self.svc.touch(camera=False)
        msg = wait(lambda: next((m for m in self.published if m.get("type") == "status"), None))
        data = msg["data"]
        for key in kobra.VIEW_KEYS + ("mode", "slots", "loaded_slot", "ace_units", "can"):
            self.assertIn(key, data)
        self.assertEqual(data["upload_url"], "")
        self.assertEqual(data["mode"], "ace_direct")
        self.assertEqual([s["tray"] for s in data["slots"]], [0, 1, 2, 3])
        self.assertEqual(data["can"], {"pause": False, "resume": False, "stop": False, "move": True, "heat": True,
                                       "feed": True, "print": True})
        self.assertEqual(data["ace_units"][0]["auto_feed"], True)
        self.assertEqual(msg["gen"], self.svc.generation)

    def test_no_secret_reaches_page_or_log(self):
        self.svc.touch(camera=False)
        wait(lambda: any(m.get("type") == "status" for m in self.published))
        self.fake.drop_clients()
        wait(lambda: len(self.fake.ctrl_calls) >= 2 and self.conn.connected)
        text = json.dumps(self.published) + "\n".join(map(str, self.logs))
        for secret in (self.fake.password, self.fake.token, self.fake.upload_token):
            self.assertNotIn(secret, text)

    def test_reconnects_after_drop(self):
        self.fake.drop_clients()
        wait(lambda: self.conn.connected and len(self.fake.ctrl_calls) == 2)   # credentials recovered again
        self.assertEqual(len(self.fake.client_ids), 2)

    def test_stale_generation(self):
        self.svc.submit("x", "connect", {}, gen=self.svc.generation + 5)
        reply = wait(lambda: next((m for m in self.published if m.get("id") == "x"), None))
        self.assertEqual(reply["error"], service.STALE)

    def test_unknown_command(self):
        self.assertIn("unknown command", self.run_cmd("__class__")["error"])


class NoCert(unittest.TestCase):
    def test_no_certificate_flag(self):
        with FakeKobra() as fake:
            published = []
            svc = service.Service(published.append, lambda m: None, cert_dir=tempfile.mkdtemp(),
                                  http_port=fake.http_port, mqtt_port=fake.mqtt_port, camera_factory=FakeCamera)
            try:
                svc.set_target(service.Target(fake.host))
                svc.submit("c", "connect", {})
                reply = wait(lambda: next((m for m in published if m.get("id") == "c"), None), 15)
                self.assertTrue(reply["no_certificate"])
                self.assertIn("Find Anycubic certificate", reply["error"])
                self.assertEqual(fake.ctrl_calls, [])     # nothing asked of the printer without a certificate
            finally:
                svc.close()


class IdleCommands(Base):
    def test_print_controls_refused_when_idle(self):
        for cmd in ("pause", "resume", "stop"):
            self.assertIn("not possible while the printer is idle", self.run_cmd(cmd)["error"])
        self.assertFalse(self.sent("print", "stop"))

    def test_set_temp_idle_clamps(self):
        self.assertEqual(self.run_cmd("set_temp", nozzle=999, bed=-5)["result"], {"nozzle": 320, "bed": 0})
        msg = wait(lambda: self.sent("tempature", "set"))[0]
        self.assertEqual(msg["data"], {"type": 2, "target_nozzle_temp": 320, "target_hotbed_temp": 0})

    def test_move_and_home(self):
        self.fake.reply("axis", "move", {})
        self.assertTrue(self.run_cmd("move", axis="y", distance=-5)["result"])
        self.assertEqual(self.sent("axis", "move")[0]["data"], {"axis": 2, "move_type": 0, "distance": 5.0})
        self.assertTrue(self.run_cmd("home", axes="z")["result"])
        self.assertEqual(self.sent("axis", "move")[1]["data"], {"axis": 3, "move_type": 2, "distance": 0})
        self.assertIn("up to", self.run_cmd("move", axis="x", distance=0)["error"])
        self.assertIn("axis", self.run_cmd("move", axis="e", distance=1)["error"])

    def test_fan_light(self):
        self.assertTrue(self.run_cmd("set_fan", pct=150)["result"])
        self.assertEqual(wait(lambda: self.sent("fan", "setSpeed"))[0]["data"], {"fan_speed_pct": 100})
        self.assertTrue(self.run_cmd("set_light", on=True)["result"])
        self.assertEqual(wait(lambda: self.sent("light", "control"))[0]["data"]["status"], 1)

    def test_speed_needs_a_print(self):
        self.assertIn("running print", self.run_cmd("set_speed", mode=3)["error"])

    def test_slot_set_and_feed_with_ack(self):
        self.assertTrue(self.run_cmd("slot_set", slot=2, type="petg", colour="#00ff00")["result"])
        data = wait(lambda: self.sent("multiColorBox", "setInfo"))[0]["data"]
        self.assertEqual(data["multi_color_box"][0]["slots"][0], {"index": 2, "type": "PETG", "color": [0, 255, 0]})
        self.assertIn("empty", self.run_cmd("slot_feed", slot=2)["error"])
        self.assertTrue(self.run_cmd("slot_feed", slot=1)["result"])
        feed = wait(lambda: self.sent("multiColorBox", "feedFilament"))[0]["data"]
        self.assertEqual(feed["multi_color_box"][0]["feed_status"], {"slot_index": 1, "type": 1})
        box = dict(ACE0, feed_status={"current_status": 10, "slot_index": 1, "type": 1})
        self.fake.report("multiColorBox/report", {"type": "multiColorBox", "action": "update", "state": "success",
                                                  "data": {"multi_color_box": [box]}})
        acks = wait(lambda: [m for m in self.sent("multiColorBox", "feedFilament")
                             if m["data"]["multi_color_box"][0]["feed_status"]["type"] == 3], 6)
        self.assertEqual(acks[0]["data"]["multi_color_box"][0]["feed_status"]["slot_index"], 1)

    def test_dry_and_auto_feed(self):
        self.assertTrue(self.run_cmd("dry_start", aces=[0], temp=99, minutes=5)["result"])
        dry = wait(lambda: self.sent("multiColorBox", "setDry"))[0]["data"]["multi_color_box"][0]["drying_status"]
        self.assertEqual(dry, {"status": 1, "target_temp": 80, "duration": 10, "remain_time": 10})
        self.assertIn("ACE", self.run_cmd("dry_stop", aces=[3])["error"])
        self.assertTrue(self.run_cmd("auto_feed", ace=0, on=False)["result"])

    def test_spools_bind_unbind(self):
        self.assertEqual(self.run_cmd("spools")["result"]["spools"][0]["id"], 7)
        self.assertEqual(self.run_cmd("bind", slot=0, spool_id=7)["result"]["bindings"], {"0": 7})
        self.assertEqual(FakeSpoolman.locations[7], "Anycubic Kobra X S1")
        self.assertEqual(self.run_cmd("unbind", slot=0)["result"]["bindings"], {})
        self.assertEqual(FakeSpoolman.locations[7], "")

    def test_agent_call_for_host(self):
        self.svc.call(self.fake.host, "set_light", on=False)
        self.assertEqual(wait(lambda: self.sent("light", "control"))[0]["data"]["status"], 0)


class PrintingCommands(Base):
    def setUp(self):
        super().setUp()
        self.set_state("printing")

    def test_refusals_while_printing(self):
        for cmd, args in (("move", {"axis": "x", "distance": 1}), ("home", {"axes": "xyz"}), ("motors_off", {}),
                          ("slot_feed", {"slot": 0}), ("file_print", {"name": "a.gcode"}), ("resume", {})):
            self.assertIn("printing", self.run_cmd(cmd, **args)["error"], cmd)
        self.assertFalse(self.kinds() & {("axis", "move"), ("axis", "turnOff"), ("multiColorBox", "feedFilament"),
                                         ("print", "start"), ("print", "resume")})

    def test_pause_and_stop_carry_task_id(self):
        self.fake.reply("print", "pause", {}, state="paused")
        self.assertTrue(self.run_cmd("pause")["result"])
        self.assertEqual(self.sent("print", "pause")[0]["data"], {"taskid": "42"})
        self.fake.reply("print", "stop", {}, state="stoped")
        self.assertTrue(self.run_cmd("stop")["result"])

    def test_temperature_while_printing_uses_print_update(self):
        self.run_cmd("set_temp", nozzle=215.4)
        msg = wait(lambda: self.sent("print", "update"))[0]
        self.assertEqual(msg["data"], {"taskid": "42", "settings": {"target_nozzle_temp": 215}})
        self.assertIn("/web/", next(r["topic"] for r in self.fake.requests if r["msg"] is msg))

    def test_speed(self):
        self.assertTrue(self.run_cmd("set_speed", mode=4)["result"])
        self.assertEqual(wait(lambda: self.sent("print", "update"))[0]["data"]["settings"], {"print_speed_mode": 4})

    def test_print_job_refused(self):
        path = make_3mf(self.tmp)
        with self.assertRaisesRegex(kobra.KobraError, "printing"):
            self.svc.print_job(self.fake.host, path, 1, "cube", [0], [{"colour": "#FF0000", "type": "PLA"}])
        self.assertEqual(self.fake.uploads, [])


GCODE = b"; HEADER\nG28\nG1 X10\n" * 50


def make_3mf(folder, plate=1, weights=((1, "3.5"), (2, "1.25"))):
    path = os.path.join(folder, "job.3mf")
    fil = "".join('<filament id="%d" type="PLA" used_g="%s"/>' % w for w in weights)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/plate_%d.gcode" % plate, GCODE)
        z.writestr("Metadata/slice_info.config",
                   '<config><plate><metadata key="index" value="%d"/>%s</plate></config>' % (plate, fil))
        z.writestr("../evil.gcode", b"x")
    return path


class Jobs(Base):
    def setUp(self):
        super().setUp()
        self.fake.reply("print", "start", {}, code=0)
        self.tempdir = tempfile.mkdtemp()
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        tempfile.tempdir = self.tempdir

    def test_print_job_uploads_plate_and_starts_with_trays(self):
        stages, progress = [], []
        name = self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "My cube/1", [1, 3],
                                  [{"colour": "#112233", "type": "PETG"}, {"colour": "00FF00FF", "type": "PLA"}],
                                  {"auto_leveling": True}, lambda s, t: progress.append((s, t)), lambda: False,
                                  stages.append)
        self.assertEqual(name, "My cube_1.gcode")
        self.assertEqual(stages, ["upload", "start"])
        self.assertEqual(self.fake.uploads[0]["filename"], name)
        self.assertEqual(self.fake.uploads[0]["data"], GCODE)
        self.assertEqual(progress[-1], (len(GCODE), len(GCODE)))
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual(start["filename"], name)
        self.assertEqual(start["task_settings"]["auto_leveling"], 1)
        mapping = start["ams_settings"]["ams_box_mapping"]
        self.assertEqual([(m["paint_index"], m["ams_index"], m["material_type"]) for m in mapping],
                         [(0, 1, "PETG"), (1, 3, "PLA")])
        self.assertEqual(mapping[0]["paint_color"], [0x11, 0x22, 0x33, 255])
        self.assertEqual(glob.glob(os.path.join(self.tempdir, "kobracontrol-*")), [])   # temp G-code removed
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "evil.gcode")))

    def test_print_job_records_usage(self):
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0, 1],
                           [{"colour": "#FF0000", "type": "PLA"}, {"colour": "#0000FF", "type": "PETG"}])
        jobs = list(self.svc.ledger.jobs.values())
        self.assertEqual(jobs[0].per_slot, {0: 3.5, 1: 1.25})

    def test_bad_tray_refused_before_upload(self):
        with self.assertRaisesRegex(kobra.KobraError, "tray 2 is empty"):
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [2], [{"colour": "#FF0000", "type": "PLA"}])
        self.assertEqual(self.fake.uploads, [])

    def test_missing_plate(self):
        with self.assertRaisesRegex(kobra.KobraError, "plate 2"):
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 2, "cube", [0], [{"colour": "#FF0000"}])

    def test_cancel_during_upload(self):
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 1
        big = os.path.join(self.tmp, "big.gcode")
        with open(big, "wb") as f:
            f.write(b"G1 X1\n" * 200000)
        with self.assertRaises(kobra.Cancelled):
            self.svc.print_job(self.fake.host, big, 1, "big", [0], [{"colour": "#FF0000"}], cancelled=cancelled)
        time.sleep(0.2)
        self.assertFalse(self.sent("print", "start"))

    def test_send_file_uploads_only(self):
        self.assertEqual(self.svc.send_file(self.fake.host, make_3mf(self.tmp), "part"), "part.gcode")
        self.assertEqual(self.fake.uploads[0]["data"], GCODE)
        time.sleep(0.2)
        self.assertFalse(self.sent("print", "start"))

    def test_no_trays_uses_loaded_slots(self):
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [-1], [{"colour": "#FF0000"}])
        mapping = wait(lambda: self.sent("print", "start"))[0]["data"]["ams_settings"]["ams_box_mapping"]
        self.assertEqual([m["ams_index"] for m in mapping], [0, 1, 3, 3])


def start_mapping(test):
    start = wait(lambda: test.sent("print", "start"))[0]["data"]
    return [m["ams_index"] for m in start["ams_settings"]["ams_box_mapping"]]


class Files(Base):
    def test_list_details_delete_print(self):
        records = [{"filename": "a.gcode", "size": 10, "timestamp": 2}, {"filename": "b.gcode", "size": 5, "timestamp": 1}]
        self.fake.reply("file", "listLocal", {"records": records}, code=200)
        self.fake.reply("file", "fileDetails", {"file_details": {"thumbnail": "iVBORw0KGgo=", "objects_skip_parts": ["A"]}})
        self.fake.reply("file", "deleteBatch", {}, code=200)
        self.fake.reply("print", "start", {}, code=0)
        self.assertEqual([r["name"] for r in self.run_cmd("files")["result"]["files"]], ["a.gcode", "b.gcode"])
        details = self.run_cmd("file_details", name="a.gcode")["result"]
        self.assertTrue(details["thumbnail"].startswith("data:image/png;base64,"))
        self.assertTrue(self.run_cmd("file_print", name="a.gcode", auto_leveling=True)["result"])
        self.assertEqual(start_mapping(self), [0, 1, 3, 3])   # the loaded ACE slots, Kobralink's auto mapping
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual((start["filename"], start["filesize"]), ("a.gcode", 10))
        self.assertIn("files", self.run_cmd("file_delete", names=["b.gcode"])["result"])
        self.assertIn("path separators", self.run_cmd("file_details", name="../x")["error"])


if __name__ == "__main__":
    unittest.main()


class Preparing(Base):
    def test_pause_refused_while_preparing_but_stop_allowed(self):
        self.set_state("auto_leveling")
        self.svc.touch(camera=False)
        data = wait(lambda: next((m["data"] for m in reversed(self.published) if m.get("type") == "status"
                                  and m["data"]["preparing"]), None))
        self.assertEqual((data["can"]["pause"], data["can"]["stop"]), (False, True))
        self.assertIn("not possible", self.run_cmd("pause")["error"])


class FakePeers:
    def __init__(self, spooler_state, stock_state):
        self.spooler_state, self.stock_state = spooler_state, stock_state

    def want_stock(self, refresh):
        pass

    def stock(self):
        return ({"state": self.spooler_state, "text": "", "detail": "", "version": "1", "session": "s", "origin": ""},
                {"state": self.stock_state, "code": "waiting", "text": "", "rows": [], "key": "", "ts": 0})


class Stock(Base):
    def stock(self):
        return self.run_cmd("stock")["result"]

    def test_reasons(self):
        self.assertEqual((self.stock()["available"], self.stock()["reason"]), (False, "absent"))   # no Spooler link
        self.svc.peers = FakePeers("active", "missing")
        self.assertEqual(self.stock()["reason"], "waiting")
        self.svc._stock_missing_since -= service.STOCK_UNSUPPORTED_S
        self.assertEqual(self.stock()["reason"], "unsupported")   # released Spooler publishes only for u1control
        self.svc.peers = FakePeers("active", "stale")
        self.assertEqual(self.stock()["reason"], "stale")
        self.svc.peers = FakePeers("active", "ok")
        self.assertEqual((self.stock()["available"], self.stock()["reason"]), (True, None))
