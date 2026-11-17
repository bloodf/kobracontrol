"""requirements.py: the checks for ffmpeg and Anycubic Slicer Next, their cache, and the page message."""

import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import camera  # noqa: E402
import requirements  # noqa: E402
from test_service import wait  # noqa: E402


class Checks(unittest.TestCase):
    def test_ffmpeg_found_on_path(self):
        with mock.patch.object(camera.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                mock.patch.object(camera.os.path, "isfile", side_effect=lambda p: p == "/usr/bin/ffmpeg"), \
                mock.patch.object(camera.os, "access", return_value=True):
            self.assertEqual(requirements.check_ffmpeg(), {"id": "ffmpeg", "state": "ok", "details": "/usr/bin/ffmpeg"})

    def test_ffmpeg_missing(self):
        with mock.patch.object(camera.shutil, "which", return_value=None), \
                mock.patch.object(camera.os.path, "isfile", return_value=False):
            self.assertEqual(requirements.check_ffmpeg("/nowhere/ffmpeg"), {"id": "ffmpeg", "state": "missing", "details": ""})

    def test_ffmpeg_setting_is_used_first(self):
        with mock.patch.object(camera.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                mock.patch.object(camera.os.path, "isfile", return_value=True), \
                mock.patch.object(camera.os, "access", return_value=True):
            self.assertEqual(requirements.check_ffmpeg("/opt/ff/ffmpeg")["details"], "/opt/ff/ffmpeg")

    def test_anycubic_slicer_found(self):
        tmp = tempfile.mkdtemp()
        app = os.path.join(tmp, "AnycubicSlicerNext")
        os.mkdir(app)
        self.assertEqual(requirements.check_anycubic_slicer([os.path.join(tmp, "nope"), app]),
                         {"id": "anycubic_slicer", "state": "ok", "details": app})

    def test_anycubic_slicer_missing_at_the_default_locations(self):
        tmp = tempfile.mkdtemp()
        with mock.patch.object(requirements.certs, "default_locations", return_value=[os.path.join(tmp, "x")]):
            self.assertEqual(requirements.check_anycubic_slicer()["state"], "missing")

    def test_anycubic_slicer_refused_is_unknown(self):
        with mock.patch.object(requirements.os, "stat", side_effect=PermissionError("denied")):
            self.assertEqual(requirements.check_anycubic_slicer(["/Applications/AnycubicSlicerNext.app"])["state"], "unknown")


class CheckerCache(unittest.TestCase):
    def setUp(self):
        self.runs, self.done = [], threading.Event()
        patch_ff = mock.patch.object(requirements, "check_ffmpeg",
                                     side_effect=lambda s: self.runs.append(s) or requirements.item("ffmpeg", "ok", s or "/bin/ffmpeg"))
        patch_ac = mock.patch.object(requirements, "check_anycubic_slicer", return_value=requirements.item("anycubic_slicer", "missing"))
        for p in (patch_ff, patch_ac):
            p.start()
            self.addCleanup(p.stop)
        self.checker = requirements.Checker(self.done.set, log=lambda m: None)

    def settle(self):
        wait(lambda: not self.checker.checking)
        self.done.clear()

    def test_not_checked_until_asked(self):
        self.assertEqual(self.runs, [])
        self.assertFalse(self.checker.checking)
        self.assertEqual([i["state"] for i in self.checker.items()], ["unknown", "unknown"])
        self.assertEqual(self.checker.ffmpeg(), "")   # unchecked: the camera waits

    def test_cached_until_check_again_or_a_new_setting(self):
        self.checker.ensure("")
        self.settle()
        self.assertEqual(self.checker.ffmpeg(), "/bin/ffmpeg")
        self.checker.ensure("")                     # cached: no second check
        self.assertFalse(self.checker.checking)
        self.assertEqual(self.runs, [""])
        self.checker.ensure("", force=True)         # Check again
        self.settle()
        self.checker.ensure("/opt/ffmpeg")          # the ffmpeg path setting changed
        self.settle()
        self.assertEqual(self.runs, ["", "", "/opt/ffmpeg"])
        self.assertEqual(self.checker.ffmpeg(), "/opt/ffmpeg")
        self.assertEqual([i["state"] for i in self.checker.items()], ["ok", "missing"])

    def test_a_failing_check_is_unknown(self):
        with mock.patch.object(requirements, "check_ffmpeg", side_effect=OSError("boom")):
            self.checker.ensure("x")
            self.settle()
        self.assertEqual(self.checker.items()[0], {"id": "ffmpeg", "state": "unknown", "details": ""})
        self.assertEqual(self.checker.ffmpeg(), "")

    def test_message(self):
        m = requirements.message(self.checker, True, "http://spoolman.lan:7912")
        self.assertEqual(m["type"], "requirements")
        self.assertEqual({i["id"]: i["state"] for i in m["items"]},
                         {"ffmpeg": "unknown", "anycubic_slicer": "unknown", "printer_agents": "ok", "spoolman": "ok"})
        m = requirements.message(self.checker, False, "")
        self.assertEqual({i["id"]: i["state"] for i in m["items"]}["printer_agents"], "unknown")   # "not detected"
        self.assertEqual({i["id"]: i["state"] for i in m["items"]}["spoolman"], "missing")


class NothingAtImport(unittest.TestCase):
    def test_import_runs_no_check(self):
        import importlib
        with mock.patch.object(camera.shutil, "which", side_effect=AssertionError("checked at import")), \
                mock.patch.object(requirements.certs, "default_locations", side_effect=AssertionError("checked at import")):
            importlib.reload(requirements)
            requirements.Checker()   # nor on construction


if __name__ == "__main__":
    unittest.main()
