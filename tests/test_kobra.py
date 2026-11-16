"""Kobra protocol: credentials, MQTT request/reply, command helpers, upload, print/start and the State reducer."""

import base64
import copy
import dataclasses
import hashlib
import json
import os
import shutil
import ssl
import sys
import tempfile
import threading
import time
import unittest
import uuid
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests"), os.path.join(ROOT, "scripts")]

import aes  # noqa: E402
import bambu  # noqa: E402
import certs  # noqa: E402
import kobra  # noqa: E402
import probe  # noqa: E402
import service  # noqa: E402
import kobra_captures as cap  # noqa: E402

with open(os.path.join(ROOT, "tests", "kobra_print_capture.json"), encoding="utf-8") as _f:
    LIVE = json.load(_f)  # [t, suffix, payload] rows from a real print and motion session (fw 2.0.2.8)
from fake_kobra import FakeKobra, make_tls_files  # noqa: E402
from test_mqtt import wait_for  # noqa: E402

AUDIT = {"active": False, "events": []}


def _audit(event, args):  # sys.addaudithook cannot be removed, so it records only while a test asks
    if AUDIT["active"] and event in ("urllib.Request", "http.client.connect", "socket.connect"):
        AUDIT["events"].append((event, args[1] if event == "http.client.connect" else args[0]))


sys.addaudithook(_audit)


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
        return self.encrypted_raw(json.dumps(plain).encode())

    def encrypted_raw(self, raw):
        iv = "fedcba9876543210"
        enc = aes.encrypt_cbc(self.fake.token[16:32].encode(), iv.encode(), raw)
        return {"data": {"info": base64.b64encode(enc).decode(), "token": iv}}

    def test_deeply_nested_json_is_kobra_error(self):
        """M1: RecursionError from json must not escape."""
        self.fake.info_answer = b"[" * 200000
        with self.assertRaisesRegex(kobra.KobraError, "/info"):
            self.creds()
        self.fake.info_answer = None
        self.fake.ctrl_answer = self.encrypted_raw(b"[" * 200000)
        with self.assertRaisesRegex(kobra.KobraError, "decrypt"):
            self.creds()

    def test_non_utf8_answer_is_kobra_error(self):
        self.fake.info_answer = b"\xff\xfe{"
        with self.assertRaises(kobra.KobraError):
            self.creds()

    def test_printer_cannot_choose_the_address(self):
        """M2: the decrypted "ip" is ignored; we keep talking to the address we were given."""
        self.fake.ctrl_answer = self.encrypted({"ip": "203.0.113.7", "username": "u", "password": "p",
                                                 "deviceId": "d"})
        with self.assertNoLogs(kobra.log):
            self.assertEqual(self.creds().ip, "127.0.0.1")

    def test_credentials_never_use_urllib(self):
        """H2: OrcaSlicer audits urllib by full URL (the /ctrl query changes every time, so it can never
        be granted); http.client is audited by host, which one grant covers."""
        AUDIT["events"].clear()
        AUDIT["active"] = True
        try:
            self.creds()
        finally:
            AUDIT["active"] = False
        names = {e for e, _ in AUDIT["events"]}
        self.assertNotIn("urllib.Request", names)
        self.assertIn(("http.client.connect", "127.0.0.1"), AUDIT["events"])

    def test_denied_network_is_told_apart(self):
        """H2: the audit hook's PermissionError is KobraError(code="denied"), not "not reachable"."""
        with mock.patch("http.client.HTTPConnection.connect", side_effect=PermissionError("audit: denied")):
            with self.assertRaises(kobra.KobraError) as cm:
                self.creds()
        self.assertEqual(cm.exception.code, "denied")
        self.assertIn("denied", str(cm.exception))
        self.fake.stop()
        with self.assertRaises(kobra.KobraError) as cm:
            self.creds()
        self.assertEqual(cm.exception.code, "unreachable")
        self.fake.start()

    def test_malformed_http_is_kobra_error(self):
        import http.client
        with mock.patch("http.client.HTTPConnection.getresponse", side_effect=http.client.BadStatusLine("x")):
            with self.assertRaises(kobra.KobraError):
                self.creds()

    def test_redirects_are_not_followed(self):
        """M2: a 3xx from /info is an error, never a request to another host."""
        other = FakeKobra().start()
        self.addCleanup(other.stop)
        self.fake.info_redirect = "http://%s:%d/info" % (other.host, other.http_port)
        with self.assertRaisesRegex(kobra.KobraError, "HTTP 302"):
            self.creds()
        self.assertEqual(other.ctrl_calls, [])

    def test_oversized_http_answer(self):
        """M3: at most 1 MiB is read from /info."""
        self.fake.info_answer = b'{"token": "' + b"a" * (kobra.MAX_HTTP_BODY + 10) + b'"}'
        with self.assertRaisesRegex(kobra.KobraError, "too large"):
            self.creds()

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

    def test_request_settles_on_report_not_on_ack(self):
        """Real firmware: an empty ack on <deviceId>/response with our msgid, then <type>/report with a
        printer-made msgid (info/query answers with action "report")."""
        self.fake.reply("info", "query", {"printerName": "K"})
        reply = self.printer.request("info", "query")
        self.assertEqual(reply["data"], {"printerName": "K"})
        self.assertEqual((reply["action"], reply["code"], reply["state"]), ("report", 200, "done"))
        self.assertNotEqual(reply["msgid"], self.fake.requests[0]["msg"]["msgid"])
        self.assertTrue(kobra.succeeded(reply))
        self.assertFalse(kobra.is_ack_only(reply))
        self.assertEqual(self.printer.last_ack["msgid"], self.fake.requests[0]["msg"]["msgid"])
        self.assertNotIn("response", [s.split("/")[-1] for s, _ in self.reports])  # acks are not reports
        req = self.fake.requests[0]
        self.assertEqual(req["topic"], self.topic("slicer", "info"))
        msg = req["msg"]
        self.assertEqual((msg["type"], msg["action"], msg["data"]), ("info", "query", None))
        self.assertEqual(uuid.UUID(msg["msgid"]).version, 4)
        self.assertAlmostEqual(msg["timestamp"] / 1000, time.time(), delta=60)
        self.assertEqual(self.reports[-1][0], "info/report")

    def test_timeout_without_ack_returns_none(self):
        self.fake.send_ack = False
        start = time.monotonic()
        self.assertIsNone(self.printer.request("info", "query", timeout=0.3))
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertTrue(self.printer.connected)  # one missed answer is not a dead session (KX-Bridge #105)

    def test_ack_without_report_returns_ack_marker(self):
        """print/query on an idle printer: acknowledged, never reported."""
        reply = self.printer.request("print", "query", timeout=0.3)
        self.assertTrue(kobra.is_ack_only(reply))
        self.assertEqual((reply["ack"], reply["type"], reply["action"], reply["data"]), (True, "print", "query", None))
        self.assertFalse(kobra.succeeded(reply))
        self.fake.ack_only = True
        self.fake.reply("info", "query", {})
        self.assertTrue(kobra.is_ack_only(self.printer.request("info", "query", timeout=0.3)))

    def test_any_action_when_reply_action_is_none(self):
        self.fake.replies[("status", "query")] = lambda m: {"type": "status", "action": "x", "msgid": None, "data": 1}
        self.assertEqual(self.printer.request("status", "query", timeout=2, reply_action=None)["data"], 1)
        self.assertTrue(kobra.is_ack_only(self.printer.request("status", "query", timeout=0.3)))

    def test_explicit_reply_action(self):
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "moved", "code": 200}
        self.assertEqual(self.printer.request("axis", "move", timeout=2, reply_action="moved")["action"], "moved")

    def test_report_of_another_action_does_not_settle(self):
        """Other clients share the topic: a report of the same type for another action is not our answer."""
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "home", "code": 200}
        self.assertTrue(kobra.is_ack_only(self.printer.request("axis", "move", timeout=0.4)))

    def test_report_on_another_topic_does_not_settle(self):
        def wrong_topic(m):
            self.fake.report("info/report", {"msgid": m["msgid"], "action": "move"})
        self.fake.replies[("axis", "move")] = wrong_topic
        self.assertTrue(kobra.is_ack_only(self.printer.request("axis", "move", timeout=0.4)))

    def test_legacy_msgid_echo_still_settles(self):
        """Older firmware echoes our msgid in the report and sends no ack; any action then matches."""
        self.fake.echo_msgid, self.fake.send_ack = True, False
        self.fake.replies[("axis", "move")] = lambda m: {"type": "axis", "action": "anything", "data": 5}
        reply = self.printer.request("axis", "move", timeout=2)
        self.assertEqual(reply["data"], 5)
        self.assertIsNone(self.printer.last_ack)

    def test_reports_before_the_publish_do_not_settle(self):
        """A report that arrived before we sent is someone else's answer."""
        seen = threading.Event()
        self.printer.on_report = lambda s, m: seen.set()
        self.fake.report("light/report", {"type": "light", "action": "control", "code": 200, "data": {"status": 9}})
        self.assertTrue(seen.wait(2))
        self.assertTrue(kobra.is_ack_only(self.printer.request("light", "control", {}, timeout=0.3)))

    def test_reply_helpers(self):
        ok = [{"state": "done", "code": 200}, {"state": "success", "code": 0}, {"state": "paused"}, {"code": 200}]
        bad = [{"state": "failed", "code": 200}, {"state": "done", "code": 10112}, {"code": 3},
               None, {"ack": True, "type": "x", "action": "y", "data": None}]
        for r in ok:
            self.assertTrue(kobra.succeeded(r), r)
            self.assertIs(kobra.check_reply(r, "x"), r)
        for r in bad:
            self.assertFalse(kobra.succeeded(r), r)
        with self.assertRaises(kobra.KobraError) as cm:
            kobra.check_reply(None, "the pause")
        self.assertEqual((cm.exception.code, type(cm.exception)), ("no_answer", kobra.KobraError))
        self.assertIn("did not answer the pause", str(cm.exception))
        with self.assertRaises(kobra.NoResult) as cm:
            kobra.check_reply(bad[-1], "the pause")
        self.assertEqual(cm.exception.code, "no_result")
        self.assertIn("received the pause but reported no result", str(cm.exception))
        with self.assertRaises(kobra.KobraError) as cm:
            kobra.check_reply({"state": "done", "code": 10112, "msg": "busy"}, "the pause")
        self.assertEqual(cm.exception.code, 10112)
        self.assertIn("refused the pause (code 10112): busy", str(cm.exception))

    def test_deeply_nested_report_is_dropped(self):
        """M1: a hostile report must not reach on_report nor break the session."""
        self.fake.report("x/report", b"[" * 200000)
        self.fake.report("light/report", {"data": {}})
        self.assertTrue(wait_for(lambda: self.reports))
        self.assertEqual([s for s, _ in self.reports], ["light/report"])
        self.assertTrue(self.printer.connected)

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
        self.assertEqual(result, [None])  # acknowledged, then the session died: no ack marker
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


class SessionTests(PrinterCase):
    """Ported from KX-Bridge tests/test_mqtt_reconnect.py, test_client_robustness.py, test_poll_loop_reconnect.py."""

    def test_connect_is_idempotent(self):
        self.assertTrue(self.printer.connect())
        self.assertEqual(len(self.fake.client_ids), 1)

    def test_concurrent_connects_run_one_handshake(self):
        p = self.make()
        self.fake.connack_delay = 0.3
        results = []
        threads = [threading.Thread(target=lambda: results.append(p.connect())) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(3)
        self.assertEqual(results, [True, True])
        self.assertEqual(len(self.fake.client_ids), 2)  # setUp's printer + exactly one more

    def test_non_blocking_connect_returns_while_handshake_runs(self):
        p = self.make()
        self.fake.connack_delay = 0.5
        t = threading.Thread(target=p.connect)
        t.start()
        self.assertTrue(wait_for(lambda: len(self.fake.client_ids) == 2))
        start = time.monotonic()
        self.assertFalse(p.connect(wait=False))
        self.assertLess(time.monotonic() - start, 0.2)
        t.join(3)
        self.assertTrue(p.connected)

    def test_reconnect_after_printer_reboot(self):
        self.fake.drop_clients()
        self.assertTrue(wait_for(lambda: self.drops))
        self.assertFalse(self.printer.connected)
        self.assertIsNone(self.printer.query_info())
        self.assertTrue(self.printer.connect())
        self.assertEqual(len(self.fake.subscriptions), 2)
        self.fake.reply("info", "query", {"version": "2"})
        self.assertEqual(self.printer.query_info()["data"]["version"], "2")
        self.assertGreater(self.printer.last_rx, 0)

    def test_one_report_answers_every_waiter(self):
        """Real firmware: reports carry no request id, so concurrent identical queries share the answer."""
        self.fake.reply("info", "query", {"v": 1})
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.printer.query_info())) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(4)
        self.assertEqual([r["data"] for r in results], [{"v": 1}] * 3)

    def test_concurrent_requests_of_one_type_each_get_their_reply(self):
        """Legacy msgid echo: a report carrying a request's msgid goes to that request only."""
        self.fake.echo_msgid = True
        self.fake.replies[("info", "query")] = lambda m: {"type": "info", "action": "report", "data": m["msgid"]}
        results = {}

        def call(label):
            results[label] = self.printer.request("info", "query", timeout=3)
        threads = [threading.Thread(target=call, args=(k,)) for k in "ab"]
        for t in threads:
            t.start()
        for t in threads:
            t.join(4)
        self.assertEqual(set(results), {"a", "b"})
        self.assertTrue(all(r is not None for r in results.values()))
        self.assertNotEqual(results["a"]["data"], results["b"]["data"])


class FileCommandTests(PrinterCase):
    """Ported from KX-Bridge tests/test_printer_files_endpoint.py: answers arrive as file/report."""
    RECORDS = [{"filename": "a.gcode", "is_dir": False, "size": 100, "timestamp": 1700000000},
               {"filename": "subdir", "is_dir": True, "size": 0, "timestamp": 1700000001},
               {"filename": "b.gcode", "is_dir": False, "size": 200, "timestamp": 1700000002}]

    def answer(self, action, **fields):
        self.fake.replies[("file", action)] = lambda m: {"type": "file", "action": action, "msgid": None, **fields}

    def test_list_files(self):
        self.answer("listLocal", code=200, state="success", data={"records": self.RECORDS})
        files = self.printer.list_files(timeout=2)
        self.assertEqual([f["filename"] for f in files], ["b.gcode", "a.gcode"])
        self.assertEqual(self.fake.wait_request("file", "listLocal")["data"], {"page_num": 1, "page_size": 200, "path": "/"})

    def test_list_files_refused_or_silent(self):
        self.answer("listLocal", code=10112, state="failed", data=None)
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.list_files(timeout=2)
        self.assertEqual(cm.exception.code, 10112)
        self.fake.replies.clear()
        with self.assertRaises(kobra.NoResult):
            self.printer.list_files(timeout=0.3)
        self.fake.send_ack = False
        with self.assertRaisesRegex(kobra.KobraError, "did not answer the file list"):
            self.printer.list_files(timeout=0.3)

    def test_list_files_in_seconds(self):
        """The printer reports listLocal timestamps in milliseconds; list_files gives seconds."""
        self.answer("listLocal", code=200, state="done", data=cap.FILE_LISTLOCAL["data"])
        self.assertEqual(self.printer.list_files(timeout=2),
                         [{"filename": "plate_A_PLA_0.16.gcode", "size": 66969765, "timestamp": 1794613802.793}])

    def test_other_actions_do_not_answer_a_waiter(self):
        def wrong(m):
            self.fake.report("file/report", {"action": "fileDetails", "code": 200, "data": {}})
        self.fake.replies[("file", "listLocal")] = wrong
        with self.assertRaises(kobra.KobraError):
            self.printer.list_files(timeout=0.3)

    def test_delete_files(self):
        self.answer("deleteBatch", code=200, state="success", data={})
        self.assertEqual(self.printer.delete_files(["a.gcode", "b.gcode"], timeout=2)["code"], 200)
        self.assertEqual(self.fake.wait_request("file", "deleteBatch")["data"],
                         {"root": "local", "files": [{"path": "/", "filename": "a.gcode"},
                                                     {"path": "/", "filename": "b.gcode"}]})

    def test_delete_files_errors(self):
        with self.assertRaisesRegex(kobra.KobraError, "no file"):
            self.printer.delete_files([])
        self.answer("deleteBatch", code=10112, state="failed", msg="busy")
        with self.assertRaisesRegex(kobra.KobraError, "10112"):
            self.printer.delete_files(["a.gcode"], timeout=2)
        self.fake.replies.clear()
        with self.assertRaises(kobra.NoResult):
            self.printer.delete_files(["a.gcode"], timeout=0.3)

    def test_captured_delete_answer_is_success(self):
        self.answer("deleteBatch", **{k: v for k, v in cap.FILE_DELETEBATCH.items() if k not in ("type", "action")})
        self.assertIsNone(self.printer.delete_files(["a.gcode"], timeout=2)["data"])

    def test_file_details(self):
        details = {"thumbnail": "iVBOR", "png_image": "", "svg_image": "", "objects_skip_parts": []}
        self.answer("fileDetails", code=200, state="done", data={"file_details": details, "filename": "a.gcode"})
        self.assertEqual(self.printer.file_details("a.gcode", timeout=2), details)
        self.assertEqual(self.fake.wait_request("file", "fileDetails")["data"], {"root": "local", "filename": "a.gcode"})
        self.answer("fileDetails", code=10112, state="failed", data=None)
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.file_details("a.gcode", timeout=2)
        self.assertEqual(cm.exception.code, 10112)  # a refusal, not "no result"

    def test_file_details_ignores_other_files(self):
        """Other clients poll fileDetails for their own files on the shared topic; only the report naming the
        asked file (the printer sends "/<name>") answers. Live capture: hundreds from Kobralink mid-print."""
        def answer(m):
            self.fake.report("file/report", {"type": "file", "action": "fileDetails", "code": 200, "state": "done",
                                             "data": {"filename": "/other.gcode", "file_details": {"objects_skip_parts": ["F"]}}})
            time.sleep(0.1)
            return {"type": "file", "action": "fileDetails", "code": 200, "state": "done",
                    "data": {"filename": "/" + m["data"]["filename"], "file_details": {"objects_skip_parts": ["A"]}}}
        self.fake.replies[("file", "fileDetails")] = answer
        self.assertEqual(self.printer.file_details("a.gcode", timeout=2)["objects_skip_parts"], ["A"])
        self.fake.replies[("file", "fileDetails")] = lambda m: {
            "type": "file", "action": "fileDetails", "code": 200, "data": {"filename": "/other.gcode", "file_details": {}}}
        with self.assertRaises(kobra.NoResult):
            self.printer.file_details("a.gcode", timeout=0.4)

    def test_disconnect_releases_file_waiter(self):
        errors = []

        def run():
            try:
                self.printer.list_files(timeout=10)
            except kobra.KobraError as e:
                errors.append(e.code)
        t = threading.Thread(target=run)
        t.start()
        self.assertIsNotNone(self.fake.wait_request("file", "listLocal"))
        self.fake.drop_clients()
        t.join(3)
        self.assertEqual(errors, ["no_answer"])


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
            # Anycubic Slicer Next's Workbench messages, on the web topic (UNTESTED on the printer)
            (lambda: p.set_assist([{"option": 3, "value": 1}]),
             ("web", "properties", "write", {"assistant_settings": [{"option": 3, "value": 1}]})),
            (lambda: p.set_printer_name("Shop X"), ("web", "info", "setPrinterName", {"printerName": "Shop X"})),
        ]
        for call, expected in cases:
            self.check(lambda call=call: self.assertTrue(kobra.succeeded(call())), expected, reply=expected[1:3])

    def test_workbench_reads_settle_on_their_answer_only(self):
        """properties/read is answered by a report "read" (or a "report" push) that carries assistant_settings."""
        p = self.printer
        self.fake.reply("properties", "read", {"assistant_settings": []})
        self.check(lambda: self.assertEqual(p.query_properties()["action"], "read"),
                   ("web", "properties", "read", ["assistant_settings"]))
        self.fake.replies[("properties", "read")]["action"] = "report"
        self.assertEqual(p.query_properties()["action"], "report")
        self.fake.replies[("properties", "read")]["data"] = {"hotbed_settings": 1}   # another property: not ours
        self.assertFalse(kobra.succeeded(p.query_properties(timeout=0.3)))

    def test_writes_are_never_settled_by_an_unrelated_report(self):
        """A rename or a Print Assist write settles only on a report of its own action; the shared topics carry
        reads, pushes and other clients' answers too."""
        p = self.printer
        for call, kind, other in ((lambda: p.set_printer_name("A", timeout=0.6), "info", "report"),
                                  (lambda: p.set_assist([{"option": 3, "value": 1}], timeout=0.6), "properties", "read")):
            out = {}
            t = threading.Thread(target=lambda: out.update(r=call()))
            t.start()
            time.sleep(0.15)
            self.fake.report(kind + "/report", {"type": kind, "action": other, "state": "done", "code": 200, "msg": "done",
                                                "msgid": "x", "data": {"assistant_settings": [], "printerName": "B"}})
            t.join(3)
            self.assertFalse(kobra.succeeded(out["r"]), (kind, out["r"]))   # only the ack: no answer of its own
        self.fake.reply("info", "setPrinterName", {})
        self.assertTrue(kobra.succeeded(p.set_printer_name("A")))
        self.fake.reply("properties", "write", {})
        self.assertTrue(kobra.succeeded(p.set_assist([{"option": 3, "value": 1}])))

    def test_fire_and_forget(self):
        p = self.printer
        drying = {"status": 1, "target_temp": 50, "duration": 240, "remain_time": 240}
        cases = [
            (lambda: p.set_fan(40), ("slicer", "fan", "setSpeed", {"fan_speed_pct": 40})),
            (lambda: p.set_light(True), ("slicer", "light", "control", {"type": 3, "status": 1, "brightness": 100})),
            (lambda: p.set_printing_fan("9", 55), ("web", "print", "update", {"taskid": "9", "settings": {"fan_speed_pct": 55}})),
            (p.query_net, ("web", "info", "net", {})),
            (p.query_statistics, ("web", "info", "statistic-query", None)),
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
            (p.list_local_files, ("slicer", "file", "listLocal", {"page_num": 1, "page_size": 200, "path": "/"})),
            (lambda: p.delete_local_files(["a.gcode"]),
             ("slicer", "file", "deleteBatch", {"root": "local", "files": [{"path": "/", "filename": "a.gcode"}]})),
            (lambda: p.request_file_details("a.gcode"),
             ("slicer", "file", "fileDetails", {"root": "local", "filename": "a.gcode"})),
        ]
        for call, expected in cases:
            self.check(call, expected)

    def test_temperature_setters_return_bool(self):
        """L1: like the other setters, True when everything was published."""
        p = self.printer
        self.assertIs(p.set_idle_temperature(200, 60), True)
        self.assertIs(p.set_printing_temperature("1", 200, 60), True)
        self.assertIs(p.set_printing_temperature("1", bed=60), True)
        self.assertIs(p.set_idle_temperature(), False)
        self.assertIs(p.set_printing_temperature("1"), False)
        p.close()
        self.assertIs(p.set_idle_temperature(200), False)
        self.assertIs(p.set_printing_temperature("1", 200, 60), False)

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

    def test_jog_timeout_scales_with_distance(self):
        """M4: a long jog takes longer than 5 s; allow 5 s + 1 s per 5 mm."""
        with mock.patch.object(self.printer, "request", return_value={}) as req:
            self.printer.move_axis(3, 1, 50)
            self.assertEqual(req.call_args.args[3], 15)
            self.printer.move_axis(3, 0, -100)
            self.assertEqual(req.call_args.args[3], 25)
            self.printer.move_axis(1, 0, 1)
            self.assertEqual(req.call_args.args[3], 5.2)

    def test_homing_waits_long_enough(self):
        """Real homing answers axis/report move done only when finished: 41 s after the request."""
        with mock.patch.object(self.printer, "request", return_value={}) as req:
            self.printer.move_axis(5, 2)
            self.assertEqual(req.call_args.args[3], 90)
            self.printer.move_axis(1, 0, 10)
            self.assertEqual(req.call_args.args[3], 7)

    def test_captured_axis_and_temperature_answers(self):
        """The real answers to axis/move and tempature/set settle their requests and succeed."""
        rows = {(s, p["action"]): p for _, s, p in LIVE["motion"]}
        axis, temp = rows[("axis/report", "move")], rows[("tempature/report", "set")]
        self.fake.replies[("axis", "move")] = lambda m: dict(axis, msgid=str(uuid.uuid4()))
        self.fake.replies[("tempature", "set")] = lambda m: dict(temp, msgid=str(uuid.uuid4()))
        self.assertTrue(kobra.succeeded(self.printer.move_axis(5, 2)))
        self.assertTrue(kobra.succeeded(self.printer.request("tempature", "set", {"type": 2}, 2)))


class PrintTests(PrinterCase):
    MAPPING = [{"paint_index": 0, "ams_index": 2, "paint_color": [1, 2, 3, 255], "ams_color": [1, 2, 3, 255],
                "material_type": "PLA"}]

    def test_payload(self):
        payload = kobra.print_file_payload("a b.gcode", 1234, self.MAPPING,
                                           {"auto_leveling": True, "vibration_compensation": True,
                                            "skip_parts": ["o1"]})
        self.assertEqual(payload, {
            "taskid": "-1", "url": "", "filename": "a b.gcode", "md5": "", "filepath": "/",
            "filetype": 1, "project_type": 1, "filesize": 1234,
            "ams_settings": {"use_ams": True, "ams_box_mapping": self.MAPPING},
            "task_settings": {
                "auto_leveling": 1, "vibration_compensation": 1, "flow_calibration": 0, "dry_mode": 0,
                "ai_settings": {"status": 0, "count": 0, "type": 1},
                "timelapse": {"status": 0, "count": 0, "type": 64},
                "drying_settings": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
                "model_objects_skip_parts": ["o1"]}})

    def test_payload_flow_calibration_and_timelapse(self):
        task = kobra.print_file_payload("a.gcode", 1, [], {"flow_calibration": True, "timelapse": True})["task_settings"]
        self.assertEqual((task["flow_calibration"], task["timelapse"]), (1, {"status": 1, "count": 0, "type": 64}))
        task = kobra.print_file_payload("a.gcode", 1, [], {})["task_settings"]
        self.assertEqual((task["flow_calibration"], task["timelapse"]), (0, {"status": 0, "count": 0, "type": 64}))

    def test_payload_defaults(self):
        payload = kobra.print_file_payload("a.gcode", 1, [], None)
        self.assertEqual(payload["ams_settings"], {"use_ams": False, "ams_box_mapping": []})
        self.assertEqual((payload["task_settings"]["auto_leveling"], payload["task_settings"]["vibration_compensation"],
                          payload["task_settings"]["model_objects_skip_parts"]), (0, 0, []))

    def test_start_print_accepted(self):
        self.enterContext(mock.patch.object(kobra, "START_WATCH", 0.2))  # a scripted "done" is not a phase
        for code in (200, 0):
            self.fake.reply("print", "start", {}, state="done", code=code)
            reply = self.printer.start_print(kobra.print_file_payload("a.gcode", 1, [], None))
            self.assertEqual(reply["code"], code)
        self.assertEqual(self.fake.wait_request("print", "start")["data"]["filepath"], "/")

    def test_start_print_ignores_progress_reports(self):
        """Only print/report with action "start" answers print/start; a progress push is not success."""
        self.fake.replies[("print", "start")] = lambda m: {"type": "print", "action": "auto", "state": "printing",
                                                           "code": 200, "data": {"progress": 1}}
        with self.assertRaises(kobra.NoResult):
            self.printer.start_print({}, timeout=0.4)

    def test_start_print_returns_once_the_print_runs(self):
        """Real sequence: start/checking, start/printing, start/hotbed_heating: a preparation phase past
        checking proves the printer found the file, so start_print returns without the full watch."""
        self.fake.print_start = "ok"
        start = time.monotonic()
        reply = self.printer.start_print(kobra.print_file_payload("cube.gcode", 10, [], None))
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual((reply["action"], reply["state"]), ("start", "checking"))

    def test_start_print_abnormal_end_raises(self):
        """Real sequence with a bad filepath: start/checking, start/printing, stop/stopping,
        stop/stoped code 10111 "abnormal end of task" within a second."""
        self.fake.print_start = "abnormal"
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.start_print(kobra.print_file_payload("cube.gcode", 10, [], None))
        self.assertEqual(cm.exception.code, 10111)
        self.assertIn("abnormal end of task", str(cm.exception))
        self.assertNotIsInstance(cm.exception, kobra.NoResult)

    def test_start_print_watch_ends_without_news(self):
        """Only checking/printing and then silence: success after the watch window."""
        self.fake.print_start = "quiet"
        with mock.patch.object(kobra, "START_WATCH", 0.5):
            start = time.monotonic()
            reply = self.printer.start_print({})
        self.assertGreaterEqual(time.monotonic() - start, 0.4)
        self.assertEqual(reply["state"], "checking")

    def stage_start(self, *reports):
        """print/start answered by start/checking, then the given (action, state, code, msg) reports."""
        def answer(m):
            def later():
                for action, state, code, msg in reports:
                    time.sleep(0.05)
                    self.fake.report("print/report", {"type": "print", "action": action, "state": state,
                                                      "code": code, "msg": msg, "data": {"taskid": "-1"}})
            threading.Thread(target=later, daemon=True).start()
            return {"type": "print", "action": "start", "state": "checking", "code": 200, "data": {"taskid": "-1"}}
        self.fake.replies[("print", "start")] = answer

    def test_start_watch_ignores_other_actions_failing(self):
        """M3: another client's refused pause/update during our start window is not our start failing."""
        self.stage_start(("pause", "failed", 10020, "cannot pause"), ("update", "failed", 1, "x"),
                         ("start", "hotbed_heating", 200, "done"))
        self.assertEqual(self.printer.start_print({}, timeout=2)["state"], "checking")

    def test_start_watch_user_stop_is_cancelled(self):
        """L4: stop/stoped code 200 during the watch is a user cancel."""
        self.stage_start(("stop", "stopping", 200, "done"), ("stop", "stoped", 200, "done"))
        with self.assertRaises(kobra.Cancelled) as cm:
            self.printer.start_print({}, timeout=2)
        self.assertNotIn("ended the print at once", str(cm.exception))

    def test_start_watch_abnormal_stop_still_raises(self):
        self.stage_start(("stop", "stopping", 200, "done"), ("stop", "stoped", 10111, "abnormal end of task"))
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.start_print({}, timeout=2)
        self.assertEqual(cm.exception.code, 10111)
        self.assertNotIsInstance(cm.exception, kobra.Cancelled)

    def test_start_print_refused(self):
        for kwargs in ({"state": "failed", "code": 10010, "msg": "busy"}, {"state": "success", "code": 3, "msg": "no"}):
            self.fake.reply("print", "start", {"x": 1}, **kwargs)
            with self.assertRaises(kobra.KobraError) as cm:
                self.printer.start_print({}, timeout=2)
            self.assertIn(str(kwargs["code"]), str(cm.exception))
            self.assertIn(kwargs["msg"], str(cm.exception))
            self.assertEqual(cm.exception.code, kwargs["code"])

    def test_start_print_acknowledged_only_is_not_success(self):
        with self.assertRaises(kobra.NoResult) as cm:
            self.printer.start_print({}, timeout=0.3)
        self.assertIn("received", str(cm.exception))

    def test_start_print_unanswered(self):
        self.fake.send_ack = False
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.start_print({}, timeout=0.3)
        self.assertEqual(cm.exception.code, "no_answer")
        self.assertNotIsInstance(cm.exception, kobra.NoResult)


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
        self.assertEqual(answer, {"code": 200, "data": {"gcode": "job 1.gcode"}, "message": "success"})
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

    def test_upload_from_zip_member(self):
        """C2: a zip member streams straight to the printer, no temp file."""
        payload = os.urandom(700_000)
        zpath = self.source(0)
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Metadata/plate_1.gcode", payload)
        progress = []
        with zipfile.ZipFile(zpath) as z, z.open("Metadata/plate_1.gcode") as member:
            size = z.getinfo("Metadata/plate_1.gcode").file_size
            with mock.patch.object(kobra, "UPLOAD_CHUNK", 65536):
                self.printer.upload("plate.gcode", member, self.fake.upload_url, size=size,
                                    progress=lambda s, t: progress.append((s, t)))
        self.assertEqual(self.fake.uploads[0]["data"], payload)
        self.assertEqual(self.fake.uploads[0]["headers"]["X-File-Length"], str(len(payload)))
        self.assertEqual(progress[-1], (len(payload), len(payload)))
        self.assertGreater(len(progress), 5)

    def test_file_object_needs_size(self):
        with open(self.source(5), "rb") as f, self.assertRaisesRegex(kobra.KobraError, "size"):
            self.printer.upload("a.gcode", f, self.fake.upload_url)

    def test_short_source_is_an_error(self):
        """C2: fewer bytes than announced is never sent as a truncated upload."""
        import io
        with self.assertRaisesRegex(kobra.KobraError, "ended early"):
            self.printer.upload("a.gcode", io.BytesIO(b"x" * 10), self.fake.upload_url, size=100)
        time.sleep(0.2)
        self.assertEqual(self.fake.uploads, [])

    def test_file_object_cancel(self):
        import io
        seen = []
        with self.assertRaises(kobra.Cancelled):
            self.printer.upload("c.gcode", io.BytesIO(os.urandom(600_000)), self.fake.upload_url, size=600_000,
                                progress=lambda s, t: seen.append(s), cancelled=lambda: len(seen) >= 1)
        self.assertEqual(self.fake.uploads, [])

    def test_hostile_upload_url_host_is_ignored(self):
        """M2: only the token is taken from the printer's URL; the file goes to creds.ip."""
        url = "http://203.0.113.7:1/gcode_upload?s=" + self.fake.upload_token
        self.printer.upload("a.gcode", self.source(10), url)
        self.assertEqual(len(self.fake.uploads), 1)

    def test_oversized_upload_answer(self):
        """M3: the upload answer is capped too."""
        self.fake.upload_answer = b'{"m": "' + b"a" * (kobra.MAX_HTTP_BODY + 10) + b'"}'
        with self.assertRaisesRegex(kobra.KobraError, "too large"):
            self.printer.upload("a.gcode", self.source(1), self.fake.upload_url)

    def test_unsafe_filename(self):
        for name in ('a"b.gcode', "a\r\nb.gcode", ""):
            with self.assertRaises(kobra.KobraError):
                self.printer.upload(name, self.source(1), self.fake.upload_url)
        self.assertEqual(self.fake.uploads, [])

    def test_url_without_token(self):
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.upload("a.gcode", self.source(1), "http://127.0.0.1/gcode_upload")
        self.assertNotIn("127.0.0.1", str(cm.exception))

    def test_upload_body_code_checked(self):
        """The printer answers {"code": 200, "data": {"gcode": name}, "message": "success"}; any other code
        in the body is a failed upload even with HTTP 200."""
        self.assertEqual(self.printer.upload("ok.gcode", self.source(3), self.fake.upload_url),
                         {"code": 200, "data": {"gcode": "ok.gcode"}, "message": "success"})
        self.fake.upload_answer = {"code": 10203, "message": "disk full"}
        with self.assertRaises(kobra.KobraError) as cm:
            self.printer.upload("a.gcode", self.source(1), self.fake.upload_url)
        self.assertEqual(cm.exception.code, 10203)
        self.assertIn("disk full", str(cm.exception))
        self.fake.upload_answer = {"message": "no code"}
        with self.assertRaises(kobra.KobraError):
            self.printer.upload("a.gcode", self.source(1), self.fake.upload_url)

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
        with open(tls.server_cert) as f:
            der = ssl.PEM_cert_to_DER_cert(f.read())
        self.assertEqual(p.tls_fingerprint, hashlib.sha256(der).hexdigest())

    def test_plain_session_has_no_fingerprint(self):
        fake = FakeKobra().start()
        self.addCleanup(fake.stop)
        p = kobra.Printer(kobra.fetch_credentials(fake.host, port=fake.http_port), mqtt_port=fake.mqtt_port)
        self.addCleanup(p.close)
        self.assertEqual(p.tls_fingerprint, "")
        p.connect()
        self.assertEqual(p.tls_fingerprint, "")


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
        with self.assertRaisesRegex(probe.StepFailed, "^info/query: the printer received info/query but reported no"):
            self.run_probe()
        self.fake.send_ack = False
        with self.assertRaisesRegex(probe.StepFailed, "^info/query: the printer did not answer"):
            self.run_probe()
        self.fake.send_ack = True
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

    def test_connected_before_first_info_is_busy(self):
        """Before any info report the printer may be printing: not "idle" (which would allow move/heat/print)."""
        s = kobra.State()
        s.connected = True
        self.assertEqual(s.view()["state"], "busy")
        s.apply("tempature/report", {"data": {"curr_nozzle_temp": 20}, "action": "auto"})
        self.assertEqual(s.view()["state"], "busy")
        s.apply("info/report", {"data": {"state": "free", "project": None}, "action": "report"})
        self.assertEqual(s.view()["state"], "idle")
        s.connected = False
        self.assertEqual(s.view()["state"], "offline")

    def test_initial_view_is_offline_and_json(self):
        v = kobra.State().view()
        self.assertEqual(v["state"], "offline")
        json.dumps(v)
        for key in kobra.VIEW_KEYS:
            self.assertIn(key, v)
        self.assertEqual(set(v), set(kobra.VIEW_KEYS))

    def test_device_details_from_info_reports(self):
        """info/net's mac and the counters of statistic-query / statistic-reported (Anycubic Slicer Next's fields)."""
        v = self.s.view()
        self.assertEqual((v["mac"], v["stats"], v["assist"]), ("", {}, None))
        v = self.apply("info/report", {"mac": "AA:BB:CC:00:11:22"}, action="net")
        self.assertEqual(v["mac"], "AA:BB:CC:00:11:22")
        v = self.apply("info/report", {"machine_mac": "11:22"}, action="net")
        self.assertEqual(v["mac"], "11:22")
        v = self.apply("info/report", {"print_total_minutes": 600, "print_count": 12, "material_used_gram_value": 950.5},
                       action="statistic-query")
        self.assertEqual(v["stats"], {"print_minutes": 600, "print_count": 12, "filament_g": 950.5})
        v = self.apply("info/report", {"print_count": 13}, action="statistic-reported")
        self.assertEqual(v["stats"], {"print_minutes": 600, "print_count": 13, "filament_g": 950.5})

    def test_statistics_keep_only_reported_numbers(self):
        """A counter the firmware does not send is absent (the page hides it), never 0; junk is ignored."""
        v = self.apply("info/report", {"project": None, "state": None, "temp": None}, action="statistic-reported")
        self.assertEqual(v["stats"], {})   # what firmware 2.0.2.8 sent in our capture
        v = self.apply("info/report", {"print_count": "x", "print_total_minutes": -1, "material_used_value": 20,
                                       "mac": 5}, action="statistic-query")
        self.assertEqual((v["stats"], v["mac"]), ({"filament_g": 20}, ""))
        v = self.apply("info/report", {"print_count": True})
        self.assertEqual(v["stats"], {"filament_g": 20})

    def test_print_assist_from_properties_report(self):
        v = self.apply("properties/report", {"assistant_settings": [{"option": 0, "value": 1}, {"option": 3, "value": 0},
                                                                     {"option": 2, "value": 1}, {"option": 9, "value": 1},
                                                                     "junk"]}, action="read")
        self.assertEqual(v["assist"], {0: True, 3: False})   # 2 (auto-feed) is set per ACE; 9 is unknown
        v = self.apply("properties/report", {"assistant_settings": {"value": [{"option": 3, "value": 1}]}}, action="write")
        self.assertEqual(v["assist"], {0: True, 3: True})   # merged by option, wrapped form accepted
        v = self.apply("properties/report", {"assistant_settings": [{"option": 4, "value": 1}]}, state="failed")
        self.assertEqual(v["assist"], {0: True, 3: True})   # a refused write changes nothing
        v = self.apply("properties/report", {"assistant_settings": [{"option": "4", "value": "1"}, {"option": "1.5", "value": 1},
                                                                     {"option": True, "value": 1}]})
        self.assertEqual(v["assist"], {0: True, 3: True, 4: True})   # numeric strings read; fractions and bools not

        v = self.apply("properties/report", {"hotbed_settings": 1})
        self.assertEqual(v["assist"], {0: True, 3: True, 4: True})
        json.dumps(v)

    def test_int_accepts_only_plain_integers(self):
        for good, n in ((3, 3), ("3", 3), (" 4 ", 4), ("-1", -1), ("0", 0)):
            self.assertEqual(kobra._int(good), n, repr(good))
        for bad in ("--3", "-", "", "3.0", "1e2", "+3", "\u0663", "3-", True, None, 1.5, [3]):
            self.assertIsNone(kobra._int(bad), repr(bad))

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
                         ("finished", "", 1, 50, 0))  # the finished job's layers stay shown
        self.assertEqual(v["progress"], 100)

    def test_normalised_states(self):
        for raw, norm in (("stoped", "cancelled"), ("canceled", "cancelled"), ("pausing", "paused"),
                          ("pause", "paused"), ("busy", "busy"),
                          ("weird_new_state", "busy"), ("free", "idle"), ("auto_leveling", "printing"),
                          ("resumed", "printing"), ("stopping", "printing"), ("offline", "offline")):
            self.assertEqual(self.apply("print/report", {}, state=raw)["state"], norm, raw)
        self.s.connected = False
        self.assertEqual(self.s.view()["state"], "offline")

    def test_failed_state_from_info_is_error(self):
        """"failed" still normalises to error where it is the printer's state (info project), not a refusal."""
        self.assertEqual(kobra.normalise("failed"), "error")
        self.assertEqual(self.apply("info/report", {"state": "busy", "project": {"state": "failed"}})["state"], "error")

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

    def test_skipped_objects_cleared_on_new_print(self):
        """L4: a new print starts with no skipped objects (Kobralink clears them at print start)."""
        self.apply("print/report", {"filename": "a.gcode", "taskid": "1"}, state="printing")
        self.apply("skip/report", {"objects_skip_parts": ["o1"]})
        self.apply("print/report", {"filename": "a.gcode"}, state="paused")
        self.assertEqual(self.apply("print/report", {}, state="printing")["skipped_objects"], ["o1"])
        self.apply("print/report", {}, state="finished")
        self.assertEqual(self.s.view()["skipped_objects"], ["o1"])  # still visible after the job
        v = self.apply("print/report", {"filename": "b.gcode"}, state="printing")  # non-print -> printing
        self.assertEqual(v["skipped_objects"], [])
        self.apply("skip/report", {"objects_skip_parts": ["o2"]})
        v = self.apply("info/report", {"project": {"state": "printing", "filename": "c.gcode"}})  # new file
        self.assertEqual(v["skipped_objects"], [])
        self.apply("skip/report", {"objects_skip_parts": ["o3"]})
        v = self.apply("print/report", {"taskid": "99"}, state="printing")  # new task, same file
        self.assertEqual(v["skipped_objects"], [])
        self.apply("skip/report", {"objects_skip_parts": ["o4"]})
        v = self.apply("info/report", {"state": "busy"})  # device state only: not a new print
        v = self.apply("print/report", {"taskid": "99"}, state="printing")
        self.assertEqual(v["skipped_objects"], ["o4"])

    def test_buried_storage_and_video(self):
        self.assertTrue(self.apply("video/report", {}, action="startCapture", state="success")["camera_active"])
        self.assertFalse(self.apply("video/report", {}, action="stopCapture", state="success")["camera_active"])

    FW2_PREPARATION = ("nozzle_heating", "nozzle_cooling", "nozzle_wiping", "nozzle_purging", "hotbed_heating",
                       "hotbed_cooling_off", "z_offset_calibrating", "frequency_sweeping", "extfilbox_filament_feeding")
    LEGACY_PREPARATION = ("preheating", "auto_leveling", "checking", "updated", "init")

    def test_preparation_phases_are_printing_and_keep_progress(self):
        """Ported from KX-Bridge tests/test_fw2_print_states.py and test_metadata_and_print_state_reset.py."""
        self.apply("print/report", {"progress": 0}, state="printing")
        for st in self.FW2_PREPARATION + self.LEGACY_PREPARATION + ("nozzle_cooling_off",):
            v = self.apply("print/report", {"progress": 87}, state=st)
            self.assertEqual((v["state"], v["preparing"], v["progress"]), ("printing", True, 0), st)
            v = self.apply("info/report", {"project": {"state": st, "progress": 55}})
            self.assertEqual((v["state"], v["preparing"], v["progress"]), ("printing", True, 0), st)
        v = self.apply("print/report", {"progress": 33}, state="printing")
        self.assertEqual((v["state"], v["preparing"], v["progress"]), ("printing", False, 33))
        for st in ("finished", "stoped", "canceled", "free", "paused"):
            self.assertFalse(self.apply("print/report", {}, state=st)["preparing"], st)

    def test_finished_resets_job_fields(self):
        self.apply("print/report", {"filename": "job.gcode", "progress": 50, "curr_layer": 10, "total_layers": 20},
                   state="printing")
        v = self.apply("print/report", {"filename": "job.gcode"}, state="finished")
        self.assertEqual((v["filename"], v["layer"], v["total_layers"]), ("", 10, 20))  # the job's layers stay
        v = self.apply("print/report", {"filename": "next.gcode", "progress": 0}, action="start", state="checking")
        self.assertEqual((v["progress"], v["layer"], v["total_layers"]), (0, 0, 0))  # a new job resets them
        self.apply("print/report", {"filename": "job.gcode", "curr_layer": 7, "total_layers": 20}, state="printing")
        v = self.apply("info/report", {"project": {"state": "finished"}})
        self.assertEqual((v["layer"], v["total_layers"]), (7, 20))
        for end in ("canceled", "stoped"):  # a cancel still clears them (KX-Bridge test)
            self.apply("print/report", {"curr_layer": 7, "total_layers": 20}, state="printing")
            v = self.apply("print/report", {}, state=end)
            self.assertEqual((v["layer"], v["total_layers"]), (0, 0), end)

    def test_phase_unit_and_channel(self):
        """ACE slot checks report unit_no/channel_no (1-based); other reports carry none."""
        self.assertEqual((self.s.view()["phase_unit"], self.s.view()["phase_channel"]), (None, None))
        v = self.apply("print/report", {"channel_no": 2, "taskid": "-1", "unit_no": 1}, action="start",
                       state="ace_filament_unfeeding")
        self.assertEqual((v["phase_unit"], v["phase_channel"], v["preparing"]), (1, 2, True))
        v = self.apply("tempature/report", {"curr_nozzle_temp": 200}, action="auto")
        self.assertEqual((v["phase_unit"], v["phase_channel"]), (1, 2))  # other kinds leave it
        v = self.apply("print/report", {"target_temp": 215, "taskid": "-1"}, action="start", state="nozzle_heating")
        self.assertEqual((v["phase_unit"], v["phase_channel"]), (None, None))
        v = self.apply("print/report", {"slice_param": {}, "unit_no": 9}, action="getSliceParam", state="done")
        self.assertEqual(v["phase_unit"], None)

    def test_malformed_box_entries(self):
        """A box, slot or status block that is not an object never reaches the slot code (which would raise on
        every status sample); a bad slot keeps its position, so slot numbers stay those of the printer."""
        slot = {"index": 2, "status": 5, "type": "PLA", "color": [1, 2, 3]}
        boxes = [1, "a", None, {"id": 0, "slots": [None, "x", slot], "feed_status": "x", "drying_status": 5,
                                "loaded_slot": -1}, {"id": 1, "slots": "x"}]
        v = self.apply("multiColorBox/report", {"multi_color_box": boxes}, state="success")
        self.assertEqual(v["multi_color_box"], [{"id": 0, "slots": [{}, {}, slot], "loaded_slot": -1},
                                                {"id": 1, "slots": []}])
        data, _ = service.status_data(v)
        self.assertEqual([(s["global_index"], s["status"]) for s in data["slots"]], [(0, 0), (1, 0), (2, 5)])
        bambu.push_status(v, data["slots"], data["mode"])

    def test_non_finite_numbers_read_as_absent(self):
        """JSON 1e999 parses as infinity: never a number the Device tab or the page would choke on."""
        self.apply("print/report", {"curr_layer": 3, "progress": 10}, action="start", state="printing")
        v = self.apply("print/report", {"curr_layer": 1e999, "total_layers": float("nan"), "progress": 1e999},
                       action="start", state="printing")
        self.assertEqual((v["layer"], v["total_layers"], v["progress"]), (0, 0, 10))
        data, _ = service.status_data(v)
        json.dumps(bambu.push_status(v, data["slots"], data["mode"]), allow_nan=False)

    def test_multi_color_box_failure_shapes(self):
        """Ported from KX-Bridge tests/test_multicolor_box_failed_state.py (issue #100)."""
        ok = {"head_tools_model": 1, "multi_color_box": [{"id": -1, "slots": []}, {"id": 0, "slots": [
            {"index": 0, "type": "PLA", "color": [0, 156, 189], "status": 5}]}]}
        self.apply("multiColorBox/report", ok, state="success")
        v = self.apply("multiColorBox/report", ["multi_color_box", [{"filaments": {"id": 2}, "id": 0}]], state="failed")
        self.assertTrue(v["box_set_failed"])
        self.assertEqual(v["multi_color_box"], ok["multi_color_box"])
        self.assertEqual(v["last_error"]["report"], "multiColorBox/report")
        self.assertFalse(self.apply("multiColorBox/report", ok, state="success")["box_set_failed"])
        v = self.apply("multiColorBox/report", ["multi_color_box", []], state="success")
        self.assertEqual(v["multi_color_box"], ok["multi_color_box"])

    def test_buried_report(self):
        """Ported from KX-Bridge tests/test_buried_report.py."""
        self.assertEqual(self.s.view()["storage"], {})
        data = {"task_name": "Smileys_simple_plate(01)_PLA_0.2_16m39s.gcode", "gcode_size": 644437,
                "estimate_duration": 1264, "total_layers": 8, "storage_total": 6481, "storage_used": 898,
                "slicer": "OrcaSlicer"}
        v = self.apply("buried/report", data, type="buried", action="PrintStart", code=200, state="done")
        self.assertEqual(v["storage"], {"total": 6481, "used": 898})
        self.assertEqual(v["last_job"], {"task_name": data["task_name"], "gcode_size": 644437,
                                         "estimate_duration": 1264, "total_layers": 8})
        v = self.apply("buried/report", {"gcode_size": 123, "storage_total": 1})
        self.assertEqual((v["last_job"]["gcode_size"], v["storage"]["total"]), (644437, 6481))

    def test_camera_url_rotation(self):
        """Ported from KX-Bridge tests/test_camera_cache_url_rotation.py (issue #99)."""
        def urls(rtsp):
            return self.apply("info/report", {"urls": {"rtspUrl": rtsp}})
        self.assertEqual((urls("http://printer/live/tokenA")["camera_url_rev"]), 0)
        self.assertEqual(urls("http://printer/live/tokenA")["camera_url_rev"], 0)
        v = urls("http://printer/live/tokenB")
        self.assertEqual((v["camera_url"], v["camera_url_rev"]), ("http://printer/live/tokenB", 1))
        v = self.apply("info/report", {"urls": {"fileUploadurl": "http://u?s=1"}})
        self.assertEqual((v["camera_url"], v["camera_url_rev"]), ("http://printer/live/tokenB", 1))

    def test_captured_info_report(self):
        v = self.apply_capture("info/report", cap.INFO_REPORT)
        self.assertEqual((v["state"], v["kobra_state"], v["preparing"]), ("idle", "free", False))
        self.assertEqual((v["printer_name"], v["model"], v["firmware"]), ("Anycubic Kobra X", "Anycubic Kobra X", "2.0.2.8"))
        self.assertEqual((v["nozzle_temp"], v["bed_temp"], v["nozzle_target"], v["bed_target"]), (37, 47, 0, 0))
        self.assertEqual((v["fan_pct"], v["aux_fan_pct"], v["speed_mode"]), (0, 0, 2))
        self.assertEqual(v["camera_url"], "http://192.0.2.10:18088/live/StReAmTk")
        self.assertTrue(v["upload_url"].startswith("http://192.0.2.10:18910/gcode_upload?s="))
        self.assertEqual(v["storage"], {})
        self.assertEqual((v["filename"], v["progress"], v["layer"]), ("", 0, 0))  # project is null
        self.assertEqual(v["features"]["delete_batch_support"], True)
        self.assertEqual(v["features"]["drying_first_support"], False)
        self.assertTrue(all(k.endswith("_support") for k in v["features"]))
        self.assertEqual(v["last_project"]["filename"], "plate_B_PLA_0.2.gcode")
        self.assertEqual((v["last_project"]["state"], v["last_project"]["total_layers"]), ("finished", 750))
        json.dumps(v)

    def test_captured_box_light_temp_and_files(self):
        v = self.apply_capture("multiColorBox/report", cap.MULTICOLORBOX_GETINFO)
        box = v["multi_color_box"][0]
        self.assertEqual((box["humidity"], box["temp"], box["model_id"], box["status"]), (32, 45, 40002, 1))
        slot = box["slots"][0]
        self.assertEqual((slot["consumables_percent"], slot["weight"], slot["brand_name"], slot["edit_status"]),
                         (100, 1000, "public", 1))
        self.assertEqual(slot["color_group"], [[225, 6, 0, 255]])
        self.assertEqual((v["head_tools_model"], v["box_set_failed"]), (0, False))
        v = self.apply_capture("light/report", cap.LIGHT_CONTROL)
        self.assertEqual((v["light_on"], v["light_brightness"]), (True, 100))
        v = self.apply_capture("tempature/report", cap.TEMPATURE_AUTO)
        self.assertEqual((v["nozzle_temp"], v["bed_temp"]), (37, 46))
        v = self.apply_capture("file/report", cap.FILE_LISTLOCAL)
        self.assertEqual(v["files"], [{"filename": "plate_A_PLA_0.16.gcode", "size": 66969765,
                                       "timestamp": 1794613802.793}])
        v = self.apply_capture("file/report", cap.FILE_FILEDETAILS)
        d = v["file_details"]
        self.assertEqual((d["estimated_time_s"], d["layer_count"], len(d["paint_infos"])), (25816, 1875, 2))
        self.assertEqual(len(d["objects_skip_parts"]), 2)
        before = self.s.view()
        v = self.apply_capture("file/report", cap.FILE_DELETEBATCH)
        self.assertEqual((v["files"], v["file_details"], v["last_error"]), (before["files"], d, None))
        v = self.apply_capture(cap.ACK_SUFFIX, cap.ACK)
        self.assertEqual({k: x for k, x in v.items() if k != "updated_at"},
                         {k: x for k, x in before.items() if k != "updated_at"})

    def test_file_timestamps_seconds_kept(self):
        v = self.apply("file/report", {"records": [{"filename": "a", "size": 1, "timestamp": 1700000000}]},
                       action="listLocal", code=200)
        self.assertEqual(v["files"][0]["timestamp"], 1700000000)

    def apply_capture(self, suffix, payload):
        self.s.apply(suffix, json.loads(json.dumps(payload)))
        return self.s.view()

    # live print capture -------------------------------------------------------------------------------
    def replay(self, rows):
        """Apply rows; return [(t, suffix, payload, view)] for every row."""
        out = []
        for t, suffix, payload in rows:
            self.s.apply(suffix, copy.deepcopy(payload))
            out.append((t, suffix, payload, self.s.view()))
        return out

    def print_rows(self):
        rows = LIVE["print"]
        starts = [i for i, (_, s, p) in enumerate(rows) if s == "print/report" and p.get("state") == "checking"]
        self.assertEqual(len(starts), 2, "capture: a failed start then a working one")
        return rows[:starts[1]], rows[starts[1]:]

    def test_live_abnormal_start(self):
        """Bad filepath: the printer ends the task itself with stoped code 10111: an error, not a cancel."""
        failed, _ = self.print_rows()
        steps = self.replay(failed)
        stoped = next(i for i, (_, s, p, _) in enumerate(steps) if p.get("state") == "stoped" and s == "print/report")
        v = steps[stoped][3]
        self.assertEqual((v["state"], v["kobra_state"]), ("error", "stoped"))
        self.assertEqual(v["last_error"], {"report": "print/report", "action": "stop", "code": 10111,
                                           "msg": "abnormal end of task"})
        after = [v for _, s, _, v in steps[stoped:] if v["kobra_state"] == "stoped"]
        self.assertTrue(all(v["state"] == "error" for v in after))  # info project "stoped" keeps it an error
        free = [v for _, s, p, v in steps[stoped:] if s == "info/report" and p["data"].get("state") == "free"]
        self.assertEqual(free[-1]["state"], "idle")  # info free after the end; the slice ends on workReport busy
        self.assertEqual(steps[-1][3]["last_error"]["code"], 10111)
        self.assertEqual(steps[-1][3]["state"], "busy")

    def test_stoped_with_200_is_a_cancel(self):
        v = self.apply("print/report", {"taskid": "-1"}, action="stop", state="stoped", code=200, msg="done")
        self.assertEqual((v["state"], v["last_error"]), ("cancelled", None))
        self.apply("print/report", {}, action="stop", state="stoped", code=10111, msg="abnormal end of task")
        self.assertEqual(self.s.view()["state"], "error")
        self.assertEqual(self.apply("print/report", {}, action="start", state="checking")["state"], "printing")

    def test_live_print_run(self):
        """Every row of the working print: never "busy" once the job started, preparing through the
        preparation and ACE phases, job numbers frozen while preparing, file name without the path."""
        failed, run = self.print_rows()
        self.replay(failed)
        steps = self.replay(run)
        for t, suffix, payload, v in steps:
            ended = v["kobra_state"] in kobra.TERMINAL or v["kobra_state"] == "free"
            if not ended:
                self.assertEqual(v["state"], "printing", (t, suffix, payload.get("action"), payload.get("state")))
                self.assertIn(v["filename"], ("kobracontrol-cube10.gcode",), (t, suffix))
            if suffix == "print/report" and payload.get("action") == "start":
                st = payload["state"]
                prep = st not in ("printing", "finished")  # incl. the cooling phases after the last layer
                self.assertEqual(v["preparing"], prep, (t, st))
        by_state = {p["state"]: v for _, s, p, v in steps if s == "print/report" and p.get("action") == "start"}
        for st in ("hotbed_heating", "nozzle_heating", "ace_filament_unfeeding", "ace_filament_feeding",
                   "auto_leveling", "z_offset_calibrating", "nozzle_purging", "nozzle_wiping", "nozzle_cooling",
                   "frequency_sweeping", "hotbed_cooling_off"):
            self.assertEqual((by_state[st]["state"], by_state[st]["preparing"]), ("printing", True), st)
        first50 = next(i for i, (_, _, _, v) in enumerate(steps) if v["total_layers"] == 50)
        for t, _, _, v in steps[first50:]:
            if v["state"] == "printing":  # ACE phases report total_layers 0: frozen instead
                self.assertEqual(v["total_layers"], 50, t)
        progress = [(v["progress"], p.get("state")) for _, s, p, v in steps
                    if s == "print/report" and p.get("action") == "start"]
        values = [x for x, _ in progress]
        self.assertEqual(values, sorted(values), "progress never goes back within a job")
        row, mid = next((p["data"], v) for _, s, p, v in steps
                        if s == "print/report" and (p.get("data") or {}).get("curr_layer") == 47)
        self.assertEqual((mid["state"], mid["preparing"], mid["layer"], mid["total_layers"]), ("printing", False, 47, 50))
        self.assertEqual((mid["progress"], mid["elapsed_s"], mid["remaining_s"]),
                         (row["progress"], row["print_time"] * 60, row["remain_time"] * 60))
        done = next(v for _, s, p, v in steps if s == "print/report" and p.get("state") == "finished")
        self.assertEqual((done["state"], done["progress"], done["filename"], done["layer"], done["total_layers"]),
                         ("finished", 100, "", 50, 50))
        channels = {(v["phase_unit"], v["phase_channel"]) for _, s, p, v in steps
                    if p.get("state") in ("ace_filament_unfeeding", "ace_filament_feeding")}
        self.assertEqual(channels, {(1, 1), (1, 2), (1, 3), (1, 4)})
        self.assertEqual(steps[-1][3]["state"], "idle")  # info free, project null after the job
        slice_params = [v for _, s, p, v in steps if p.get("action") == "getSliceParam"]
        self.assertTrue(slice_params)
        self.assertTrue(all(v["state"] == "printing" and v["kobra_state"] != "done" for v in slice_params))
        self.assertTrue(any(s == "status/report" for _, s, _ in LIVE["print"]))  # replayed in both parts
        self.assertTrue(any(s == "skip/report" and p.get("action") == "query_obj" for _, s, p, _ in steps))
        json.dumps(steps[-1][3])

    def test_print_report_actions_that_are_not_the_job(self):
        self.apply("print/report", {"filename": "/a.gcode", "progress": 10}, action="start", state="printing")
        for action in ("getSliceParam", "somethingNew"):
            v = self.apply("print/report", {"slice_param": {"remain_time": 5}, "progress": 99}, action=action,
                           state="done", code=200)
            self.assertEqual((v["state"], v["kobra_state"], v["progress"], v["filename"]),
                             ("printing", "printing", 10, "a.gcode"))
        v = self.apply("status/report", None, action="workReport", state="busy", code=200)
        self.assertEqual(v["kobra_state"], "printing")
        v = self.apply("skip/report", {"objects_skip_parts": []}, action="query_obj", state="done", code=200)
        self.assertEqual((v["state"], v["kobra_state"]), ("printing", "printing"))

    def test_unknown_state_during_a_job_is_preparing(self):
        self.apply("print/report", {"filename": "a.gcode"}, action="start", state="checking")
        v = self.apply("print/report", {}, action="start", state="brand_new_phase")
        self.assertEqual((v["state"], v["preparing"]), ("printing", True))
        v = self.apply("info/report", {"state": "busy", "project": {"state": "another_phase", "filename": "a.gcode"}})
        self.assertEqual((v["state"], v["preparing"]), ("printing", True))
        self.apply("info/report", {"state": "free", "project": None})
        v = self.apply("info/report", {"state": "homing_whatever", "project": None})
        self.assertEqual((v["state"], v["preparing"]), ("busy", False))

    def test_progress_resets_when_a_job_begins_by_any_route(self):
        """M1: finished at 100, then job B's reports arrive without its "checking" (missed while reconnecting)."""
        self.apply("print/report", {"progress": 99, "curr_layer": 50, "total_layers": 50}, action="start",
                   state="printing")
        self.apply("print/report", {"progress": 100}, action="start", state="finished")
        v = self.s.view()
        self.assertEqual((v["state"], v["progress"], v["layer"], v["total_layers"]), ("finished", 100, 50, 50))
        v = self.apply("print/report", {"progress": 5, "curr_layer": 2, "total_layers": 80}, action="start",
                       state="printing")
        self.assertEqual((v["progress"], v["layer"], v["total_layers"]), (5, 2, 80))
        # a cancel at 30, then info free, then job C via info project only
        self.apply("print/report", {"progress": 30}, action="start", state="printing")
        self.apply("print/report", {"progress": 30}, action="stop", state="stoped", code=200)
        v = self.apply("info/report", {"state": "free", "project": None})
        self.assertEqual((v["state"], v["progress"]), ("idle", 0))
        v = self.apply("info/report", {"state": "busy", "project": {"state": "printing", "progress": 3, "curr_layer": 1,
                                                                    "total_layers": 9, "filename": "c.gcode"}})
        self.assertEqual((v["state"], v["progress"], v["layer"], v["total_layers"]), ("printing", 3, 1, 9))

    def test_failed_print_report_does_not_end_the_job(self):
        """M2: a refused pause/stop/update (from any client) records last_error, the job keeps running."""
        self.apply("print/report", {"progress": 40}, action="start", state="printing")
        v = self.apply("print/report", None, action="pause", state="failed", code=10020, msg="cannot pause")
        self.assertEqual((v["state"], v["kobra_state"], v["progress"]), ("printing", "printing", 40))
        self.assertEqual(v["last_error"], {"report": "print/report", "action": "pause", "code": 10020,
                                           "msg": "cannot pause"})
        self.apply("print/report", {}, action="start", state="nozzle_heating")
        v = self.apply("print/report", None, action="update", state="failed", code=1)
        self.assertEqual((v["state"], v["preparing"]), ("printing", True))

    def test_speed_mode_from_any_print_report(self):
        """L5: settings.print_speed_mode counts even on a print/report outside the job actions."""
        v = self.apply("print/report", {"settings": {"print_speed_mode": 3}}, action="update", state="done", code=200)
        self.assertEqual((v["speed_mode"], v["kobra_state"]), (3, ""))

    def test_work_report_while_idle(self):
        """M4: status/report workReport busy|free shows a move/home at once while no job runs."""
        self.apply("info/report", {"state": "free", "project": None})
        v = self.apply("status/report", None, action="workReport", state="busy", code=200)
        self.assertEqual(v["state"], "busy")
        v = self.apply("status/report", None, action="workReport", state="free", code=200)
        self.assertEqual(v["state"], "idle")
        self.apply("print/report", {"progress": 10}, action="start", state="printing")
        for st in ("free", "busy"):  # during a job it changes nothing
            v = self.apply("status/report", None, action="workReport", state=st, code=200)
            self.assertEqual((v["state"], v["kobra_state"]), ("printing", "printing"))
        self.apply("status/report", None, action="other", state="free", code=200)
        self.assertEqual(self.s.view()["kobra_state"], "printing")

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
