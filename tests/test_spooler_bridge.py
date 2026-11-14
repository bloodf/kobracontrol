import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import spooler_bridge as sb  # noqa: E402

NOW = 1_800_000_000.0


def preset(name, vendor="Generic", colour="#FF0000", compatible=("Anycubic Kobra X",), bundle=sb.BUNDLE_ID):
    return {"name": sb.NAME_PREFIX + name, "bundle_id": bundle, "compatible_printers": list(compatible),
            "colour": colour, "vendor": vendor}


class DetectTests(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(sb.detect([], []), {"installed": False, "presets": 0})
        self.assertTrue(sb.detect(["spooler"], [])["installed"])
        self.assertEqual(sb.detect([], [preset("a"), {"bundle_id": "x"}]), {"installed": True, "presets": 1})
        self.assertTrue(sb.detect([], [], settings_file_exists=True)["installed"])

    def test_data_dir(self):
        root = os.path.abspath(os.path.join(os.sep, "x", "OrcaSlicer"))
        self.assertEqual(sb.data_dir(os.path.join(root, "orca_plugins", "plugin_data", "kobracontrol")),
                         os.path.join(root, "spooler"))
        self.assertEqual(sb.data_dir("/somewhere/else"), "")


class KeepSlotsTests(unittest.TestCase):
    def test_marker_must_be_active_fresh_and_for_this_printer(self):
        ok = {"active": True, "ts": NOW, "printer": "Anycubic Kobra X"}
        labels = ["Anycubic Kobra X"]
        self.assertTrue(sb.keep_slots_active(ok, NOW + 5, labels))
        self.assertTrue(sb.keep_slots_active({**ok, "printer": "Anycubic Kobra X 0.4"}, NOW, labels))
        self.assertTrue(sb.keep_slots_active({**ok, "printer": ""}, NOW, labels))    # unknown printer: pause
        self.assertFalse(sb.keep_slots_active({**ok, "printer": "Other"}, NOW, labels))
        self.assertFalse(sb.keep_slots_active({**ok, "active": False}, NOW, labels))
        self.assertFalse(sb.keep_slots_active({**ok, "ts": NOW - sb.KEEP_SLOTS_FRESH - 1}, NOW, labels))
        self.assertFalse(sb.keep_slots_active({**ok, "ts": True}, NOW, labels))
        self.assertFalse(sb.keep_slots_active("x", NOW, labels))
        self.assertFalse(sb.keep_slots_active(None, NOW, labels))


class ProfilesTests(unittest.TestCase):
    PROFILES = {"version": 1, "filaments": {"70": {"anycubic kobra x": "_local/spooler/Gen Black"}}}

    def test_problem_and_lookup(self):
        self.assertEqual(sb.profiles_problem(None), "")
        self.assertEqual(sb.profiles_problem(self.PROFILES), "")
        self.assertIn("version", sb.profiles_problem({"version": 2, "filaments": {}}))
        self.assertIn("version", sb.profiles_problem({"version": True, "filaments": {}}))
        self.assertIn("object", sb.profiles_problem({"version": 1, "filaments": []}))
        self.assertEqual(sb.profile_lookup(self.PROFILES, 70, "Anycubic Kobra X"), "_local/spooler/Gen Black")
        self.assertEqual(sb.profile_lookup(self.PROFILES, 70, "Anycubic Kobra"), "_local/spooler/Gen Black")
        self.assertIsNone(sb.profile_lookup(self.PROFILES, 71, "Anycubic Kobra X"))
        self.assertIsNone(sb.profile_lookup(self.PROFILES, None, "x"))
        self.assertIsNone(sb.profile_lookup({"version": 2, "filaments": {}}, 70, "x"))

    def test_read_json(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        with open(os.path.join(d, "p.json"), "w") as f:
            json.dump({"a": 1}, f)
        with open(os.path.join(d, "l.json"), "w") as f:
            f.write("[1]")
        self.assertEqual(sb.read_json(d, "p.json"), {"a": 1})
        self.assertIsNone(sb.read_json(d, "l.json"))
        self.assertIsNone(sb.read_json(d, "missing.json"))
        self.assertIsNone(sb.read_json("", "p.json"))


class PresetTests(unittest.TestCase):
    def test_spooler_presets_filter_by_printer(self):
        metas = [preset("a"), preset("b", compatible=("Other",)), preset("c", compatible=()), preset("d", bundle="x")]
        names = [m["name"][len(sb.NAME_PREFIX):] for m in sb.spooler_presets(metas, ["Anycubic Kobra X"])]
        self.assertEqual(names, ["a", "c"])
        self.assertEqual(len(sb.spooler_presets(metas, [])), 3)
        self.assertEqual(sb.as_list('"A B";C'), ["A B", "C"])

    def test_preset_for_spool_prefers_published_profile_then_nearest_colour(self):
        presets = [preset("Generic PLA Red", colour="#FF0000"), preset("Generic PLA Blue", colour="#0000FF"),
                   preset("Other PLA Red", vendor="Other", colour="#FF0000")]
        spool = {"filament_id": 7, "vendor": "Generic", "material": "PLA", "colour": "#FE0000"}
        self.assertEqual(sb.preset_for_spool(presets, spool), sb.NAME_PREFIX + "Generic PLA Red")
        profiles = {"version": 1, "filaments": {"7": {"anycubic kobra x": "Generic PLA Blue"}}}
        self.assertEqual(sb.preset_for_spool(presets, spool, profiles, "Anycubic Kobra X"),
                         sb.NAME_PREFIX + "Generic PLA Blue")
        self.assertIsNone(sb.preset_for_spool(presets, {**spool, "colour": "#00FF00"}))
        self.assertIsNone(sb.preset_for_spool(presets, {**spool, "material": "PETG"}))


if __name__ == "__main__":
    unittest.main()
