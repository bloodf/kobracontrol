"""Slot links shared with Spooler: Spoolman's location is the one link store. A location Spooler writes ("<printer
model> S<n>") is read here, a renamed printer included; a link made here moves this plugin's presence "links" and
names the printer, so Spooler's open tab re-reads at once and uses that name; and the page's refresh setting."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import peers  # noqa: E402
import settings  # noqa: E402
import spoolman as sm  # noqa: E402
from test_peers import spooler_presence  # noqa: E402
from test_service import Base, FakeSpoolman  # noqa: E402

NOW = 1_800_000_000.0


def sp(sid, location, last_used=""):
    return {"id": sid, "location": location, "last_used": last_used}


class SpoolerWrittenLocations(unittest.TestCase):
    def test_spooler_format_is_read(self):
        self.assertEqual(sm.bindings_from_locations([sp(7, "Anycubic Kobra X S2")], "Anycubic Kobra X"), {1: 7})

    def test_renamed_printer_reads_the_model_name(self):
        self.assertEqual(sm.bindings_from_locations([sp(7, "Anycubic Kobra X S6")], "Workshop"), {5: 7})
        self.assertEqual(sm.location_score("anycubic  kobra x s6", "Workshop", 5), 1)

    def test_own_name_beats_the_model_name(self):
        spools = [sp(7, "Anycubic Kobra X S1", "2026-02-01"), sp(8, "Workshop S1", "2026-01-01")]
        self.assertEqual(sm.bindings_from_locations(spools, "Workshop"), {0: 8})
        self.assertEqual(sm.location_score("Workshop S1", "Workshop", 0), 2)

    def test_another_printers_name_never_binds(self):
        self.assertEqual(sm.bindings_from_locations([sp(7, "Garage S1")], "Workshop"), {})


class RefreshSetting(unittest.TestCase):
    def test_default_range_and_off(self):
        st = settings.Store(os.path.join(tempfile.mkdtemp(), "s.json"))
        self.assertEqual(st.effective()["spoolman_refresh_s"], 30)
        for value, want in ((10, 10), (300, 300), (0, 0), (9, 0), (301, 0), (True, 0), ("30", 0), (45, 45)):
            st.update({"spoolman_refresh_s": 0})
            st.update({"spoolman_refresh_s": value})
            self.assertEqual(st.effective()["spoolman_refresh_s"], want, value)


class LinksSignal(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.now = NOW
        self.link = peers.SpoolerLink(self.root, "1.0", log=lambda *_: None, clock=lambda: self.now)

    def test_presence_carries_links_and_the_printer(self):
        doc = self.link.presence.doc()
        self.assertEqual(doc["links"], 0)
        self.assertNotIn("printer", doc)
        self.link.set_printer("kobra.local", "Workshop")
        self.now += 1
        self.link.links_changed()
        doc = self.link.presence.doc()
        self.assertEqual(doc["links"], int((NOW + 1) * 1000))
        self.assertEqual(doc["printer"], {"host": "kobra.local", "name": "Workshop"})

    def test_spoolers_links_are_read(self):
        os.makedirs(os.path.join(self.root, "spooler"))
        with open(os.path.join(self.root, "spooler", "presence.json"), "w") as f:
            json.dump(spooler_presence(ts=NOW, links=1234), f)
        self.assertEqual(self.link.spooler()["links"], 1234)


class ServiceSync(Base):
    def setUp(self):
        FakeSpoolman.locations = {}
        super().setUp()
        self.svc.peers = mock.Mock()

    def tearDown(self):
        FakeSpoolman.locations = {}

    def test_a_link_spooler_wrote_shows_on_the_next_read(self):
        self.assertEqual(self.run_cmd("spools")["result"]["bindings"], {})
        FakeSpoolman.locations[7] = "Anycubic Kobra X S3"
        self.assertEqual(self.run_cmd("spools")["result"]["bindings"], {"2": 7})
        self.svc.peers.set_printer.assert_called_with(self.fake.host, "Anycubic Kobra X")

    def test_link_and_unlink_here_tell_spooler(self):
        self.run_cmd("spools")
        self.run_cmd("bind", slot=0, spool_id=7)
        self.assertEqual(self.svc.peers.links_changed.call_count, 1)
        self.run_cmd("unbind", slot=0)
        self.assertEqual(self.svc.peers.links_changed.call_count, 2)


if __name__ == "__main__":
    unittest.main()
