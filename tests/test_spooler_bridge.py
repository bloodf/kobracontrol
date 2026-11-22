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


class TrayIdTests(unittest.TestCase):
    """tray_filament_id: the SPL id of a linked spool's standalone Spooler preset, from profiles.json "ids"."""
    LABEL = "Anycubic Kobra X"
    SPOOL = {"id": 12, "filament_id": 7, "vendor": "SUNLU", "material": "PLA", "colour": "#101010"}
    MATTE = "SUNLU PLA Matte Black @Anycubic Kobra X"

    def presets(self, *names):
        return [preset(n, vendor="SUNLU", colour="#101010") for n in names]

    def test_linked_spool_reports_its_spooler_preset_id(self):
        profiles = {"version": 1, "filaments": {"7": {self.LABEL: "_local/spooler/" + self.MATTE}},
                    "ids": {"_local/spooler/" + self.MATTE: "SPLAAAA000001"}}
        self.assertEqual(sb.tray_filament_id(self.SPOOL, self.presets(self.MATTE), profiles, self.LABEL), "SPLAAAA000001")
        by_colour = {"version": 1, "filaments": {}, "ids": profiles["ids"]}   # not listed: same vendor, material, colour
        self.assertEqual(sb.tray_filament_id(self.SPOOL, self.presets(self.MATTE), by_colour, self.LABEL), "SPLAAAA000001")

    def test_per_spool_preset_wins_over_the_filament_one(self):
        three, twelve = "SUNLU PLA #3 @Anycubic Kobra X", "SUNLU PLA #12 @Anycubic Kobra X"
        profiles = {"version": 1, "filaments": {"7": {self.LABEL: "_local/spooler/" + three}},
                    "spools": {"12": {self.LABEL: "_local/spooler/" + twelve}, "3": {self.LABEL: "_local/spooler/" + three}},
                    "ids": {"_local/spooler/" + three: "SPL0000000003", "_local/spooler/" + twelve: "SPL0000000012"}}
        self.assertEqual(sb.profile_lookup(profiles, 7, self.LABEL, 12), "_local/spooler/" + twelve)
        self.assertEqual(sb.profile_lookup(profiles, 7, self.LABEL, 99), "_local/spooler/" + three)
        presets = self.presets(three, twelve)
        self.assertEqual(sb.tray_filament_id(self.SPOOL, presets, profiles, self.LABEL), "SPL0000000012")
        self.assertEqual(sb.tray_filament_id({**self.SPOOL, "id": 3}, presets, profiles, self.LABEL), "SPL0000000003")

    def test_no_id_leaves_it_to_the_generic_preset(self):
        listed = {"version": 1, "filaments": {"7": {self.LABEL: "_local/spooler/" + self.MATTE}}}
        presets = self.presets(self.MATTE)
        self.assertEqual(sb.tray_filament_id(self.SPOOL, presets, listed, self.LABEL), "")   # an inheriting preset
        self.assertEqual(sb.tray_filament_id(self.SPOOL, presets, None, self.LABEL), "")     # no profiles.json
        self.assertEqual(sb.tray_filament_id(None, presets, listed), "")                     # nothing linked
        ids = {**listed, "ids": {"_local/spooler/" + self.MATTE: "SPLAAAA000001"}}
        self.assertEqual(sb.tray_filament_id({**self.SPOOL, "id": 1, "filament_id": 1, "material": "ASA"}, presets, ids), "")


if __name__ == "__main__":
    unittest.main()


class LinkedPresetTests(unittest.TestCase):
    """A spool's orca_filament_preset names one of the user's own presets (spoolman.linked_preset)."""

    def user(self, name, compatible=True, file="", inherits=""):
        return {"name": name, "compatible": compatible, "file": file, "inherits": inherits}

    def test_exact_name_then_the_only_case_insensitive_match_and_only_when_compatible(self):
        mine, other = self.user("My PLA"), self.user("my pla")
        self.assertEqual(sb.find_user_preset("My PLA", [other, mine]), (mine, ""))
        self.assertEqual(sb.find_user_preset("MY PLA", [other, mine]), (None, "ambiguous"))   # two loose matches
        self.assertEqual(sb.find_user_preset("MY PLA", [mine]), (mine, ""))
        self.assertEqual(sb.find_user_preset("My PLA", [self.user("My PLA", compatible=False)]), (None, "missing"))
        self.assertEqual(sb.find_user_preset("Missing", [mine]), (None, "missing"))

    def test_standalone_id_from_the_preset_file_never_for_an_inheriting_preset(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = os.path.join(folder, "My PLA.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "My PLA", "inherits": "", "filament_id": " P1234567 "}, f)
        self.assertEqual(sb.standalone_id(self.user("My PLA", file=path)), "P1234567")
        self.assertEqual(sb.standalone_id(self.user("My PLA", file=path, inherits="Generic PLA @System")), "")
        logged = []
        self.assertEqual(sb.standalone_id(self.user("My PLA", file=os.path.join(folder, "gone.json")), logged.append), "")
        self.assertEqual(len(logged), 1)
        self.assertEqual(sb.standalone_id(self.user("My PLA")), "")
        self.assertEqual(sb.standalone_id(None), "")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "My PLA", "filament_id": ""}, f)
        self.assertEqual(sb.standalone_id(self.user("My PLA", file=path)), "")


class SlotMatchTests(unittest.TestCase):
    """A slot card's preset: what the Device tab reports, why, and a pick remembered in matches.json."""
    LABEL = "Anycubic Kobra X"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "matches.json")
        name = sb.NAME_PREFIX + "Acme PLA Red @Anycubic Kobra X"
        self.mine = [{"name": name, "bundle_id": sb.BUNDLE_ID, "vendor": "Acme", "colour": "#FF0000"}]
        self.profiles = {"version": 1, "filaments": {"9": {self.LABEL: name}}, "ids": {name: "SPL0123456789"}}
        user = os.path.join(self.tmp, "Polymaker PLA.json")
        with open(user, "w", encoding="utf-8") as f:
            json.dump({"name": "Polymaker PLA", "inherits": "", "filament_id": "P1234567"}, f)
        self.users = [{"name": "Polymaker PLA", "compatible": True, "file": user, "inherits": ""},
                      {"name": "Inherits PLA", "compatible": True, "file": user, "inherits": "Generic PLA @System"}]
        self.slot = {"global_index": 0, "type": "PLA", "color": [255, 0, 0], "sku": "", "rfid": None, "brand": ""}

    def ctx(self):
        return sb.match_context(self.mine, self.LABEL, self.users, self.profiles, sb.load_stores([self.path]), {})

    def test_without_a_pick_it_is_what_the_agent_reports(self):
        spool = {"id": 5, "filament_id": 9, "vendor": "Acme", "material": "PLA", "colour": "#FE0101"}
        m = sb.slot_match(self.ctx(), self.slot, spool)
        self.assertEqual((m["name"], m["id"], m["source"]), (self.mine[0]["name"], "SPL0123456789", "spooler"))
        m = sb.slot_match(self.ctx(), self.slot, None)
        self.assertEqual((m["name"], m["id"], m["source"]), ("Generic PLA", "OFDSrzZ8", "generic"))
        names = [c["name"] for c in m["candidates"]]
        self.assertIn("Polymaker PLA", names)
        self.assertNotIn("Inherits PLA", names)   # no id of its own: sync from AMS would load its parent
        self.assertEqual(sb.slot_match(self.ctx(), {**self.slot, "type": "PETG"}, None)["candidates"][0]["name"], "Generic PETG")

    def test_pick_remembered_then_forgotten(self):
        sb.remember_slot(self.ctx(), self.slot, None, "Polymaker PLA", [self.path], self.path)
        m = sb.slot_match(self.ctx(), self.slot, None)
        self.assertEqual((m["name"], m["id"], m["source"], m["remembered_key"]), ("Polymaker PLA", "P1234567", "remembered", "mat:|pla|"))
        self.assertTrue(m["confident"])
        # the same pick for a slot with another colour of PLA; not for PETG
        self.assertEqual(sb.slot_match(self.ctx(), {**self.slot, "color": [0, 0, 255]}, None)["source"], "remembered")
        self.assertEqual(sb.slot_match(self.ctx(), {**self.slot, "type": "PETG"}, None)["source"], "generic")
        with self.assertRaises(ValueError):
            sb.remember_slot(self.ctx(), self.slot, None, "Generic PETG", [self.path], self.path)
        with self.assertRaises(ValueError):
            sb.remember_slot(self.ctx(), self.slot, None, "Inherits PLA", [self.path], self.path)
        sb.remember_slot(self.ctx(), self.slot, None, None, [self.path], self.path)
        self.assertEqual(sb.slot_match(self.ctx(), self.slot, None)["source"], "generic")

    def test_spoolers_store_first_and_written_while_installed(self):
        storage = os.path.join(self.tmp, "orca_plugins", "plugin_data", "kobracontrol")
        shared = os.path.join(self.tmp, sb.DATA_SUBDIR, "matches.json")
        own = os.path.join(storage, "matches.json")
        self.assertEqual(sb.match_paths(storage), ([shared, own], own))
        os.makedirs(os.path.dirname(shared))
        with open(os.path.join(os.path.dirname(shared), sb.SETTINGS_FILE), "w", encoding="utf-8") as f:
            f.write("{}")
        self.assertEqual(sb.match_paths(storage), ([shared, own], shared))
