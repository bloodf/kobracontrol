"""Spooler presence and stock list (peers.py). Files go to temporary folders."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import peers  # noqa: E402

NOW = 1_800_000_000.0


def spooler_presence(session="s1", ts=NOW, state="active", pid=None, **extra):
    return {"schema": peers.SCHEMA, "version": 1, "plugin": "spooler", "plugin_version": "0.21.0", "session": session,
            "pid": os.getpid() if pid is None else pid, "started": ts - 100, "ts": ts, "state": state,
            "provides": {"stock": 1}, "spoolman": {"origin": "http://box:7912", "source": "spoolman"}, **extra}


def stock_doc(session="s1", gen=3, ts=NOW, url="http://box:7912", spools=None, **extra):
    return {"schema": peers.STOCK_SCHEMA, "version": 1, "session": session, "seq": 1, "ts": ts,
            "origin": {"url": url, "gen": gen, "source": "spoolman"}, "low_stock_grams": 100,
            "spools": spools if spools is not None else [
                {"id": 7, "filament_id": 70, "name": "Matte Black", "vendor": "Generic", "material": "PLA",
                 "colour": "111111", "remaining": 500.0, "initial": 1000.0, "location": "Shelf A", "low": False},
                {"id": 11, "filament_id": 110, "name": "White", "vendor": "Generic", "material": "PETG",
                 "colour": "#FAFAFA", "remaining": 40.0, "location": "", "low": True, "use_first": True}], **extra}


class Root:
    """An OrcaSlicer data folder with Spooler's files in it."""

    def __init__(self, test):
        self.path = tempfile.mkdtemp(prefix="peers-")
        test.addCleanup(shutil.rmtree, self.path, ignore_errors=True)

    def write(self, name, doc, plugin="spooler"):
        folder = Path(self.path, plugin)
        folder.mkdir(exist_ok=True)
        (folder / name).write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")

    def read(self, plugin="kobracontrol"):
        return json.loads(Path(self.path, plugin, peers.PRESENCE_FILE).read_text(encoding="utf-8"))


class PresenceStatusTests(unittest.TestCase):
    def test_only_a_fresh_active_file_of_this_process_counts(self):
        cases = [
            (None, "absent"),
            ({**spooler_presence(), "schema": "x"}, "incompatible"),
            ({**spooler_presence(), "version": 2}, "incompatible"),
            ({**spooler_presence(), "plugin": "kobracontrol"}, "incompatible"),
            ({**spooler_presence(), "session": ""}, "incompatible"),
            ({**spooler_presence(), "ts": "now"}, "incompatible"),
            (spooler_presence(pid=os.getpid() + 1), "other_process"),
            (spooler_presence(state="stopped"), "stopped"),
            (spooler_presence(ts=NOW - peers.FRESH - 1), "stale"),
            (spooler_presence(ts=NOW + 60), "stale"),
            (spooler_presence(), "active"),
        ]
        for doc, want in cases:
            self.assertEqual(peers.peer_status(doc, NOW)[0], want, doc)

    def test_origins_are_compared_without_credentials_case_or_default_port(self):
        self.assertEqual(peers.normalize_origin("HTTP://User:pw@Box:7912/"), "http://box:7912")
        self.assertEqual(peers.normalize_origin("box:80"), "http://box")
        self.assertEqual(peers.normalize_origin("https://box:443/spoolman/"), "https://box/spoolman")
        for bad in ("", None, "ftp://box", "http://", "http://box:99999"):
            self.assertEqual(peers.normalize_origin(bad), "", bad)


class StockParseTests(unittest.TestCase):
    def test_rows_are_checked_and_keyed_to_the_running_spooler(self):
        bad_rows = [{"id": 0}, {"id": True}, {"id": "7"}, "x", {"id": 5, "colour": "red", "remaining": "lots", "name": 3}]
        parsed = peers.parse_stock(stock_doc(spools=bad_rows + stock_doc()["spools"]), {"session": "s1"}, NOW)
        self.assertEqual(parsed["state"], "ok")
        self.assertEqual(parsed["key"], "s1:3")
        self.assertEqual([r["id"] for r in parsed["rows"]], [5, 7, 11])
        self.assertEqual(parsed["rows"][0], {**parsed["rows"][0], "colour": None, "remaining": None, "name": ""})
        self.assertEqual(parsed["rows"][1]["colour"], "#111111")
        self.assertEqual(parsed["origin"], "http://box:7912")

    def test_old_run_other_source_errors_and_age(self):
        self.assertEqual(peers.parse_stock(stock_doc(session="old"), {"session": "s1"}, NOW)["state"], "mismatch")
        other = stock_doc()
        other["origin"]["source"] = "bambu"
        self.assertEqual(peers.parse_stock(other, {"session": "s1"}, NOW)["state"], "error")
        self.assertIn("couldn't read", peers.parse_stock(stock_doc(error="HTTP 500"), {"session": "s1"}, NOW)["text"])
        self.assertEqual(peers.parse_stock({**stock_doc(), "version": 9}, {"session": "s1"}, NOW)["state"], "error")
        stale = peers.parse_stock(stock_doc(ts=NOW - peers.STOCK_STALE - 1), {"session": "s1"}, NOW)
        self.assertEqual((stale["state"], len(stale["rows"])), ("stale", 2))   # still shown, marked

    def test_every_stock_state_carries_a_reason_code_for_the_page(self):
        other = stock_doc()
        other["origin"]["source"] = "bambu"
        cases = [(None, "waiting"), ({**stock_doc(), "version": 9}, "format"), (stock_doc(session="old"), "earlier_run"),
                 (other, "not_spoolman"), (stock_doc(error="HTTP 500"), "spoolman_error"),
                 ({**stock_doc(), "spools": "x"}, "no_list"), (stock_doc(ts=NOW - peers.STOCK_STALE - 1), "stale"),
                 (stock_doc(), "ok")]
        for doc, code in cases:
            with self.subTest(code=code):
                self.assertEqual(peers.parse_stock(doc, {"session": "s1"}, NOW)["code"], code)
        self.assertEqual(peers.parse_stock(stock_doc(error="HTTP 500"), {"session": "s1"}, NOW)["detail"], "HTTP 500")


class PresenceFileTests(unittest.TestCase):
    def test_start_publishes_wants_and_stop_says_stopped(self):
        root = Root(self)
        link = peers.SpoolerLink(root.path, "1.2.3", log=lambda m: None)
        link.presence.heartbeat = 0.05
        link.presence.start()
        first = root.read()
        self.assertEqual((first["state"], first["plugin"], first["pid"], first["plugin_version"]),
                         ("active", "kobracontrol", os.getpid(), "1.2.3"))
        link.want_stock(refresh=True)
        deadline = time.time() + 3
        while time.time() < deadline and root.read()["wants"]["stock_request"] != 1:
            time.sleep(0.02)
        self.assertEqual(root.read()["wants"]["stock_request"], 1)
        self.assertGreater(root.read()["wants"]["stock_until"], time.time())
        link.presence.stop()
        last = root.read()
        self.assertEqual((last["state"], last["session"]), ("stopped", first["session"]))
        self.assertNotIn("wants", last)

    def test_a_new_load_is_a_new_session(self):
        root = Root(self)
        a = peers.SpoolerLink(root.path, log=lambda m: None)
        b = peers.SpoolerLink(root.path, log=lambda m: None)
        self.assertNotEqual(a.presence.session, b.presence.session)

    def test_unwritable_folder_is_logged_once_and_never_raises(self):
        logs = []
        presence = peers.Presence(os.path.join(Root(self).path, "file"), log=logs.append)
        Path(presence.root).write_text("not a folder")
        self.assertFalse(presence.write())
        self.assertFalse(presence.write())
        self.assertEqual(len(logs), 1)

    def test_data_root_from_storage(self):
        root = os.path.abspath(os.path.join(os.sep, "x", "OrcaSlicer"))  # D:\x\OrcaSlicer on Windows
        self.assertEqual(peers.data_root(os.path.join(root, "orca_plugins", "plugin_data", "kobracontrol")), root)
        self.assertEqual(peers.data_root("/somewhere/else"), "")


class SpoolerLinkTests(unittest.TestCase):
    def link(self, root):
        return peers.SpoolerLink(root.path, log=lambda m: None, clock=lambda: NOW)

    def test_absent_then_active_with_stock(self):
        root = Root(self)
        link = self.link(root)
        self.assertEqual(link.spooler()["state"], "absent")
        peer, stock = link.stock()
        self.assertEqual((peer["state"], stock["state"], stock["code"]), ("absent", "unavailable", "unavailable"))
        root.write(peers.PRESENCE_FILE, spooler_presence())
        root.write(peers.STOCK_FILE, stock_doc(spools=[dict(stock_doc()["spools"][0], u1_bound=True, kobra_bound=True)]))
        peer, stock = link.stock()
        self.assertEqual((peer["state"], peer["origin"], stock["state"]), ("active", "http://box:7912", "ok"))
        for key in ("bound", "u1_bound", "kobra_bound"):   # binding is kobracontrol's own knowledge, never Spooler's
            self.assertNotIn(key, stock["rows"][0])

    def test_stock_without_the_stock_capability_is_incompatible_and_unreadable_file_is_reported(self):
        root = Root(self)
        link = self.link(root)
        root.write(peers.PRESENCE_FILE, spooler_presence(provides={}))
        self.assertEqual(link.spooler()["state"], "incompatible")
        root.write(peers.PRESENCE_FILE, spooler_presence())
        root.write(peers.STOCK_FILE, "{broken")
        self.assertEqual(link.stock()[1]["code"], "unreadable")

    def test_want_stock_counts_requests(self):
        link = self.link(Root(self))
        link.want_stock()
        link.want_stock(refresh=True)
        self.assertEqual(link._wants(), {"stock_until": NOW + peers.STOCK_WANT, "stock_request": 1})


if __name__ == "__main__":
    unittest.main()
