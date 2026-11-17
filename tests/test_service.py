"""Service end to end against FakeKobra on 127.0.0.1. Run: python3 -m unittest tests/test_service.py -v"""

import glob
import hashlib
import json
import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

from unittest import mock  # noqa: E402

import ace  # noqa: E402
import certs  # noqa: E402
import connection  # noqa: E402
import jobs  # noqa: E402
import kobra  # noqa: E402
import locate  # noqa: E402
import service  # noqa: E402
from fake_kobra import FakeKobra, make_tls_files  # noqa: E402

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

    used = []

    def use_weight(self, sid, grams):
        FakeSpoolman.used.append((sid, grams))


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
        info = self.fake.replies.get(("info", "query"))
        if isinstance(info, dict) and isinstance(info.get("data"), dict):   # the 5 s info poll must agree
            info["data"] = {**info["data"], "project": {"state": state, "taskid": "42", "filename": "a.gcode"}}
        query = self.fake.replies.get(("print", "query"))
        if isinstance(query, dict):   # so is the print/query poll made while printing
            query["state"] = state
        self.fake.report("print/report", {"type": "print", "action": "start", "state": state,
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
        for key in set(kobra.VIEW_KEYS) - {"file_details"} | {"mode", "slots", "loaded_slot", "ace_units", "can"}:
            self.assertIn(key, data)
        self.assertNotIn("file_details", data)   # stale details of some file: skip names come from cmd objects
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
    @mock.patch.object(certs, "bundled", return_value=None)   # no saved and no bundled certificate
    def test_no_certificate_flag(self, _bundled):
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
        self.assertIn("no distance", self.run_cmd("move", axis="x", distance=0)["error"])

    def test_home_codes_follow_kx_bridge_issue_4(self):
        """KX-Bridge CHANGELOG 0.9.1-beta14 (its Issue #4, found on a real printer): axis 5 homes X, Y and Z,
        axis 4 homes X and Y. Kobralink's 4 for "all" would leave Z unhomed."""
        self.fake.reply("axis", "move", {})
        for axes, code in (("xyz", 5), ("xy", 4), ("z", 3)):
            before = len(self.sent("axis", "move"))
            self.assertTrue(self.run_cmd("home", axes=axes)["result"])
            self.assertEqual(self.sent("axis", "move")[before]["data"], {"axis": code, "move_type": 2, "distance": 0})

    def test_move_is_clamped_to_50_mm(self):   # L5: whatever the page sends
        self.fake.reply("axis", "move", {})
        self.assertTrue(self.run_cmd("move", axis="z", distance=-120)["result"])
        self.assertEqual(self.sent("axis", "move")[-1]["data"], {"axis": 3, "move_type": 0, "distance": 50.0})
        self.assertIn("axis", self.run_cmd("move", axis="e", distance=1)["error"])

    def test_fan_light(self):
        self.assertTrue(self.run_cmd("set_fan", pct=150)["result"])
        self.assertEqual(wait(lambda: self.sent("fan", "setSpeed"))[0]["data"], {"fan_speed_pct": 100})
        time.sleep(0.2)
        self.assertFalse(self.sent("print", "update"))   # idle: fan/setSpeed only
        self.assertTrue(self.run_cmd("set_light", on=True)["result"])
        self.assertEqual(wait(lambda: self.sent("light", "control"))[0]["data"], {"type": 3, "status": 1, "brightness": 100})
        self.assertTrue(self.run_cmd("set_light", on=False)["result"])
        self.assertEqual(wait(lambda: self.sent("light", "control")[1:])[0]["data"], {"type": 3, "status": 0, "brightness": 0})

    def test_device_asks_net_statistics_and_assist(self):
        self.fake.reply("properties", "read", {"assistant_settings": [{"option": 0, "value": 1}, {"option": 3, "value": 0}]})
        self.fake.reply("info", "net", {"mac": "AA:BB"})
        self.fake.reply("info", "statistic-query", {"print_total_minutes": 90, "print_count": 4})
        self.assertEqual(self.run_cmd("device")["result"], {"sent": True, "assist": True})
        for kind in (("info", "net"), ("info", "statistic-query"), ("properties", "read")):
            self.assertIn("/web/", next(r["topic"] for r in self.fake.requests if r["msg"] and
                                        (r["msg"]["type"], r["msg"]["action"]) == kind), kind)
        data = wait(lambda: (lambda d: d if d["mac"] and d["stats"] and d["assist"] else None)(self.svc._data(self.conn)))
        self.assertEqual((data["mac"], data["stats"], data["assist"]),
                         ("AA:BB", {"print_minutes": 90, "print_count": 4}, {0: True, 3: False}))

    def test_device_without_answers_leaves_the_fields_empty(self):
        """A firmware that ignores the Workbench queries (2.0.2.8 may): nothing is guessed."""
        self.fake.send_ack = False
        self.assertEqual(self.run_cmd("device", timeout=12)["result"], {"sent": True, "assist": False})
        data = self.svc._data(self.conn)
        self.assertEqual((data["mac"], data["stats"], data["assist"]), ("", {}, None))

    def test_assist_writes_only_reported_options(self):
        self.fake.reply("properties", "read", {"assistant_settings": [{"option": 3, "value": 0}]})
        self.run_cmd("device")
        wait(lambda: self.svc._data(self.conn)["assist"])
        self.fake.reply("properties", "write", {"assistant_settings": [{"option": 3, "value": 1}]})
        self.assertEqual(self.run_cmd("assist", option="breakAlert", on=True)["result"], {"confirmed": True})
        self.assertEqual(self.sent("properties", "write")[0]["data"], {"assistant_settings": [{"option": 3, "value": 1}]})
        wait(lambda: self.svc._data(self.conn)["assist"] == {3: True})
        self.assertIn("did not report", self.run_cmd("assist", option="belt", on=True)["error"])
        self.assertIn("unknown", self.run_cmd("assist", option="nozzle", on=True)["error"])
        self.assertEqual(len(self.sent("properties", "write")), 1)

    def test_assist_auto_feed_sets_every_ace(self):
        self.assertTrue(self.run_cmd("assist", option="autoFeed", on=False)["result"])
        self.assertEqual(wait(lambda: self.sent("multiColorBox", "setAutoFeed"))[0]["data"],
                         {"multi_color_box": [{"id": 0, "auto_feed": 0}]})

    def test_writes_wait_for_the_device_queries(self):
        """While the read-only queries are out, an assist write or a rename is refused: their answers share topics."""
        self.fake.send_ack = False   # unanswered: the device command waits its full 5 s
        self.conn.state._v["assist"] = {3: False}
        rid = "dev"
        self.svc.submit(rid, "device", {})
        wait(lambda: self.sent("properties", "read"))
        for cmd, args in (("assist", {"option": "breakAlert", "on": True}), ("rename", {"name": "Shop"})):
            self.assertIn("still being read", self.run_cmd(cmd, **args)["error"], cmd)
        self.assertFalse(self.kinds() & {("properties", "write"), ("info", "setPrinterName")})
        wait(lambda: next((m for m in self.published if m.get("id") == rid), None), 12)

    def test_rename_not_confirmed_by_an_unrelated_info_report(self):
        self.fake.reply("info", "setPrinterName", {"printerName": "Shop"})
        self.fake.replies[("info", "setPrinterName")]["action"] = "report"   # what every info poll answers with
        self.assertEqual(self.run_cmd("rename", name="Shop", timeout=20)["result"], {"confirmed": False, "name": "Shop"})

    def test_rename(self):
        self.fake.reply("info", "setPrinterName", {"printerName": "Shop"})
        result = self.run_cmd("rename", name="  Shop   X ", timeout=15)["result"]
        self.assertEqual(result["name"], "Shop X")
        self.assertEqual(self.sent("info", "setPrinterName")[0]["data"], {"printerName": "Shop X"})
        for bad in ("", "   ", "x" * (service.NAME_MAX + 1), "é" * (service.NAME_MAX // 2 + 1), 'a"b', "<b>", "a\\b", "a\x00b"):
            self.assertIn("bytes (UTF-8)", self.run_cmd("rename", name=bad)["error"], repr(bad))
        self.assertEqual(len(self.sent("info", "setPrinterName")), 1)
        self.assertEqual(self.run_cmd("rename", name="é" * (service.NAME_MAX // 2), timeout=15)["result"]["name"], "é" * 16)   # 32 bytes

    def test_speed_needs_a_print(self):
        self.assertIn("running print", self.run_cmd("set_speed", mode=3)["error"])

    def test_objects_needs_a_print(self):
        self.assertIn("no print is running", self.run_cmd("objects")["error"])
        self.assertFalse(self.sent("file", "fileDetails"))

    def test_retract_with_nothing_loaded_says_so(self):
        """No slot given (the Device tab's unload) and nothing loaded: a plain reason, never "slot 0 does not exist"."""
        error = self.run_cmd("slot_retract")["error"]
        self.assertEqual(error, service.NOTHING_LOADED)
        self.assertFalse(self.sent("multiColorBox", "feedFilament"))

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
        self.assertEqual(self.run_cmd("pause")["result"], {"confirmed": True})
        self.assertEqual(self.sent("print", "pause")[0]["data"], {"taskid": "42"})
        self.fake.reply("print", "stop", {}, state="stoped")
        self.assertEqual(self.run_cmd("stop")["result"], {"confirmed": True})

    def test_printer_settings_refused_while_printing(self):
        """Print Assist and the printer's name change only on an idle printer."""
        self.conn.state._v["assist"] = {3: False}
        for cmd, args in (("assist", {"option": "breakAlert", "on": True}), ("assist", {"option": "autoFeed", "on": True}),
                          ("rename", {"name": "Shop"})):
            self.assertIn("printing", self.run_cmd(cmd, **args)["error"], cmd)
        self.assertFalse(self.kinds() & {("properties", "write"), ("info", "setPrinterName"), ("multiColorBox", "setAutoFeed")})

    def test_fan_while_printing_sends_set_speed_then_print_update(self):
        """fan/setSpeed (verified) is always sent; print/update (Anycubic's page, untested) only as a second message."""
        self.assertTrue(self.run_cmd("set_fan", pct=40)["result"])
        self.assertEqual(wait(lambda: self.sent("fan", "setSpeed"))[0]["data"], {"fan_speed_pct": 40})
        msg = wait(lambda: self.sent("print", "update"))[0]
        self.assertEqual(msg["data"], {"taskid": "42", "settings": {"fan_speed_pct": 40}})
        kinds = [(r["msg"]["type"], r["msg"]["action"]) for r in self.fake.requests if isinstance(r["msg"], dict)]
        self.assertLess(kinds.index(("fan", "setSpeed")), kinds.index(("print", "update")))

    def test_device_queries_never_sent_while_printing(self):
        self.assertIn("printing", self.run_cmd("device")["error"])
        self.assertFalse(self.kinds() & {("info", "net"), ("info", "statistic-query"), ("properties", "read")})

    def test_temperature_while_printing_uses_print_update(self):
        self.run_cmd("set_temp", nozzle=215.4)
        msg = wait(lambda: self.sent("print", "update"))[0]
        self.assertEqual(msg["data"], {"taskid": "42", "settings": {"target_nozzle_temp": 215}})
        self.assertIn("/web/", next(r["topic"] for r in self.fake.requests if r["msg"] is msg))

    def test_speed(self):
        self.assertIn("1 (quiet) to 3 (sport)", self.run_cmd("set_speed", mode=4)["error"])
        self.assertTrue(self.run_cmd("set_speed", mode=3)["result"])
        self.assertEqual(wait(lambda: self.sent("print", "update"))[0]["data"]["settings"], {"print_speed_mode": 3})

    def test_objects_of_the_running_file(self):
        self.fake.reply("file", "fileDetails", {"root": "local", "filename": "/a.gcode", "file_details": {"objects_skip_parts": ["A", {"name": "B"}, 7]}})
        self.fake.report("skip/report", {"type": "skip", "action": "update", "state": "success",
                                         "data": {"objects_skip_parts": ["A"]}})
        wait(lambda: self.conn.view()["skipped_objects"])
        result = self.run_cmd("objects")["result"]
        self.assertEqual(result, {"filename": "a.gcode", "objects": ["A", "B", "7"], "skipped": ["A"]})
        asked = self.sent("file", "fileDetails")[-1]["data"]
        self.assertEqual(asked["filename"], "a.gcode")

    def test_skip_checks_names_against_the_running_file(self):
        self.fake.reply("file", "fileDetails", {"root": "local", "filename": "/a.gcode", "file_details": {"objects_skip_parts": ["A", "B"]}})
        self.fake.reply("skip", "start", {})
        self.assertIn("not in a.gcode: Z", self.run_cmd("skip_objects", names=["B", "Z"])["error"])
        self.assertFalse(self.sent("skip", "start"))
        self.assertTrue(self.run_cmd("skip_objects", names=["B"])["result"])
        self.assertEqual(self.sent("skip", "start")[0]["data"], {"objects_skip_parts": ["B"]})

    def test_objects_without_an_answer(self):
        self.set_state("printing")   # the scripted info poll answers "free" otherwise
        self.fake.send_ack = False
        self.assertIn("did not answer the details of a.gcode", self.run_cmd("objects", timeout=15)["error"])
        self.fake.send_ack = True   # received, no report: told apart from "did not answer"
        self.assertIn("received the details of a.gcode but reported no result", self.run_cmd("objects", timeout=15)["error"])

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


class JobsMaterial(Base):
    """print_job refuses a filament sent to a slot of another material family, also when the slot changed during
    the upload (the check runs again under start_lock)."""

    def setUp(self):
        super().setUp()
        self.fake.print_start = "ok"

    def test_other_material_refused_before_upload(self):
        tray_petg = 1   # ACE0 slot 2 (PETG)
        with self.assertRaises(kobra.KobraError):
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [tray_petg], [{"colour": "#FF0000", "type": "PLA"}])
        self.assertEqual(self.fake.uploads, [])

    def test_slot_swapped_during_upload_refused_before_start(self):
        real = self.svc._data

        def stage(name):   # from now on the printer reports PETG in slot 1, as after a swap on the touchscreen
            if name == "start":
                self.svc._data = lambda conn=None: {**real(conn), "slots": [
                    {**s, "type": "PETG"} if s["global_index"] == 0 else s for s in real(conn)["slots"]]}
        with self.assertRaises(kobra.KobraError) as e:
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000", "type": "PLA"}],
                               stage=stage)
        self.assertIn("another material", str(e.exception))
        self.assertEqual(len(self.fake.uploads), 1)
        self.assertEqual(self.sent("print", "start"), [])

    def test_auto_feed_after_checks(self):
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000", "type": "PLA"}],
                           auto_feed=False)
        self.assertEqual(wait(lambda: self.sent("multiColorBox", "setAutoFeed"))[0]["data"]["multi_color_box"][0]["auto_feed"], 0)

    def test_auto_feed_not_sent_when_refused(self):
        with self.assertRaises(kobra.KobraError):
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [1], [{"colour": "#FF0000", "type": "PLA"}],
                               auto_feed=False)
        self.assertEqual(self.sent("multiColorBox", "setAutoFeed"), [])


class Jobs(Base):
    def setUp(self):
        super().setUp()
        self.fake.print_start = "ok"
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
        self.fake.reply("file", "fileDetails", {"root": "local", "filename": "/a.gcode", "file_details": {"thumbnail": "iVBORw0KGgo=", "objects_skip_parts": ["A"]}})
        self.fake.reply("file", "deleteBatch", {}, code=200)
        self.fake.print_start = "ok"
        self.assertEqual([r["name"] for r in self.run_cmd("files")["result"]["files"]], ["a.gcode", "b.gcode"])
        details = self.run_cmd("file_details", name="a.gcode")["result"]
        self.assertTrue(details["thumbnail"].startswith("data:image/png;base64,"))
        self.assertEqual((details["materials"], details["info"]["model_ok"]), ([], True))   # no paint_infos in this fake
        self.assertTrue(self.run_cmd("file_print", name="a.gcode", auto_leveling=True)["result"])
        self.assertEqual(start_mapping(self), [0, 1, 3, 3])   # the loaded ACE slots, Kobralink's auto mapping
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual((start["filename"], start["filesize"]), ("a.gcode", 10))
        self.assertIn("files", self.run_cmd("file_delete", names=["b.gcode"])["result"])
        self.assertIn("path separators", self.run_cmd("file_details", name="../x")["error"])


VIDEO = {"createTime": 1794838471, "duration": 6, "fileKey": "f" * 32, "fileSize": 109048,
         "file_image": "benchy-20261116215053_8_6.jpg", "filename": "benchy-20261116215053_8.mp4", "main_file_name": "benchy"}
ABORTED = {**VIDEO, "createTime": 1794000000, "duration": 0, "fileSize": 156, "filename": "cube-20261107_1.mp4",
           "main_file_name": "cube"}


class Videos(Base):
    """Time-lapse videos: the page's `videos` and `video_delete` commands (docs/architecture.md)."""

    def script(self):
        self.fake.reply("file", "listVideo", {"records": [ABORTED, VIDEO, {"filename": "../x.mp4"}, "junk"]})
        self.fake.reply("file", "deleteVideo", None, state="success")

    def test_list_newest_first_with_the_aborted_one_marked(self):
        self.script()
        self.assertEqual(self.run_cmd("videos")["result"], {"videos": [
            {"filename": "benchy-20261116215053_8.mp4", "name": "benchy", "created": 1794838471, "duration": 6,
             "size": 109048, "empty": False},
            {"filename": "cube-20261107_1.mp4", "name": "cube", "created": 1794000000, "duration": 0, "size": 156,
             "empty": True}]})
        self.assertEqual(self.sent("file", "listVideo")[0]["data"], {"page_num": 1, "page_size": 200, "path": "/", "keyword": ""})

    def test_delete_sends_one_named_video(self):
        self.script()
        self.assertEqual(self.run_cmd("video_delete", name="cube-20261107_1.mp4")["result"], {"deleted": "cube-20261107_1.mp4"})
        self.assertEqual([m["data"] for m in self.sent("file", "deleteVideo")], [{"path": "/", "filename": "cube-20261107_1.mp4"}])

    def test_a_name_that_is_not_a_plain_mp4_name_is_refused_before_the_printer(self):
        self.script()
        for bad in ("../x.mp4", "x/y.mp4", "x\\y.mp4", "a.gcode", "", ".mp4", "x" * 300 + ".mp4", 5, None, ["a.mp4"]):
            self.assertIn("error", self.run_cmd("video_delete", name=bad), repr(bad))
        self.assertIn("error", self.run_cmd("video_delete"))                       # no name at all
        self.assertIn("error", self.run_cmd("video_delete", names=["a.mp4"]))      # the file command's argument
        self.assertEqual(self.sent("file", "deleteVideo"), [])

    def test_what_the_printer_refuses_is_an_error_with_its_code(self):
        self.fake.reply("file", "listVideo", None, state="failed", code=10112)
        self.fake.reply("file", "deleteVideo", None, state="failed", code=10110)
        self.assertIn("10112", self.run_cmd("videos")["error"])
        self.assertIn("10110", self.run_cmd("video_delete", name="a.mp4")["error"])

    def test_nothing_else_is_sent(self):
        self.script()
        before = self.kinds()
        self.run_cmd("videos")
        self.run_cmd("video_delete", name="a.mp4")
        self.assertEqual(self.kinds() - before - READ_ONLY, {("file", "listVideo"), ("file", "deleteVideo")})


class VideosWhilePrinting(Videos):
    """Listing and deleting videos does not move the printer: both work during a print."""

    def setUp(self):
        super().setUp()
        self.set_state("printing")


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


class LoopSurvives(unittest.TestCase):
    """M1: no unexpected exception ends a printer's connection loop or a service thread."""

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        self.fake.reply("info", "query", {"urls": {"fileUploadurl": self.fake.upload_url}})
        self.fake.reply("print", "query", {}, state="free")
        self.fake.reply("multiColorBox", "getInfo", {"multi_color_box": [ACE0]})
        self.logs = []

    def service(self, fetch=kobra.fetch_credentials):
        svc = service.Service(lambda m: None, self.logs.append, cert_dir=tempfile.mkdtemp(), tls=lambda: None,
                              http_port=self.fake.http_port, mqtt_port=self.fake.mqtt_port, fetch=fetch,
                              camera_factory=FakeCamera)
        self.addCleanup(svc.close)
        return svc

    def test_deeply_nested_info_answer(self):
        self.fake.info_answer = b"[" * 200000
        conn = self.service().connection(self.fake.host)
        wait(lambda: conn.error)
        self.assertTrue(conn._thread.is_alive())
        self.fake.info_answer = None
        conn.retry()
        wait(lambda: conn.connected, 15)

    def test_any_exception_is_logged_and_retried(self):
        calls = []

        def fetch(host, port):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return kobra.fetch_credentials(host, port=port)
        conn = self.service(fetch).connection(self.fake.host)
        wait(lambda: conn.error)
        self.assertIn("RuntimeError", conn.error)
        conn.retry()
        wait(lambda: conn.connected, 15)
        self.assertTrue(any("RuntimeError: boom" in str(m) for m in self.logs))

    def test_retry_restarts_a_dead_loop(self):
        conn = self.service().connection(self.fake.host)
        wait(lambda: conn.connected)
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        conn._thread = dead
        conn.retry()
        self.assertTrue(conn._thread.is_alive())

    def test_monitor_survives_an_exception(self):
        published = []
        svc = self.service()
        svc.publish = published.append
        svc.set_target(service.Target(self.fake.host))
        wait(lambda: svc.connections[self.fake.host].connected)
        real, fail = svc._data, [True]

        def flaky(conn=None):
            if fail and fail.pop():
                raise RuntimeError("bad report")
            return real(conn)
        svc._data = flaky
        svc.touch(camera=False)
        wait(lambda: any(m.get("type") == "status" for m in published))
        self.assertTrue(svc.monitor.is_alive())


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed to generate throwaway certificates")
class PrinterCertificate(unittest.TestCase):
    """The printer's TLS certificate is remembered per address; a different one is shown, the connection kept."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        tls = make_tls_files(self.tmp)
        self.fake = FakeKobra(tls=tls).start()
        self.addCleanup(self.fake.stop)
        self.fake.reply("info", "query", {"project": {"state": "free"}})
        self.fake.reply("print", "query", {"taskid": "1"}, state="free")
        self.fake.reply("multiColorBox", "getInfo", {"multi_color_box": [ACE0]})
        self.ctx = lambda: certs.context(tls.client_cert, tls.client_key)
        with open(tls.server_cert) as f:
            self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()

    def connect(self):
        published, logs = [], []
        svc = service.Service(published.append, logs.append, cert_dir=self.tmp, tls=self.ctx, http_port=self.fake.http_port,
                              mqtt_port=self.fake.mqtt_port, camera_factory=FakeCamera)
        self.addCleanup(svc.close)
        svc.set_target(service.Target(self.fake.host))
        conn = svc.connections[self.fake.host]
        wait(lambda: conn.connected)
        return svc._data(conn), logs

    def test_first_connection_remembers_the_certificate(self):
        data, logs = self.connect()
        self.assertEqual(data["tls"], {"fingerprint": self.fingerprint, "changed_from": ""})
        data, _ = self.connect()
        self.assertEqual(data["tls"]["changed_from"], "")

    def test_a_different_certificate_is_reported_and_still_connects(self):
        with open(os.path.join(self.tmp, certs.PINS_FILE), "w") as f:
            json.dump({"printers": {self.fake.host: "ab" * 32}}, f)
        data, logs = self.connect()
        self.assertTrue(data["connected"])
        self.assertEqual(data["tls"], {"fingerprint": self.fingerprint, "changed_from": "ab" * 32})
        self.assertTrue(any("certificate" in line and "changed" in line for line in logs), logs)

    def test_the_agent_path_checks_the_pin_of_a_known_printer_warn_only(self):
        """N2: Print/Send/Device tab (service.call with no tab target) at an address in the address book: the pin is
        checked under that printer's identity; a different certificate is logged and shown, the session kept."""
        locate.Addresses(os.path.join(self.tmp, "addresses.json")).put("P", self.fake.host, "SERIAL-A", "")
        with open(os.path.join(self.tmp, certs.PINS_FILE), "w") as f:
            json.dump({"printers": {"id:SERIAL-A": "ab" * 32}}, f)
        logs = []
        svc = service.Service(lambda m: None, logs.append, cert_dir=self.tmp, tls=self.ctx, http_port=self.fake.http_port,
                              mqtt_port=self.fake.mqtt_port, camera_factory=FakeCamera,
                              addresses_path=os.path.join(self.tmp, "addresses.json"))
        self.addCleanup(svc.close)
        conn = svc.ready(self.fake.host, timeout=15)   # what the printer agent does
        self.assertEqual(conn.identity, "SERIAL-A")
        self.assertEqual(svc._data(conn)["tls"], {"fingerprint": self.fingerprint, "changed_from": "ab" * 32})
        self.assertTrue(any("certificate" in line and "changed" in line for line in logs), logs)

    def located_after_the_agent(self, pin):
        """The reviewer's case: the printer agent opens the session first (identity from the address book, no pin
        enforced); then the tab locates the same remembered printer with `pin` as its pinned certificate."""
        locate.Addresses(os.path.join(self.tmp, "addresses.json")).put("P", self.fake.host, "SERIAL-A", pin)
        published = []
        svc = service.Service(published.append, lambda m: None, cert_dir=self.tmp, tls=self.ctx,
                              http_port=self.fake.http_port, mqtt_port=self.fake.mqtt_port, camera_factory=FakeCamera,
                              addresses_path=os.path.join(self.tmp, "addresses.json"),
                              probe=lambda ip: {"ip": ip, "name": "KX", "model": "", "id": "SERIAL-A"})
        self.addCleanup(svc.close)
        conn = svc.ready(self.fake.host, timeout=15)   # the agent's Print/Send path
        svc.set_target(service.Target("", preset_key="P"))
        svc._join_locators(30)
        return svc, conn, published

    def test_a_pin_given_to_an_open_session_that_does_not_match_closes_it(self):
        svc, conn, published = self.located_after_the_agent("ab" * 32)
        wait(lambda: svc.target.host == "" and getattr(svc.locate_error, "candidates", None), 15)
        self.assertEqual(conn.mismatch, self.fingerprint)
        wait(lambda: not conn.connected and not conn._thread.is_alive(), 15)
        self.assertNotIn(self.fake.host, svc.connections)
        self.assertEqual(svc.generation, 2)   # the tab's selection, then the impostor refused
        self.assertTrue(svc.locate_error.candidates[0]["different"])
        wait(lambda: {"type": "selection_changed"} in published, 15)   # published right after the offer is set

    def test_a_pin_given_to_an_open_session_that_matches_keeps_it(self):
        svc, conn, _ = self.located_after_the_agent(self.fingerprint)
        self.assertIs(svc.connections[self.fake.host], conn)
        self.assertTrue(conn.connected)
        self.assertEqual((conn.mismatch, svc.target.host, svc.generation), ("", self.fake.host, 1))

    def test_plain_session_reports_none(self):
        self.assertEqual(service.status_data(kobra.State().view())[0].get("tls"), None)


class CameraNeedsFfmpeg(Base):
    """No ffmpeg: the camera is never started (no reader thread failing every second); with it, it is."""

    def check(self, found):
        with mock.patch.object(service.requirements, "check_ffmpeg",
                               return_value=service.requirements.item("ffmpeg", "ok" if found else "missing", found)), \
                mock.patch.object(service.requirements, "check_anycubic_slicer",
                                  return_value=service.requirements.item("anycubic_slicer", "missing")):
            self.svc.check_requirements("")
            wait(lambda: not self.svc.requirements.checking)
        return wait(lambda: [m for m in self.published if m.get("type") == "requirements" and not m["checking"]])[-1]

    def test_missing_ffmpeg_never_starts_the_camera(self):
        msg = self.check("")
        self.assertEqual(msg["items"][0], {"id": "ffmpeg", "state": "missing", "details": ""})
        self.svc.touch(camera=True)
        time.sleep(0.6)   # the monitor ticks every 0.1 s
        self.assertNotIn("start", self.svc.camera.calls)
        self.assertFalse([m for m in self.published if m.get("type") == "camera_error"])

    def test_before_the_check_the_camera_looks_for_ffmpeg_itself(self):
        self.svc.target.ffmpeg_path = "/my/ffmpeg"
        self.svc.touch(camera=True)
        wait(lambda: "start" in self.svc.camera.calls)
        self.assertIn(("ffmpeg", "/my/ffmpeg"), self.svc.camera.calls)
        self.svc.camera.on_error("no_ffmpeg", "ffmpeg was not found")   # its one lookup failed
        time.sleep(0.3)
        starts = self.svc.camera.calls.count("start")
        time.sleep(0.6)
        self.assertEqual(self.svc.camera.calls.count("start"), starts)   # not started again and again

    def test_requirements_reach_the_page_through_the_service_publish(self):
        """The checker thread's answer goes out through Service.publish, the path every worker-thread message takes."""
        threads, publish = [], self.svc.publish
        self.svc.publish = lambda m: (threads.append((m.get("type"), threading.current_thread().name)), publish(m))
        self.check("")
        self.assertIn(("requirements", "kobracontrol-requirements"), threads)

    def test_found_ffmpeg_starts_the_camera_with_that_path(self):
        self.check("/opt/ff/ffmpeg")
        self.svc.touch(camera=True)
        wait(lambda: "start" in self.svc.camera.calls)
        self.assertIn(("ffmpeg", "/opt/ff/ffmpeg"), self.svc.camera.calls)

    def test_ffmpeg_gone_mid_session_is_marked_missing_and_not_restarted(self):
        self.check("/opt/ff/ffmpeg")
        self.svc.touch(camera=True)
        wait(lambda: "start" in self.svc.camera.calls)
        self.svc.camera.on_error("no_ffmpeg", "ffmpeg was not found")   # the reader found it gone and ended
        self.assertEqual(self.svc.requirements.items()[0]["state"], "missing")
        self.assertEqual(self.svc.requirements.ffmpeg(), "")
        time.sleep(0.3)
        starts = self.svc.camera.calls.count("start")
        time.sleep(0.6)
        self.assertEqual(self.svc.camera.calls.count("start"), starts)   # the monitor stopped starting it
        last = [m for m in self.published if m.get("type") == "requirements"][-1]
        self.assertEqual(last["items"][0]["state"], "missing")   # the page is told at once

    def test_a_recheck_keeps_a_running_camera_running(self):
        self.check("/opt/ff/ffmpeg")
        self.svc.touch(camera=True)
        wait(lambda: "start" in self.svc.camera.calls)
        gate, seen = threading.Event(), len(self.svc.camera.calls)
        self.addCleanup(gate.set)
        slow = lambda s: gate.wait(10) and service.requirements.item("ffmpeg", "ok", "/opt/ff/ffmpeg")
        with mock.patch.object(service.requirements, "check_ffmpeg", side_effect=slow), \
                mock.patch.object(service.requirements, "check_anycubic_slicer",
                                  return_value=service.requirements.item("anycubic_slicer", "missing")):
            self.svc.check_requirements("", force=True)   # a Settings save
            self.assertTrue(self.svc.requirements.checking)
            self.assertEqual(self.svc.requirements.ffmpeg(), "/opt/ff/ffmpeg")   # the last result stays meanwhile
            time.sleep(0.5)
            gate.set()
            wait(lambda: not self.svc.requirements.checking)
        time.sleep(0.3)
        self.svc.touch(camera=True)
        self.assertNotIn("stop", self.svc.camera.calls[seen:])   # never switched off while checking

    def test_spoolman_and_agent_in_the_message(self):
        msg = self.check("")
        items = {i["id"]: i for i in msg["items"]}
        self.assertEqual(items["spoolman"], {"id": "spoolman", "state": "ok", "details": "http://spoolman.invalid"})
        self.assertEqual(items["printer_agents"]["state"], "missing")   # not detected


class CameraPrinterGone(Base):
    """The session can be replaced (printer None) between the connected check and the capture thread."""

    class Swapped:
        host, connected, printer = "127.0.0.1", True, None

        def view(self):
            return {"camera_url_rev": 0, "connected": True, "camera_url": ""}

    def test_camera_tick_with_no_printer(self):
        errors = []
        old = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_value)
        self.addCleanup(setattr, threading, "excepthook", old)
        target = service.Target("swapped")
        self.svc.connections["swapped"] = self.Swapped()
        self.addCleanup(self.svc.connections.pop, "swapped", None)
        self.svc._camera_tick(target)
        time.sleep(0.2)
        self.assertEqual(errors, [])


class CameraTurnedOn(Base):
    """camera_enabled is only whether the page turns the camera on by itself (settings default False). Pressing
    Turn on must start the reader anyway, else the page waits on "Starting the camera…" forever."""

    def test_turn_on_starts_the_camera_with_the_default_off(self):
        self.svc.target.camera_enabled = False
        self.svc.touch(camera=True)
        wait(lambda: "start" in self.svc.camera.calls)


class CameraHost(Base):
    """M2: a stream URL that does not point at the printer itself never reaches ffmpeg."""

    def test_foreign_stream_host_dropped(self):
        self.assertEqual(self.svc._camera_url(), "rtsp://127.0.0.1:1/live")
        self.fake.report("info/report", {"type": "info", "action": "update", "state": "success",
                                         "data": {"urls": {"rtspUrl": "rtsp://203.0.113.9/live"}}})
        wait(lambda: self.conn.view()["camera_url"] == "rtsp://203.0.113.9/live")
        self.assertEqual(self.svc._camera_url(), "")
        self.assertEqual(service.camera_url_for({"connected": True, "camera_url": "http://169.254.169.254/x"},
                                                "127.0.0.1"), "")
        self.assertTrue(any("203.0.113.9" in str(m) for m in self.logs))


class SliceInfoCap(Base):
    """L2: zip members are read only after their declared size is checked."""

    def test_huge_slice_info_is_ignored(self):
        self.fake.print_start = "ok"
        path = os.path.join(self.tmp, "big.3mf")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Metadata/plate_1.gcode", GCODE)
            z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="index" value="1"/>'
                       '<filament id="1" used_g="5"/></plate>' + " " * (9 * 1024 * 1024) + "</config>")
        with zipfile.ZipFile(path) as z:
            self.assertEqual(jobs._plate_weights(z, 1), {})
        self.svc.print_job(self.fake.host, path, 1, "big", [0], [{"colour": "#FF0000"}])
        self.assertEqual(self.fake.uploads[0]["data"], GCODE)


class Bounded(Base):
    """L6: one certificate search (and one stock or usage job) at a time; page paths resolved first."""

    def test_one_certificate_search_at_a_time(self):
        gate = threading.Event()
        real = service.certs.find
        service.certs.find = lambda paths, workdir=None: gate.wait(5) and real(paths, workdir=workdir)
        self.addCleanup(setattr, service.certs, "find", real)
        self.svc.submit("a", "find_certificate", {"path": self.tmp})
        time.sleep(0.1)
        before = threading.active_count()
        self.svc.submit("b", "find_certificate", {"path": self.tmp})
        reply = wait(lambda: next((m for m in self.published if m.get("id") == "b"), None))
        self.assertIn("already running", reply["error"])
        self.assertEqual(threading.active_count(), before)
        gate.set()
        wait(lambda: next((m for m in self.published if m.get("id") == "a"), None))
        self.assertIn("error", self.run_cmd("find_certificate", path=self.tmp))   # free again (nothing found)

    def test_stock_bounded(self):
        gate = threading.Event()
        self.svc.cmd_stock = lambda refresh=False: gate.wait(5)
        self.svc.submit("s1", "stock", {})
        self.svc.submit("s2", "stock", {})
        reply = wait(lambda: next((m for m in self.published if m.get("id") == "s2"), None))
        self.assertIn("already running", reply["error"])
        gate.set()

    def test_page_path_must_exist(self):
        reply = self.run_cmd("find_certificate", path=os.path.join(self.tmp, "nope", "..", "missing"))
        self.assertIn("does not exist", reply["error"])


class FeedAckAnyBox(Base):
    """M3: a type-3 feedFilament for EVERY box reporting feed status 10/11 (Kobralink printer-bridge.ts:820-830,
    KX-Bridge bridge_ams.py:426-440), once per event, two seconds later."""

    def box_report(self, status, slot=2, box_id=0):
        box = dict(ACE0, id=box_id, feed_status={"current_status": status, "slot_index": slot, "type": 1})
        self.fake.report("multiColorBox/report", {"type": "multiColorBox", "action": "update", "state": "success",
                                                  "data": {"multi_color_box": [box]}})

    def acks(self):
        return [m["data"]["multi_color_box"][0] for m in self.sent("multiColorBox", "feedFilament")
                if m["data"]["multi_color_box"][0]["feed_status"].get("type") == 3]

    def test_touchscreen_feed_is_acknowledged_once(self):
        self.box_report(10)
        started = time.monotonic()
        ack = wait(lambda: self.acks(), 6)[0]
        self.assertGreaterEqual(time.monotonic() - started, 1.5)
        self.assertEqual(ack, {"id": 0, "feed_status": {"slot_index": 2, "type": 3}})
        for _ in range(3):   # the status lingers: no repeat
            self.box_report(10)
            time.sleep(0.3)
        time.sleep(2.5)
        self.assertEqual(len(self.acks()), 1)
        self.box_report(0)
        self.box_report(11)   # a new event
        wait(lambda: len(self.acks()) == 2, 6)


class PausedTemperature(Base):
    def test_paused_uses_tempature_set(self):   # M1: print/update only while exactly printing
        self.set_state("paused")
        self.assertTrue(self.run_cmd("set_temp", bed=55)["result"])
        msg = wait(lambda: self.sent("tempature", "set"))[0]
        self.assertEqual(msg["data"]["target_hotbed_temp"], 55)
        self.assertFalse(self.sent("print", "update"))


class NothingSent(Base):
    def test_set_temp_reports_failure_when_nothing_was_sent(self):   # L1
        self.conn.printer.set_idle_temperature = lambda nozzle=None, bed=None: False
        self.assertIn("nothing was sent", self.run_cmd("set_temp", nozzle=200)["error"])


class PrintStartLock(Base):
    def test_check_and_start_are_serialised(self):   # L6
        self.fake.print_start = "ok"
        result = {}
        with self.conn.start_lock:
            t = threading.Thread(target=lambda: result.setdefault("r", self._job()), daemon=True)
            t.start()
            wait(lambda: self.fake.uploads)
            time.sleep(0.3)
            self.set_state("printing")   # another start won the race while this job waited
        t.join(10)
        self.assertIsInstance(result["r"], kobra.KobraError)
        self.assertFalse(self.sent("print", "start"))

    def _job(self):
        try:
            return self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000"}])
        except kobra.KobraError as e:
            return e


class SlowCamera(FakeCamera):
    """A camera whose stop() blocks until the test releases it."""
    gate = None

    def stop(self):
        self.gate.wait(30)


class NoJoinsOnCallers(Base):
    """M4: page messages and agent callbacks never wait for teardown."""

    def test_fast(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.svc.camera = SlowCamera(None, None)
        self.svc.camera.gate = gate   # stop() blocks until the end of the test
        for call in (lambda: self.svc.touch(camera=False), self.svc.clear_target,
                     lambda: self.svc.set_target(service.Target("127.0.0.2")), lambda: self.svc.release("127.0.0.2")):
            caller = threading.Thread(target=call)
            caller.start()
            caller.join(20)
            self.assertFalse(caller.is_alive())   # returned while the camera's stop() is still blocked
            self.assertFalse(gate.is_set())


class ReconnectStorm(unittest.TestCase):
    """H1: a session dropped right after it opens must not turn into a reconnect loop."""

    def test_backoff_after_short_sessions(self):
        fake = FakeKobra().start()
        self.addCleanup(fake.stop)
        fake.reply("info", "query", {})
        fake.reply("print", "query", {}, state="free")
        fake.reply("multiColorBox", "getInfo", {"multi_color_box": []})
        stop = threading.Event()

        def dropper():
            seen = 0
            while not stop.is_set():
                if len(fake.client_ids) > seen:
                    seen = len(fake.client_ids)
                    time.sleep(0.05)
                    fake.drop_clients()
                time.sleep(0.01)
        threading.Thread(target=dropper, daemon=True).start()
        self.addCleanup(stop.set)
        svc = service.Service(lambda m: None, lambda m: None, cert_dir=tempfile.mkdtemp(), tls=lambda: None,
                              http_port=fake.http_port, mqtt_port=fake.mqtt_port, camera_factory=FakeCamera)
        self.addCleanup(svc.close)
        conn = svc.connection(fake.host)
        time.sleep(5)
        self.assertLessEqual(len(fake.client_ids), 3)   # waits of 2 s then 4 s, never a tight loop
        self.assertGreaterEqual(len(fake.client_ids), 2)
        self.assertIn("another app connected to the printer", conn.error)   # says what happened, not only "lost"


class CannotConnect(unittest.TestCase):
    """The printer's HTTP side answers (credentials come back) but its MQTT port does not: the page's hello and
    its once-a-second status must not cut the retry delay short; only the user's Retry does, and it answers at
    that attempt's failure instead of after CONNECT_WAIT."""

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        closed = socket.create_server(("127.0.0.1", 0))
        self.mqtt_port = closed.getsockname()[1]
        closed.close()
        self.attempts, self.published = [], []

        def fetch(host, port):
            self.attempts.append(time.monotonic())
            return kobra.fetch_credentials(host, port=port)
        self.fetch = fetch

    def service(self, **kw):
        # A first retry delay far longer than any test: an attempt beyond the first one can only come from a
        # reset of the backoff, never from the clock (no wall-clock assertions).
        patcher = mock.patch.object(connection, "RETRY_FIRST", 60.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        svc = service.Service(self.published.append, lambda m: None, cert_dir=tempfile.mkdtemp(),
                              http_port=self.fake.http_port, mqtt_port=self.mqtt_port, fetch=self.fetch,
                              camera_factory=FakeCamera, **{"tls": lambda: None, **kw})
        self.addCleanup(svc.close)
        svc.set_target(service.Target(self.fake.host))
        return svc, svc.connections[self.fake.host]

    def connect(self, svc, timeout=3.0, **args):
        rid = "c%d" % len(self.published)
        svc.submit(rid, "connect", args)
        return wait(lambda: next((m for m in self.published if m.get("id") == rid), None), timeout)

    def test_hello_answers_the_last_error_at_once_and_keeps_the_backoff(self):
        svc, conn = self.service()
        wait(lambda: conn.failures)
        for _ in range(10):   # the 0.2.0 page said hello again on every status
            reply = self.connect(svc, timeout=3.0)
            self.assertIn("no answer on the printer's MQTT port", reply["error"])
            svc.touch(camera=False)
        self.assertEqual(len(self.attempts), 1)   # still in the first (60 s) wait: nothing reset it

    def test_retry_tries_now_and_answers_at_its_failure(self):
        svc, conn = self.service()
        wait(lambda: conn.failures)
        reply = self.connect(svc, timeout=service.CONNECT_WAIT - 1, retry=True)   # answered at the failure
        self.assertEqual(len(self.attempts), 2)   # at once, not after the 60 s delay
        self.assertIn("no answer on the printer's MQTT port", reply["error"])

    def test_status_and_hellos_do_not_reset_the_growing_delay(self):
        svc, conn = self.service()
        wait(lambda: conn.failures)
        for _ in range(10):
            self.connect(svc, timeout=3.0)
            svc.touch(camera=False)
            svc._push_status(svc.target, svc.generation)
        self.assertEqual(len(self.attempts), 1)
        self.assertEqual([m.get("type") for m in self.published if m.get("type") == "notice"], [])

    def test_failed_attempts_never_search_the_slicer_install(self):
        """Every attempt loads the saved or bundled certificate; only Find certificate reads Anycubic Slicer
        Next's folders (each read there can be an OrcaSlicer sandbox block or prompt)."""
        with mock.patch.object(certs, "find", side_effect=AssertionError("scan")) as find, \
                mock.patch.object(certs, "default_locations", side_effect=AssertionError("scan")) as where:
            _, conn = self.service(tls=connection.tls_from(tempfile.mkdtemp()))
            for count in range(1, 4):
                wait(lambda n=count: conn.failures >= n)
                conn.retry()
        self.assertGreaterEqual(len(self.attempts), 3)
        self.assertIn("no answer on the printer's MQTT port", conn.error)
        find.assert_not_called()
        where.assert_not_called()


class DeniedExplained(unittest.TestCase):
    def test_denied_message(self):   # H2
        error = kobra.KobraError("printer not reachable at 10.0.0.5 (denied)", code="denied")
        text = connection._explain("10.0.0.5", error)
        self.assertIn("Allow kobracontrol to reach 10.0.0.5", text)
        self.assertIn("press Retry", text)
        self.assertIn("restart OrcaSlicer", text)
        self.assertNotIn("Allow kobracontrol", connection._explain("10.0.0.5", kobra.KobraError("timed out")))

    def test_retry_attempts_at_once(self):
        calls = []

        def fetch(host, port):
            calls.append(time.monotonic())
            raise kobra.KobraError("denied", code="denied")
        conn = connection.Connection("10.0.0.5", lambda: None, lambda m: None, fetch=fetch).start()
        self.addCleanup(conn.stop)
        wait(lambda: calls)
        conn.retry()
        wait(lambda: len(calls) >= 2, 1.0)   # not after the 2 s backoff


class NameChangeMidPrint(Base):
    """MEDIUM-1: printer name and Spoolman address are not part of what selects the printer: saving them during a
    print keeps the connection, the session and the generation."""
    state = "printing"

    def test_name_and_spoolman_change_apply_in_place(self):
        gen, conn, sessions = self.svc.generation, self.conn, len(self.fake.client_ids)
        self.svc.set_target(service.Target(self.fake.host, name="Lab KX", spoolman_url="http://other:7912"), retry=True)
        self.assertEqual((self.svc.target.name, self.svc.target.spoolman_url), ("Lab KX", "http://other:7912"))
        self.assertIs(self.svc.connections[self.fake.host], conn)
        self.assertEqual(self.svc.generation, gen)
        time.sleep(0.5)
        self.assertTrue(conn.connected)
        self.assertEqual(len(self.fake.client_ids), sessions)
        self.svc.set_target(service.Target("localhost"))   # the address does select the printer
        self.assertEqual(self.svc.generation, gen + 1)


class RefusedInfoPort(unittest.TestCase):
    """The owner's case with the address in Settings: something answers at the address, but port 18910 is refused
    at once. Every attempt fails in microseconds, so only the backoff keeps it calm."""

    def setUp(self):
        closed = socket.create_server(("127.0.0.1", 0))
        self.port = closed.getsockname()[1]
        closed.close()
        self.attempts, self.published = [], []

        def fetch(host, port):
            self.attempts.append(time.monotonic())
            return kobra.fetch_credentials(host, port=port, timeout=10)   # Windows: a refused connect takes ~2 s
        self.delays = []
        real = connection.Connection._backoff

        def backoff(conn, delay):   # the delays the loop waits, recorded instead of timed
            self.delays.append(delay[0])
            return real(conn, delay)
        for patcher in (mock.patch.object(connection.Connection, "_backoff", backoff),
                        mock.patch.object(connection, "RETRY_FIRST", 0.05)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.svc = service.Service(self.published.append, lambda m: None, cert_dir=tempfile.mkdtemp(), tls=lambda: None,
                                   http_port=self.port, mqtt_port=self.port, fetch=fetch, camera_factory=FakeCamera)
        self.addCleanup(self.svc.close)

    def test_says_what_answers_and_where_the_address_came_from_and_backs_off(self):
        self.svc.set_target(service.Target("127.0.0.1"))
        conn = self.svc.connections["127.0.0.1"]
        wait(lambda: conn.failures)
        self.assertIn("Something answers at 127.0.0.1, but it is not a Kobra X in LAN mode", conn.error)
        self.assertIn("not a bridge such as Kobralink", conn.error)
        self.assertIn("LAN mode", conn.error)
        self.assertIn("The address comes from Settings > Printer address.", conn.error)
        self.assertTrue(conn.http_failed)
        waiting = conn._retry.wait

        def push_while_waiting(timeout):   # a status published during the backoff wait, whatever the timing
            self.svc._push_status(self.svc.target, self.svc.generation)
            return waiting(timeout)
        conn._retry.wait = push_while_waiting
        offline = wait(lambda: next((m for m in self.published if m.get("type") == "offline" and m.get("retry_at")), None), 60)
        self.assertGreater(offline["retry_at"], 0)   # the page shows when the next try is
        wait(lambda: len(self.delays) >= 5, 60)
        self.assertEqual(self.delays[:5], [0.05, 0.1, 0.2, 0.4, 0.8])   # each failure doubles the wait: never a spin

    def test_save_retries_at_once_with_a_fresh_delay(self):
        self.svc.set_target(service.Target("127.0.0.1"))
        conn = self.svc.connections["127.0.0.1"]
        wait(lambda: len(self.delays) >= 5, 60)
        with mock.patch.object(connection, "RETRY_FIRST", 0.07):   # a value only a fresh start can produce
            before = len(self.delays)
            self.svc.set_target(service.Target("127.0.0.1"), retry=True)   # Save with the same address
            wait(lambda: 0.07 in self.delays[before:], 60)
        self.assertTrue(conn._thread.is_alive())

    def test_save_with_a_new_address_stops_the_old_loop(self):
        self.svc.set_target(service.Target("127.0.0.1"))
        old = self.svc.connections["127.0.0.1"]
        self.svc.set_target(service.Target("localhost"), retry=True)
        wait(lambda: "127.0.0.1" not in self.svc.connections and not old._thread.is_alive(), 5)
        self.assertIn("localhost", self.svc.connections)


class SpoolmanFromSpooler(unittest.TestCase):
    def test_usage_is_booked_unless_spooler_books_this_printer_in_the_same_spoolman(self):
        """M-C. Spooler 0.26 reads only slots from a Kobra X (no print state), so it never books its prints, and
        Kobra Control books them, also in Spooler's Spoolman. A Spooler that declares it books Anycubic prints
        (presence provides.books contains "anycubic") makes Kobra Control stand down in that Spoolman."""
        books = []
        target = service.Target("10.0.0.5")
        target.spooler_origin, target.spooler_books = (lambda: "http://box:7912"), (lambda: bool(books))
        self.assertTrue(target.spoolman_report_usage)                     # fallback, Spooler does not book
        books.append("anycubic")
        self.assertFalse(target.spoolman_report_usage)                    # same Spoolman, Spooler books
        own = service.Target("10.0.0.5", spoolman_url="http://other:7912")
        own.spooler_origin, own.spooler_books = (lambda: "http://box:7912"), (lambda: True)
        self.assertTrue(own.spoolman_report_usage)                        # another Spoolman: no double count
        self.assertEqual(service.Service._usage_owner(target), "spooler")
        self.assertEqual(service.Service._origin_check(target, "http://box:7912"), "fallback")
        self.assertIs(service.Service._origin_check(own, "http://box:7912"), False)   # the real comparison


    def test_spooler_address_is_used_when_none_is_set_here(self):
        class Peers:
            origin = "http://box:7912"

            def spooler(self):
                return {"origin": self.origin}
        svc = service.Service(lambda m: None, lambda m: None, cert_dir=tempfile.mkdtemp(), tls=lambda: None,
                              camera_factory=FakeCamera)
        self.addCleanup(svc.close)
        svc.peers = Peers()
        with mock.patch.object(svc, "connection"):
            svc.set_target(service.Target("10.0.0.5"))
            self.assertEqual((svc.target.spoolman_url, svc.target.spoolman_source), ("http://box:7912", "spooler"))
            svc.set_target(service.Target("10.0.0.5", spoolman_url="http://mine:7912"))
            self.assertEqual((svc.target.spoolman_url, svc.target.spoolman_source), ("http://mine:7912", "settings"))
            Peers.origin = ""
            svc.set_target(service.Target("10.0.0.5"))
            self.assertEqual((svc.target.spoolman_url, svc.target.spoolman_source), ("", ""))


class Features(Base):
    """Print options the printer says it does not support (info/report features) are never sent as on."""

    def setUp(self):
        super().setUp()
        self.fake.print_start = "ok"
        self.conn.state._v["features"] = {"auto_leveling_support": False, "vibration_compensation_support": True}

    def test_print_job_drops_unsupported_options(self):
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000"}],
                           {"auto_leveling": True, "vibration_compensation": True})
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["auto_leveling"], task["vibration_compensation"]), (0, 1))

    def test_file_print_drops_unsupported_options(self):
        self.fake.reply("file", "listLocal", {"records": [{"filename": "a.gcode", "size": 1, "timestamp": 1}]}, code=200)
        self.run_cmd("file_print", name="a.gcode", auto_leveling=True, vibration_compensation=True)
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["auto_leveling"], task["vibration_compensation"]), (0, 1))

    def test_file_print_flow_calibration_and_timelapse(self):
        self.fake.reply("file", "listLocal", {"records": [{"filename": "a.gcode", "size": 1, "timestamp": 1}]}, code=200)
        self.conn.state._v["features"] = {"flow_calibration_support": True, "camera_timelapse_support": False}
        self.run_cmd("file_print", name="a.gcode", flow_calibration=True, timelapse=True)
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["flow_calibration"], task["timelapse"]["status"]), (1, 0))   # no time-lapse support

    def test_print_job_flow_calibration_and_timelapse(self):
        self.conn.state._v["features"] = {"flow_calibration_support": True, "camera_timelapse_support": True}
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000"}],
                           {"auto_leveling": False, "vibration_compensation": False, "flow_calibration": True,
                            "timelapse": True})
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["flow_calibration"], task["timelapse"]), (1, {"status": 1, "count": 0, "type": 64}))

    def test_slots_carry_percent(self):
        box = dict(ACE0, slots=[dict(ACE0["slots"][0], consumables_percent=42)] + ACE0["slots"][1:])
        self.fake.report("multiColorBox/report", {"type": "multiColorBox", "action": "update", "state": "success",
                                                  "data": {"multi_color_box": [box]}})
        wait(lambda: self.svc._data(self.conn)["slots"][0]["percent"] == 42)


class ReplyOutcomes(Base):
    """The printer acks every request on <deviceId>/response and answers later on <type>/report (fw 2.0.2.8).
    Three outcomes are told apart: success, the printer's failure (code and msg), received but no result."""

    def setUp(self):
        super().setUp()
        self.set_state("printing")

    def test_success(self):
        self.fake.reply("print", "pause", {})
        self.assertEqual(self.run_cmd("pause")["result"], {"confirmed": True})

    def test_failure_carries_code_and_msg(self):
        self.fake.reply("print", "pause", None, state="failed", code=10500, msg="cannot pause now")
        error = self.run_cmd("pause")["error"]
        self.assertIn("10500", error)
        self.assertIn("cannot pause now", error)

    def test_urgent_received_without_result_is_not_an_error(self):
        self.fake.ack_only = True
        for cmd in ("pause", "stop"):
            self.assertEqual(self.run_cmd(cmd, timeout=20)["result"], {"confirmed": False}, cmd)

    def test_no_ack_at_all_is_an_error(self):
        self.fake.send_ack = False
        self.fake.ack_only = True
        self.assertIn("did not answer", self.run_cmd("pause", timeout=20)["error"])

    def test_skip_received_without_result_is_an_error(self):
        self.fake.reply("file", "fileDetails", {"root": "local", "filename": "/a.gcode", "file_details": {"objects_skip_parts": ["A"]}})
        self.fake.reply("skip", "start", {})
        self.run_cmd("objects")
        self.fake.ack_only = True
        self.assertIn("reported no result", self.run_cmd("skip_objects", names=["A"], timeout=20)["error"])

    def test_another_clients_report_is_not_our_answer(self):
        """A pause report triggered by someone else before ours was sent must not count as our success."""
        self.fake.report("print/report", {"type": "print", "action": "pause", "state": "done", "code": 200,
                                          "data": {"taskid": "42"}})
        time.sleep(0.2)
        self.set_state("printing")
        self.fake.reply("print", "pause", None, state="failed", code=1, msg="refused")
        self.assertIn("refused", self.run_cmd("pause")["error"])


class HomingInProgress(Base):
    def test_home_acknowledged_without_result_is_in_progress(self):
        self.fake.ack_only = True
        printer = self.conn.printer   # the real 90 s homing wait, shortened for the test
        printer.move_axis = lambda axis, move_type, distance=0: printer.request(
            "axis", "move", {"axis": axis, "move_type": move_type, "distance": distance}, 1)
        self.assertEqual(self.run_cmd("home", axes="xyz")["result"], {"confirmed": False})

    def test_busy_blocks_move_heat_and_print(self):
        # Homing as the printer reports it: info state "busy" with no project (a print/report state during a
        # job is a job phase, not "busy").
        self.fake.report("info/report", {"type": "info", "action": "report", "state": "done", "code": 200,
                                         "data": {"state": "busy", "project": None}})
        wait(lambda: self.conn.view()["state"] == "busy")
        can = self.svc._data(self.conn)["can"]
        self.assertEqual((can["move"], can["heat"], can["print"]), (False, False, False))
        self.assertIn("busy", self.run_cmd("move", axis="x", distance=1)["error"])


class AbnormalEnd(Base):
    """Real fw 2.0.2.8: print/start answered "done", then print/report stop/stoped code 10111 ~1 s later."""

    def script_abnormal_end(self):
        self.fake.print_start = "abnormal"   # start/checking, start/printing, stop/stoped code 10111

    def test_print_ending_right_after_start_fails_the_job(self):
        self.script_abnormal_end()
        with self.assertRaisesRegex(kobra.KobraError, r"ended the print at once \(code 10111\): abnormal end of task"):
            self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0], [{"colour": "#FF0000"}])

    def test_tab_file_print_fails_too(self):
        self.script_abnormal_end()
        self.fake.reply("file", "listLocal", {"records": [{"filename": "a.gcode", "size": 1, "timestamp": 1}]})
        self.assertIn("abnormal end of task", self.run_cmd("file_print", name="a.gcode", timeout=15)["error"])

    def test_normal_start_succeeds(self):
        self.fake.print_start = "ok"
        self.assertEqual(self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0],
                                            [{"colour": "#FF0000"}]), "cube.gcode")


def job_report(test, state, code=200, filename="/cube.gcode"):
    """A print/report as firmware 2.0.2.8 sends during our job (action "start", taskid "-1")."""
    test.fake.report("print/report", {"type": "print", "action": "start", "state": state, "code": code,
                                      "data": {"taskid": "-1", "filename": filename, "progress": 50}})


class LiveJob(Base):
    """The finished live print (reports-print.jsonl): states, usage booking, busy info reports."""

    def setUp(self):
        super().setUp()
        self.fake.print_start = "ok"
        FakeSpoolman.used, FakeSpoolman.locations = [], {7: "Anycubic Kobra X S1"}
        self.svc.cmd_spools = lambda: None
        self.svc.bindings = {0: 7}

    def print_cube(self):
        self.svc.print_job(self.fake.host, make_3mf(self.tmp), 1, "cube", [0, 1],
                           [{"colour": "#FF0000", "type": "PLA"}, {"colour": "#0000FF", "type": "PETG"}])

    def test_finished_books_usage_once(self):
        self.print_cube()
        job_report(self, "printing")
        wait(lambda: self.conn.view()["state"] == "printing")
        time.sleep(1.2)   # the tracker sees the job printing
        job_report(self, "finished")
        wait(lambda: FakeSpoolman.used, 10)
        self.assertEqual(FakeSpoolman.used, [(7, 3.5)])   # slot 0 is bound; slot 1 is not, so not booked

    def test_cancelled_books_nothing(self):
        self.print_cube()
        job_report(self, "printing")
        time.sleep(1.2)
        job_report(self, "stoped")
        time.sleep(2)
        self.assertEqual(FakeSpoolman.used, [])

    def test_busy_info_during_a_job_still_allows_pause_and_stop(self):
        self.fake.report("info/report", {"type": "info", "action": "report", "state": "done", "code": 200,
                                         "data": {"state": "busy", "project": {"state": "ace_filament_feeding",
                                                                               "taskid": "-1", "filename": "cube.gcode"}}})
        wait(lambda: self.conn.view()["kobra_state"] == "ace_filament_feeding")
        can = self.svc._data(self.conn)["can"]
        self.assertTrue(can["stop"])
        self.assertFalse(can["move"] or can["print"])

    def test_busy_without_a_job_blocks_everything(self):   # homing: info busy, project null
        self.fake.report("info/report", {"type": "info", "action": "report", "state": "done", "code": 200,
                                         "data": {"state": "busy", "project": None}})
        wait(lambda: self.conn.view()["state"] == "busy")
        self.assertFalse(any(self.svc._data(self.conn)["can"].values()))


class ForeignFileDetails(Base):
    """Kobralink polls file/fileDetails for other files; those reports reach us on the shared topic."""

    def test_details_of_another_file_are_not_ours(self):
        self.set_state("printing")

        def details(msg):
            self.fake.report("file/report", {"type": "file", "action": "fileDetails", "state": "done", "code": 200,
                                             "data": {"root": "local", "filename": "/other.gcode",
                                                      "file_details": {"objects_skip_parts": ["FOREIGN"]}}})
            time.sleep(0.1)
            return {"type": "file", "action": "fileDetails", "state": "done", "code": 200,
                    "data": {"root": "local", "filename": "/a.gcode", "file_details": {"objects_skip_parts": ["A"]}}}
        self.fake.replies[("file", "fileDetails")] = details
        self.assertEqual(self.run_cmd("objects")["result"]["objects"], ["A"])


class RemoteName(unittest.TestCase):
    def test_suffixes(self):   # PrintJob appends ".gcode.3mf" to the project name for LAN prints
        for name, want in (("cube.gcode.3mf", "cube.gcode"), ("cube.3mf", "cube.gcode"), ("cube.GCODE", "cube.gcode"),
                           ("cube", "cube.gcode"), ("", "kobracontrol.gcode")):
            self.assertEqual(jobs.remote_name(name), want, name)


class ReviewTwo(Base):
    def short_requests(self):
        printer = self.conn.printer   # the real waits (5 s jog, 90 s homing), shortened for the test
        real = printer.request
        printer.request = lambda type_, action, data=None, timeout=5, **kw: real(type_, action, data, 1, **kw)

    def test_move_received_without_result_is_in_progress(self):   # M4
        self.fake.ack_only = True
        self.short_requests()
        self.assertEqual(self.run_cmd("move", axis="z", distance=50)["result"], {"confirmed": False})

    def test_resume_received_without_result_is_in_progress(self):   # L2
        self.set_state("paused")
        self.fake.ack_only = True
        self.short_requests()
        self.assertEqual(self.run_cmd("resume")["result"], {"confirmed": False})

    def test_home_does_not_hold_the_worker(self):   # M5
        self.fake.ack_only = True
        gate = threading.Event()
        printer = self.conn.printer
        printer.move_axis = lambda *a, **k: gate.wait(10) and None
        self.svc.submit("h", "home", {"axes": "xyz"})
        self.assertTrue(self.run_cmd("set_light", on=True, timeout=20)["result"])   # answered while home waits
        self.assertFalse(gate.is_set())
        self.svc.submit("h2", "home", {"axes": "z"})
        reply = wait(lambda: next((m for m in self.published if m.get("id") == "h2"), None))
        self.assertIn("already running", reply["error"])
        gate.set()

    def test_dry_start_payload_from_ace_builder(self):   # L7: one builder, clamped first
        self.run_cmd("dry_start", aces=[0], temp=99.6, minutes=5)
        data = wait(lambda: self.sent("multiColorBox", "setDry"))[0]["data"]
        self.assertEqual(data, ace.set_dry_payload([0], 80, 10))
