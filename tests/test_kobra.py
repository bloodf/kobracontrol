"""Kobra protocol: credentials, MQTT request/reply, command helpers, upload, print/start and the State reducer."""

import base64
import dataclasses
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests"), os.path.join(ROOT, "scripts")]

import aes  # noqa: E402
import certs  # noqa: E402
import kobra  # noqa: E402
import probe  # noqa: E402
from fake_kobra import FakeKobra, make_tls_files  # noqa: E402
from test_mqtt import wait_for  # noqa: E402


class FakeCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)

    def creds(self):
        return kobra.fetch_credentials(self.fake.host, port=self.fake.http_port, timeout=3)


class CredentialTests(FakeCase):
    def test_fetch(self):
        c = self.creds()
        self.assertEqual((c.ip, c.username, c.password, c.device_id, c.mode_id, c.model),
                         ("127.0.0.1", self.fake.username, self.fake.password, self.fake.device_id, "20030",
                          "Anycubic Kobra X"))
        q = self.fake.ctrl_calls[0]
        self.assertEqual(q["did"], "random")
        self.assertEqual(len(q["nonce"]), 6)
        self.assertAlmostEqual(int(q["ts"]) / 1000, time.time(), delta=60)

    def test_repr_masks_password(self):
        r = repr(self.creds())
        self.assertNotIn(self.fake.password, r)
        self.assertIn("***", r)
        self.assertIn(self.fake.device_id, r)

    def test_unreachable(self):
        self.fake.stop()
        with self.assertRaises(kobra.KobraError) as cm:
            self.creds()
        self.assertIn("not reachable", str(cm.exception))
        self.fake.start()

    def test_info_without_token(self):
        self.fake.info_answer = {"code": 200}
        with self.assertRaisesRegex(kobra.KobraError, "LAN mode"):
            self.creds()

    def test_info_not_json(self):
        self.fake.info_answer = b"<html>"
        with self.assertRaisesRegex(kobra.KobraError, "/info"):
            self.creds()

    def test_bad_ctrl_answer(self):
        self.fake.ctrl_answer = {"code": 500, "msg": "nope"}
        with self.assertRaisesRegex(kobra.KobraError, "/ctrl") as cm:
            self.creds()
        self.assertNotIn(self.fake.token, str(cm.exception))

    def test_ctrl_http_error(self):
        self.fake._ctrl = lambda q: (500, {"code": 500})
        with self.assertRaisesRegex(kobra.KobraError, "HTTP 500"):
            self.creds()

    def test_decrypt_failure(self):
        self.fake.ctrl_answer = {"data": {"info": base64.b64encode(b"x" * 32).decode(), "token": "0123456789abcdef"}}
        with self.assertRaisesRegex(kobra.KobraError, "decrypt") as cm:
            self.creds()
        self.assertNotIn(self.fake.token, str(cm.exception))

    def encrypted(self, plain):
        iv = "fedcba9876543210"
        enc = aes.encrypt_cbc(self.fake.token[16:32].encode(), iv.encode(), json.dumps(plain).encode())
        return {"data": {"info": base64.b64encode(enc).decode(), "token": iv}}

    def test_printer_error_field(self):
        self.fake.ctrl_answer = self.encrypted({"error": "LAN mode disabled"})
        with self.assertRaisesRegex(kobra.KobraError, "LAN mode disabled"):
            self.creds()

    def test_defaults(self):
        self.fake.ctrl_answer = self.encrypted({"username": "u", "password": "p", "deviceId": "d"})
        c = self.creds()
        self.assertEqual((c.ip, c.mode_id, c.model), ("127.0.0.1", "20030", "Anycubic Kobra"))


class PrinterCase(FakeCase):
    def setUp(self):
        super().setUp()
        self.reports, self.drops = [], []
        self.printer = self.make()
        self.printer.connect()

    def make(self, **kw):
        p = kobra.Printer(self.creds(), mqtt_port=self.fake.mqtt_port, http_port=self.fake.http_port,
                          on_report=lambda s, m: self.reports.append((s, m)), on_disconnect=self.drops.append, **kw)
        self.addCleanup(p.close)
        return p

    def topic(self, kind, type_):
        return "anycubic/anycubicCloud/v1/%s/printer/20030/%s/%s" % (kind, self.fake.device_id, type_)


class RequestTests(PrinterCase):
    def test_connect(self):
        self.assertTrue(self.printer.connected)
        self.assertRegex(self.fake.client_ids[0], r"^kobracontrol_[0-9a-f]{8}$")
        self.assertEqual(self.fake.subscriptions,
                         ["anycubic/anycubicCloud/v1/printer/public/20030/%s/#" % self.fake.device_id])

    def test_two_printers_use_distinct_client_ids(self):
        self.make().connect()
        self.assertEqual(len(set(self.fake.client_ids)), 2)

    def test_request_reply_by_msgid(self):
        self.fake.reply("info", "query", {"printerName": "K"})
        reply = self.printer.request("info", "query")
        self.assertEqual(reply["data"], {"printerName": "K"})
        req = self.fake.requests[0]
        self.assertEqual(req["topic"], self.topic("slicer", "info"))
        msg = req["msg"]
        self.assertEqual((msg["type"], msg["action"], msg["data"]), ("info", "query", None))
        self.assertEqual(uuid.UUID(msg["msgid"]).version, 4)
        self.assertAlmostEqual(msg["timestamp"] / 1000, time.time(), delta=60)
        self.assertEqual(self.reports[-1][0], "info/report")

    def test_timeout_returns_none(self):
        start = time.monotonic()
        self.assertIsNone(self.printer.request("info", "query", timeout=0.3))
        self.assertLess(time.monotonic() - start, 1.5)

    def test_reply_without_msgid_matches_report_suffix(self):
        self.fake.replies[("status", "query")] = lambda m: {"type": "status", "action": "x", "msgid": None, "data": 1}
        self.assertEqual(self.printer.request("status", "query", timeout=2)["data"], 1)

    def test_foreign_msgid_ignored_without_match_action(self):
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "move", "msgid": "other"}
        self.assertIsNone(self.printer.request("axis", "move", timeout=0.4))

    def test_match_action_accepts_same_action(self):
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "move", "msgid": "other",
                                                         "state": "done"}
        self.assertEqual(self.printer.request("axis", "move", timeout=2, match_action=True)["state"], "done")

    def test_match_action_needs_matching_suffix(self):
        def wrong_topic(m):
            self.fake.report("info/report", {"msgid": m["msgid"], "action": "move"})
        self.fake.replies[("axis", "move")] = wrong_topic
        self.assertIsNone(self.printer.request("axis", "move", timeout=0.4, match_action=True))

    def test_reports_and_bad_payloads(self):
        self.fake.report("x/report", b"not json")
        self.fake.report("x/report", b"[1, 2]")
        self.fake.report("light/report", {"data": {"status": 1}})
        self.assertTrue(wait_for(lambda: self.reports))
        self.assertEqual(self.reports[0][0], "light/report")
        self.assertEqual(len(self.reports), 1)

    def test_report_callback_errors_are_contained(self):
        self.printer.on_report = mock.Mock(side_effect=RuntimeError("x"))
        with self.assertLogs(kobra.log, "ERROR"):
            self.fake.report("light/report", {"data": {}})
            self.fake.reply("info", "query", {})
            self.assertIsNotNone(self.printer.request("info", "query", timeout=2))

    def test_disconnect_fails_pending(self):
        result = []
        t = threading.Thread(target=lambda: result.append(self.printer.request("info", "query", timeout=10)))
        t.start()
        self.assertIsNotNone(self.fake.wait_request("info", "query"))
        self.fake.drop_clients()
        t.join(3)
        self.assertEqual(result, [None])
        self.assertTrue(wait_for(lambda: self.drops))
        self.assertFalse(self.printer.connected)
        self.assertIsNone(self.printer.request("info", "query"))
        self.assertFalse(self.printer.send("info", "query"))

    def test_close_idempotent(self):
        self.printer.close()
        self.printer.close()
        self.assertFalse(self.printer.connected)

    def test_connect_auth_failure(self):
        bad = dataclasses.replace(self.creds(), password="not-the-password")
        p = kobra.Printer(bad, mqtt_port=self.fake.mqtt_port, on_disconnect=self.drops.append)
        with self.assertRaises(kobra.KobraError) as cm:
            p.connect()
        self.assertIn("refused", str(cm.exception))
        self.assertNotIn("not-the-password", str(cm.exception))
        self.assertEqual(cm.exception.code, 4)
        self.assertFalse(p.connected)
        self.assertEqual(self.drops, [])


class HelperTests(PrinterCase):
    def published(self, n=1):
        self.assertTrue(wait_for(lambda: len(self.fake.requests) >= n))
        return [(r["topic"].split("/")[3], r["msg"]["type"], r["msg"]["action"], r["msg"]["data"])
                for r in self.fake.requests]

    def check(self, call, *expected, reply=None):
        self.fake.requests.clear()
        if reply:
            self.fake.reply(*reply)
        call()
        self.assertEqual(self.published(len(expected)), list(expected))

    def test_requests(self):
        p = self.printer
        cases = [
            (p.query_info, ("slicer", "info", "query", None)),
            (p.query_status, ("slicer", "status", "query", None)),
            (p.query_print, ("slicer", "print", "query", None)),
            (p.query_multi_color_box, ("slicer", "multiColorBox", "getInfo", None)),
            (lambda: p.pause_print("7"), ("slicer", "print", "pause", {"taskid": "7"})),
            (p.resume_print, ("slicer", "print", "resume", {"taskid": "-1"})),
            (p.stop_print, ("slicer", "print", "stop", {"taskid": "-1"})),
            (p.start_camera, ("slicer", "video", "startCapture", None)),
            (p.stop_camera, ("slicer", "video", "stopCapture", None)),
            (lambda: p.move_axis(1, 0, 10), ("slicer", "axis", "move", {"axis": 1, "move_type": 0, "distance": 10})),
            (p.query_skip_objects, ("slicer", "skip", "query_obj", None)),
            (lambda: p.skip_objects(["a"]), ("slicer", "skip", "start", {"objects_skip_parts": ["a"]})),
        ]
        for call, expected in cases:
            self.check(lambda call=call: self.assertEqual(call()["state"], "success"), expected, reply=expected[1:3])

    def test_fire_and_forget(self):
        p = self.printer
        drying = {"status": 1, "target_temp": 50, "duration": 240, "remain_time": 240}
        cases = [
            (lambda: p.set_fan(40), ("slicer", "fan", "setSpeed", {"fan_speed_pct": 40})),
            (lambda: p.set_light(True), ("slicer", "light", "control", {"type": 3, "status": 1, "brightness": 80})),
            (lambda: p.set_light(False, 20), ("slicer", "light", "control", {"type": 3, "status": 0, "brightness": 20})),
            (lambda: p.set_print_speed_mode("9", 2),
             ("web", "print", "update", {"taskid": "9", "settings": {"print_speed_mode": 2}})),
            (p.disable_steppers, ("slicer", "axis", "turnOff", None)),
            (lambda: p.set_ams_slot_info(1, 2, "PLA", [1, 2, 3]),
             ("web", "multiColorBox", "setInfo",
              {"multi_color_box": [{"id": 1, "slots": [{"index": 2, "type": "PLA", "color": [1, 2, 3]}]}]})),
            (lambda: p.feed_filament(0, 3, 1),
             ("slicer", "multiColorBox", "feedFilament",
              {"multi_color_box": [{"id": 0, "feed_status": {"slot_index": 3, "type": 1}}]})),
            (lambda: p.set_auto_feed(1, True),
             ("slicer", "multiColorBox", "setAutoFeed", {"multi_color_box": [{"id": 1, "auto_feed": 1}]})),
            (lambda: p.set_dry([0, 1], drying),
             ("slicer", "multiColorBox", "setDry",
              {"multi_color_box": [{"id": 0, "drying_status": drying}, {"id": 1, "drying_status": drying}]})),
            (p.list_local_files, ("slicer", "file", "listLocal", {"page_num": 1, "page_size": 1000, "path": "/"})),
            (lambda: p.delete_local_files(["a.gcode"]),
             ("slicer", "file", "deleteBatch", {"root": "local", "files": [{"path": "/", "filename": "a.gcode"}]})),
            (lambda: p.request_file_details("a.gcode"),
             ("slicer", "file", "fileDetails", {"root": "local", "filename": "a.gcode"})),
        ]
        for call, expected in cases:
            self.check(call, expected)

    def test_temperatures(self):
        p = self.printer
        self.check(lambda: p.set_idle_temperature(210.4, 60.6),
                   ("web", "tempature", "set", {"type": 2, "target_nozzle_temp": 210, "target_hotbed_temp": 61}))
        self.check(lambda: p.set_idle_temperature(nozzle=200),
                   ("web", "tempature", "set", {"type": 0, "target_nozzle_temp": 200, "target_hotbed_temp": 0}))
        self.check(lambda: p.set_idle_temperature(bed=55),
                   ("web", "tempature", "set", {"type": 1, "target_nozzle_temp": 0, "target_hotbed_temp": 55}))
        self.check(lambda: p.set_printing_temperature("4", 220, 70),
                   ("web", "print", "update", {"taskid": "4", "settings": {"target_nozzle_temp": 220}}),
                   ("web", "print", "update", {"taskid": "4", "settings": {"target_hotbed_temp": 70}}))
        self.check(lambda: p.set_printing_temperature("4", bed=65),
                   ("web", "print", "update", {"taskid": "4", "settings": {"target_hotbed_temp": 65}}))
        self.fake.requests.clear()
        p.set_idle_temperature()
        p.set_printing_temperature("4")
        time.sleep(0.2)
        self.assertEqual(self.fake.requests, [])

    def test_move_axis_matches_action(self):
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "move", "msgid": "x", "state": "ok"}
        self.assertEqual(self.printer.move_axis(4, 2)["state"], "ok")


class PrintTests(PrinterCase):
    MAPPING = [{"paint_index": 0, "ams_index": 2, "paint_color": [1, 2, 3, 255], "ams_color": [1, 2, 3, 255],
                "material_type": "PLA"}]

    def test_payload(self):
        payload = kobra.print_file_payload("a b.gcode", 1234, self.MAPPING,
                                           {"auto_leveling": True, "vibration_compensation": True,
                                            "skip_parts": ["o1"]})
        self.assertEqual(payload, {
            "taskid": "-1", "url": "", "filename": "a b.gcode", "md5": "", "filepath": "/a b.gcode",
            "filetype": 1, "project_type": 1, "filesize": 1234,
            "ams_settings": {"use_ams": True, "ams_box_mapping": self.MAPPING},
            "task_settings": {
                "auto_leveling": 1, "vibration_compensation": 1, "flow_calibration": 0, "dry_mode": 0,
                "ai_settings": {"status": 0, "count": 0, "type": 1},
                "timelapse": {"status": 0, "count": 0, "type": 64},
                "drying_settings": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
                "model_objects_skip_parts": ["o1"]}})

    def test_payload_defaults(self):
        payload = kobra.print_file_payload("a.gcode", 1, [], None)
        self.assertEqual(payload["ams_settings"], {"use_ams": False, "ams_box_mapping": []})
        self.assertEqual((payload["task_settings"]["auto_leveling"], payload["task_settings"]["vibration_compensation"],
                          payload["task_settings"]["model_objects_skip_parts"]), (0, 0, []))

    def test_start_print_accepted(self):
        self.fake.reply("print", "start", {}, state="success", code=0)
        reply = self.printer.start_print(kobra.print_file_payload("a.gcode", 1, [], None))
        self.assertEqual(reply["code"], 0)
        self.assertEqual(self.fake.wait_request("print", "start")["data"]["filepath"], "/a.gcode")

    def test_start_print_refused(self):
        for kwargs in ({"state": "failed", "code": 10010, "msg": "busy"}, {"state": "success", "code": 3, "msg": "no"}):
            self.fake.reply("print", "start", {"x": 1}, **kwargs)
            with self.assertRaises(kobra.KobraError) as cm:
                self.printer.start_print({}, timeout=2)
            self.assertIn(str(kwargs["code"]), str(cm.exception))
            self.assertIn(kwargs["msg"], str(cm.exception))
            self.assertEqual(cm.exception.code, kwargs["code"])

    def test_start_print_unanswered(self):
        with self.assertRaisesRegex(kobra.KobraError, "no answer"):
            self.printer.start_print({}, timeout=0.3)


class UploadTests(PrinterCase):
    def source(self, size):
        fd, path = tempfile.mkstemp(suffix=".gcode")
        os.write(fd, os.urandom(size))
        os.close(fd)
        self.addCleanup(os.remove, path)
        return path

    def test_streams_file_with_headers(self):
        path = self.source(300_000)
        progress = []
        with mock.patch.object(kobra, "UPLOAD_CHUNK", 65536):
            answer = self.printer.upload("job 1.gcode", path, self.fake.upload_url, progress=lambda s, t: progress.append((s, t)))
        self.assertEqual(answer, {"code": 200, "message": "success"})
        up = self.fake.uploads[0]
        with open(path, "rb") as f:
            self.assertEqual(up["data"], f.read())
        self.assertEqual(up["filename"], "job 1.gcode")
        h = up["headers"]
        self.assertEqual(h["X-BBL-Language"], "en-US")
        self.assertEqual(h["X-File-Length"], "300000")
        self.assertEqual(h["X-BBL-Client-Name"], "AnycubicSlicerNext")
        self.assertEqual(h["User-Agent"], "AnycubicSlicerNext/1.3.9.4")
        self.assertEqual(h["Host"], "127.0.0.1:%d" % self.fake.http_port)
        uuid.UUID(h["X-BBL-Device-ID"])
        self.assertGreaterEqual(len(progress), 5)
        self.assertEqual(progress[-1], (300_000, 300_000))
        self.assertEqual([s for s, _ in progress], sorted(s for s, _ in progress))

    def test_empty_file(self):
        self.printer.upload("e.gcode", self.source(0), self.fake.upload_url)
        self.assertEqual(self.fake.uploads[0]["data"], b"")

    def test_cancel(self):
        path = self.source(400_000)
        seen = []
        with self.assertRaises(kobra.Cancelled):
            self.printer.upload("c.gcode", path, self.fake.upload_url, progress=lambda s, t: seen.append(s),
                                cancelled=lambda: len(seen) >= 2)
        time.sleep(0.2)
        self.assertEqual(self.fake.uploads, [])

    def test_unsafe_filename(self):
        for name in ('a"b.gcode', "a\r\nb.gcode", ""):
            with self.assertRaises(kobra.KobraError):
                self.printer.upload(name, self.source(1), self.fake.upload_url)
        self.assertEqual(self.fake.uploads, [])

    def test_url_without_token(self):
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.upload("a.gcode", self.source(1), "http://127.0.0.1/gcode_upload")
        self.assertNotIn("127.0.0.1", str(cm.exception))

    def test_refused_and_garbage_answers(self):
        bad = self.fake.upload_url.replace(self.fake.upload_token, "wrongtoken")
        with self.assertRaisesRegex(kobra.KobraError, "HTTP 403") as cm:
            self.printer.upload("a.gcode", self.source(1), bad)
        self.assertNotIn("wrongtoken", str(cm.exception))
        self.fake.upload_answer = b"<html>"
        with self.assertRaisesRegex(kobra.KobraError, "unexpected"):
            self.printer.upload("a.gcode", self.source(1), self.fake.upload_url)

    def test_unreachable(self):
        self.fake.stop()
        with self.assertRaisesRegex(kobra.KobraError, "upload"):
            self.printer.upload("a.gcode", self.source(1), self.fake.upload_url)
        self.fake.start()


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed to generate throwaway certificates")
class TlsPrinterTests(unittest.TestCase):
    def test_printer_over_mutual_tls(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        tls = make_tls_files(tmp)
        fake = FakeKobra(tls=tls).start()
        self.addCleanup(fake.stop)
        fake.reply("info", "query", {"version": "1.0"})
        creds = kobra.fetch_credentials(fake.host, port=fake.http_port)
        p = kobra.Printer(creds, ssl_context=certs.context(tls.client_cert, tls.client_key), mqtt_port=fake.mqtt_port)
        self.addCleanup(p.close)
        p.connect()
        self.assertEqual(p.query_info()["data"]["version"], "1.0")


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed to generate throwaway certificates")
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tls = make_tls_files(self.tmp)
        self.slicer = os.path.join(self.tmp, "slicer")
        os.makedirs(self.slicer)
        with open(os.path.join(self.slicer, "libcloud_mqtt.dylib"), "wb") as out:
            for path in (self.tls.client_key, self.tls.server_cert, self.tls.client_cert):
                with open(path, "rb") as f:
                    out.write(os.urandom(64) + f.read())
        self.fake = FakeKobra(tls=self.tls).start()
        self.addCleanup(self.fake.stop)
        self.lines = []

    def run_probe(self):
        probe.run(self.fake.host, self.slicer, http_port=self.fake.http_port, mqtt_port=self.fake.mqtt_port,
                  out=self.lines.append)
        return "\n".join(self.lines)

    def test_read_only_summary(self):
        self.fake.reply("info", "query", {"printerName": "K1", "version": "1.2", "state": "free",
                                          "temp": {"curr_nozzle_temp": 26, "curr_hotbed_temp": 25},
                                          "urls": {"fileUploadurl": self.fake.upload_url, "rtspUrl": "rtsp://x"}})
        self.fake.reply("multiColorBox", "getInfo", {"multi_color_box": [{"id": 0, "slots": [{}, {}, {}, {}]},
                                                                         {"id": 1, "slots": [{}]}]})
        before = set(os.listdir(tempfile.gettempdir()))
        text = self.run_probe()
        for expected in ("libcloud_mqtt.dylib", "K1", "1.2", "idle", "26 / 0", "ACE boxes:   2 (5 slots)",
                         "upload URL:  yes", "camera URL:  yes"):
            self.assertIn(expected, text)
        for secret in (self.fake.password, self.fake.token, self.fake.upload_token):
            self.assertNotIn(secret, text)
        self.assertEqual([(r["msg"]["type"], r["msg"]["action"]) for r in self.fake.requests],
                         [("info", "query"), ("multiColorBox", "getInfo")])
        leftovers = {n for n in set(os.listdir(tempfile.gettempdir())) - before if n.startswith("kobracontrol-")}
        self.assertEqual(leftovers, set())

    def test_failing_steps(self):
        with self.assertRaisesRegex(probe.StepFailed, "^info/query: no answer"):
            self.run_probe()
        self.fake.info_answer = {}
        with self.assertRaisesRegex(probe.StepFailed, "^credentials: .*LAN mode"):
            self.run_probe()
        os.remove(os.path.join(self.slicer, "libcloud_mqtt.dylib"))
        with self.assertRaisesRegex(probe.StepFailed, "^certificate: "):
            self.run_probe()

    def test_main_exit_code(self):
        with mock.patch.object(probe, "run", side_effect=probe.StepFailed("mqtt: nope")), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(probe.main(["10.0.0.9"]), 1)
        self.assertIn("mqtt: nope", "".join(c.args[0] for c in err.write.call_args_list))
        with mock.patch.object(probe, "run"):
            self.assertEqual(probe.main(["10.0.0.9", "--slicer", "/x"]), 0)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.s = kobra.State(model="Kobra X")
        self.s.connected = True

    def apply(self, suffix, data=None, **fields):
        self.s.apply(suffix, {"data": data, **fields})
        return self.s.view()

    def test_initial_view_is_offline_and_json(self):
        v = kobra.State().view()
        self.assertEqual(v["state"], "offline")
        json.dumps(v)
        for key in kobra.VIEW_KEYS:
            self.assertIn(key, v)
        self.assertEqual(set(v), set(kobra.VIEW_KEYS))

    def test_info_report(self):
        v = self.apply("info/report", {
            "printerName": "Kobra", "version": "2.1", "state": "free", "fan_speed_pct": 30, "print_speed_mode": 2,
            "temp": {"curr_nozzle_temp": 25, "target_nozzle_temp": 0, "curr_hotbed_temp": 24, "target_hotbed_temp": 0},
            "urls": {"fileUploadurl": "http://p/gcode_upload?s=t", "rtspUrl": "rtsp://p/cam", "flvUrl": "http://p/f"},
            "storage": {"total": 100, "used": 10}})
        self.assertEqual((v["printer_name"], v["model"], v["firmware"], v["kobra_state"], v["state"]),
                         ("Kobra", "Kobra X", "2.1", "free", "idle"))
        self.assertEqual((v["nozzle_temp"], v["nozzle_target"], v["bed_temp"], v["bed_target"]), (25, 0, 24, 0))
        self.assertEqual((v["fan_pct"], v["speed_mode"]), (30, 2))
        self.assertEqual(v["upload_url"], "http://p/gcode_upload?s=t")
        self.assertEqual(v["camera_url"], "rtsp://p/cam")
        self.assertEqual(v["camera_urls"], {"rtspUrl": "rtsp://p/cam", "flvUrl": "http://p/f"})
        self.assertEqual(v["storage"], {"total": 100, "used": 10})

    def test_info_project_printing(self):
        v = self.apply("info/report", {"state": "busy", "project": {
            "state": "printing", "filename": "a.gcode", "progress": 42, "print_time": 10, "remain_time": 5,
            "curr_layer": 3, "total_layers": 90, "taskid": 77}})
        self.assertEqual((v["state"], v["filename"], v["progress"], v["elapsed_s"], v["remaining_s"]),
                         ("printing", "a.gcode", 42, 600, 300))
        self.assertEqual((v["layer"], v["total_layers"], v["task_id"]), (3, 90, "77"))

    def test_print_report_lifecycle(self):
        v = self.apply("print/report", {"filename": "a.gcode", "progress": 5, "print_time": 1, "remain_time": 60,
                                        "curr_layer": 1, "total_layers": 50, "taskid": "9",
                                        "settings": {"print_speed_mode": 3}}, state="printing")
        self.assertEqual((v["state"], v["progress"], v["remaining_s"], v["speed_mode"], v["task_id"]),
                         ("printing", 5, 3600, 3, "9"))
        v = self.apply("print/report", {"progress": 0}, state="preheating")
        self.assertEqual((v["state"], v["progress"]), ("printing", 5))
        v = self.apply("print/report", {}, state="paused", code=1203, msg="filament runout")
        self.assertEqual((v["state"], v["pause_reason"]), ("paused", {"code": 1203, "msg": "filament runout"}))
        v = self.apply("print/report", {}, state="resuming")
        self.assertEqual((v["state"], v["pause_reason"]), ("printing", None))
        v = self.apply("print/report", {"filename": "a.gcode", "progress": 100}, state="finished")
        self.assertEqual((v["state"], v["filename"], v["layer"], v["total_layers"], v["elapsed_s"]),
                         ("finished", "", 0, 0, 0))
        self.assertEqual(v["progress"], 100)

    def test_normalised_states(self):
        for raw, norm in (("stoped", "cancelled"), ("canceled", "cancelled"), ("pausing", "paused"),
                          ("pause", "paused"), ("failed", "error"), ("busy", "busy"), ("stopping", "busy"),
                          ("weird_new_state", "busy"), ("free", "idle"), ("auto_leveling", "printing"),
                          ("resumed", "printing")):
            self.assertEqual(self.apply("print/report", {}, state=raw)["state"], norm, raw)
        self.s.connected = False
        self.assertEqual(self.s.view()["state"], "offline")

    def test_info_terminal_keeps_filename_out(self):
        self.apply("print/report", {"filename": "a.gcode", "curr_layer": 5, "total_layers": 9}, state="printing")
        v = self.apply("info/report", {"project": {"state": "canceled", "filename": "a.gcode"}})
        self.assertEqual((v["state"], v["layer"], v["total_layers"]), ("cancelled", 0, 0))

    def test_failed_reports_set_last_error(self):
        v = self.apply("axis/report", {"x": 1}, state="failed", action="move", code=7, msg="homing")
        self.assertEqual(v["last_error"], {"report": "axis/report", "action": "move", "code": 7, "msg": "homing"})
        self.assertEqual(v["kobra_state"], "")

    def test_temperature_light_fan_reports(self):
        v = self.apply("tempature/report", {"curr_nozzle_temp": 200.5, "target_nozzle_temp": 210,
                                            "curr_hotbed_temp": 60, "target_hotbed_temp": 60})
        self.assertEqual((v["nozzle_temp"], v["nozzle_target"], v["bed_temp"], v["bed_target"]), (200.5, 210, 60, 60))
        v = self.apply("light/report", {"status": 1, "brightness": 55, "type": 3})
        self.assertEqual((v["light_on"], v["light_brightness"]), (True, 55))
        v = self.apply("light/report", {"status": 0})
        self.assertEqual((v["light_on"], v["light_brightness"]), (False, 80))
        self.assertEqual(self.apply("fan/report", {"fan_speed_pct": 70})["fan_pct"], 70)
        self.assertEqual(self.apply("fan/report", {"other": 1})["fan_pct"], 70)

    def test_multi_color_box(self):
        boxes = [{"id": 0, "slots": [{"index": 0, "status": 5, "type": "PLA", "color": [1, 2, 3]}]}]
        v = self.apply("multiColorBox/report", {"multi_color_box": boxes, "head_tools_model": 1})
        self.assertEqual((v["multi_color_box"], v["head_tools_model"]), (boxes, 1))
        v = self.apply("multiColorBox/report", {"multi_color_box": []}, state="failed")
        self.assertEqual(v["multi_color_box"], boxes)
        self.assertEqual(self.apply("multiColorBox/report", {"multi_color_box": []})["multi_color_box"], [])

    def test_files(self):
        records = [{"filename": "old.gcode", "size": 1, "timestamp": 1}, {"filename": "dir", "is_dir": True},
                   {"filename": "new.gcode", "size": 2, "timestamp": 5}]
        v = self.apply("file/report", {"records": records}, action="listLocal", code=200)
        self.assertEqual(v["files"], [{"filename": "new.gcode", "size": 2, "timestamp": 5},
                                      {"filename": "old.gcode", "size": 1, "timestamp": 1}])
        v = self.apply("file/report", {"records": []}, action="listLocal", code=500)
        self.assertEqual(len(v["files"]), 2)
        details = {"filename": "new.gcode", "thumbnail": "b64", "objects_skip_parts": ["o"]}
        self.assertEqual(self.apply("file/report", {"file_details": details}, action="fileDetails")["file_details"],
                         details)

    def test_skip_objects_merge_while_printing(self):
        self.apply("print/report", {}, state="printing")
        self.assertEqual(self.apply("skip/report", {"objects_skip_parts": ["a"]})["skipped_objects"], ["a"])
        self.assertEqual(self.apply("skip/report", {"skipped": ["b"]})["skipped_objects"], ["a", "b"])
        self.assertEqual(self.apply("skip/report", {})["skipped_objects"], ["a", "b"])
        self.apply("print/report", {}, state="free")
        self.assertEqual(self.apply("skip/report", {"skipped_parts": ["c"]})["skipped_objects"], ["c"])

    def test_buried_storage_and_video(self):
        v = self.apply("buried/report", {"task_name": "a", "storage_total": 8000, "storage_used": 100})
        self.assertEqual(v["storage"], {"total": 8000, "used": 100})
        self.assertEqual(self.apply("buried/report", {"task_name": "b"})["storage"], {"total": 8000, "used": 100})
        self.assertTrue(self.apply("video/report", {}, action="startCapture", state="success")["camera_active"])
        self.assertFalse(self.apply("video/report", {}, action="stopCapture", state="success")["camera_active"])

    def test_view_is_a_copy_and_tolerates_junk(self):
        self.apply("multiColorBox/report", {"multi_color_box": [{"id": 0}]})
        v = self.s.view()
        v["multi_color_box"].append("junk")
        self.assertEqual(len(self.s.view()["multi_color_box"]), 1)
        for junk in (None, [], "x", {"data": "x"}, {"data": {"temp": "hot", "urls": 3, "project": 1}}):
            self.s.apply("info/report", junk)
            self.s.apply("print/report", junk)
        json.dumps(self.s.view())
        self.assertIsInstance(self.s.view()["updated_at"], float)


if __name__ == "__main__":
    unittest.main()
