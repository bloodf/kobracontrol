"""Kobra Control's print dialog rules (printsetup.py): matching, warnings, options, the answer and the plate."""

import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import kobra  # noqa: E402
import printsetup as ps  # noqa: E402


def slot(g, typ="PLA", rgb=(255, 0, 0), status=5, box=0):
    return {"global_index": g, "box_id": box, "box_pos": box + 1 if box >= 0 else 0, "index": g % 4, "status": status,
            "type": typ, "color": list(rgb), "usable": status == 5}


def fil(i, typ="PLA", colour="#FF0000"):
    return {"index": i, "type": typ, "colour": colour, "grams": 1.0}


# ACE in direct mode: tray id = (box + 1) * 4 + index
SLOTS = [slot(0, "PLA", (255, 0, 0)), slot(1, "PETG", (0, 0, 255)), slot(2, "", (0, 0, 0), status=0),
         slot(3, "PLA", (0, 255, 0))]
MODE = "ace_direct"
T = {s["global_index"]: 4 + s["index"] for s in SLOTS}   # global index -> tray id


class Matching(unittest.TestCase):
    def test_exact_material_and_colour(self):
        fils = [fil(0, "PLA", "#00FF00"), fil(1, "PETG", "#0000FF"), fil(2, "PLA", "#FF0000")]
        self.assertEqual(ps.auto_match(fils, SLOTS, MODE), {0: T[3], 1: T[1], 2: T[0]})

    def test_early_filament_does_not_take_a_later_exact_match(self):
        fils = [fil(0, "PLA", "#EE1111"), fil(1, "PLA", "#FF0000")]
        out = ps.auto_match(fils, SLOTS, MODE)
        self.assertEqual(out[1], T[0])
        self.assertEqual(out[0], T[3])

    def test_more_filaments_than_slots_share_their_best(self):
        fils = [fil(i, "PLA", "#FF0000") for i in range(5)]
        out = ps.auto_match(fils, SLOTS, MODE)
        self.assertEqual(len(out), 5)
        self.assertTrue(all(t in (T[0], T[1], T[3]) for t in out.values()))
        self.assertEqual(ps.check(fils, SLOTS, MODE, out)[0], [])

    def test_no_usable_slot(self):
        self.assertEqual(ps.auto_match([fil(0)], [slot(0, status=0)], MODE), {0: -1})

    def test_orca_choice_kept_unless_unusable(self):
        fils = [fil(0, "PLA", "#FF0000"), fil(1, "PETG", "#0000FF")]
        self.assertEqual(ps.initial_trays([T[3], T[2]], fils, SLOTS, MODE), {0: T[3], 1: T[1]})   # empty -> auto
        self.assertEqual(ps.initial_trays([], fils, SLOTS, MODE), {0: T[0], 1: T[1]})


class Checks(unittest.TestCase):
    def test_kinds(self):
        fils = [fil(0, "PLA", "#FF0000"), fil(1, "PETG", "#FF0000"), fil(2, "PLA", "#FFFFFF"), fil(3), fil(4),
                fil(5, "PLA Silk", "#FF0000")]
        trays = {0: T[0], 1: T[0], 2: T[3], 3: T[2], 4: -1, 5: T[0]}
        blocking, warnings, hints = ps.check(fils, SLOTS, MODE, trays)
        self.assertEqual([(b["kind"], b["f"]) for b in blocking], [("material", 1), ("empty", 3), ("none", 4)])
        self.assertEqual([w["id"] for w in warnings], ["variant:5:%d" % T[0]])
        self.assertEqual([h["id"] for h in hints], ["colour:2:%d" % T[3]])

    def test_aliases_are_the_same_material(self):
        self.assertTrue(ps.same_material("PLA+", "pla plus"))
        self.assertTrue(ps.same_material("", "PETG"))
        self.assertFalse(ps.same_material("PLA", "PLA SILK"))
        self.assertTrue(ps.same_family("PLA", "PLA SILK"))

    def test_missing_tray(self):
        self.assertEqual(ps.check([fil(0)], SLOTS, MODE, {0: 99})[0][0]["kind"], "empty")


class Options(unittest.TestCase):
    DEFAULTS = {"auto_leveling": True, "flow_calibration": False, "timelapse": False}

    def opts(self, defaults=None, features=None, orca=None, remembered=None):
        return {o["key"]: (o["on"], o["lock"]) for o in ps.offered_options(
            defaults or self.DEFAULTS, features or {}, orca or {k: True for k in ps.OPTIONS}, remembered or {})}

    def test_untested_options_need_the_setting(self):
        out = self.opts()
        self.assertEqual(out["flow_calibration"], (False, "setting"))
        self.assertEqual(out["timelapse"], (False, "setting"))
        self.assertEqual(out["auto_leveling"], (True, ""))
        on = self.opts({**self.DEFAULTS, "flow_calibration": True, "timelapse": True})
        self.assertEqual((on["flow_calibration"], on["timelapse"]), ((True, ""), (True, "")))

    def test_auto_leveling_setting_off_locks_it(self):
        self.assertEqual(self.opts({**self.DEFAULTS, "auto_leveling": False})["auto_leveling"], (False, "setting"))

    def test_unsupported_feature_locks_it(self):
        self.assertEqual(self.opts(features={"vibration_compensation_support": False})["vibration_compensation"],
                         (False, "unsupported"))

    def test_remembered_wins_over_orca(self):
        self.assertEqual(self.opts(remembered={"auto_leveling": False})["auto_leveling"], (False, ""))
        self.assertEqual(self.opts(orca={"auto_leveling": False})["auto_leveling"], (False, ""))

    def test_memory(self):
        mem = {}
        for i in range(ps.MEMORY_MAX + 3):
            mem = ps.remember(mem, "10.0.0.%d" % i, {"auto_leveling": True, "junk": 1})
        self.assertEqual(len(mem), ps.MEMORY_MAX)
        self.assertEqual(mem["10.0.0.%d" % (ps.MEMORY_MAX + 2)], {"auto_leveling": True})
        self.assertEqual(ps.clean_memory({"a": {"timelapse": "yes", "auto_leveling": False}, "": {}, "b": 3}),
                         {"a": {"auto_leveling": False}})
        self.assertIsNone(ps.clean_memory([]))


class Answer(unittest.TestCase):
    fils = [fil(0, "PLA", "#FF0000"), fil(1, "PLA Silk", "#0000FF")]
    start = {0: T[0], 1: T[3]}
    options = [{"key": "auto_leveling", "on": True, "lock": ""}, {"key": "timelapse", "on": False, "lock": "setting"}]

    def read(self, answer, auto_feed=None):
        return ps.read_answer(answer, self.fils, SLOTS, MODE, self.start, self.options, auto_feed)

    def test_cancel(self):
        for answer in (None, {"cancelled": True}, "x"):
            with self.assertRaises(ps.Cancelled):
                self.read(answer)

    def test_chosen_slots_and_options_are_sent(self):
        out = self.read({"trays": {"0": T[3], "9": T[0], "1": "x"}, "options": {"auto_leveling": False, "timelapse": True},
                         "remember": True, "name": "My cube", "acknowledged": ["variant:1:%d" % T[3]]}, auto_feed=True)
        self.assertEqual(out["trays"], {0: T[3], 1: T[3]})
        self.assertEqual(out["name"], "My cube")
        self.assertEqual(out["task"], {"auto_leveling": False, "timelapse": False})   # a locked option stays off
        self.assertEqual((out["auto_feed"], out["remember"]), (True, True))

    def test_nothing_answered_keeps_the_offer(self):
        out = self.read({"acknowledged": ["variant:1:%d" % T[3]]})
        self.assertEqual((out["trays"], out["task"], out["remember"]), (self.start, {"auto_leveling": True, "timelapse": False}, None))

    def test_variant_warning_needs_exact_ack(self):
        answer = {"trays": {"1": T[0]}}
        with self.assertRaises(kobra.KobraError):
            self.read(answer)
        with self.assertRaises(kobra.KobraError):
            self.read({**answer, "acknowledged": ["variant:1:%d" % T[3]]})
        self.assertEqual(self.read({**answer, "acknowledged": ["variant:1:%d" % T[0]]})["trays"][1], T[0])

    def test_other_material_refused_even_acknowledged(self):
        with self.assertRaises(kobra.KobraError) as e:
            self.read({"trays": {"1": T[1]}, "acknowledged": ["material:1:%d" % T[1]]})
        self.assertIn("another material", str(e.exception))

    def test_task_name_becomes_a_safe_file_name(self):
        import jobs
        name = lambda text: jobs.remote_name(ps.task_name(text, "fallback"))
        self.assertEqual(name("../x"), "_x.gcode")
        self.assertNotIn("/", name("a/b\\c"))
        self.assertNotIn("\\", name("a/b\\c"))
        self.assertEqual(name("..."), "kobracontrol.gcode")
        self.assertEqual(name("a.gcode.3mf"), "a.gcode")
        self.assertEqual(name(""), "fallback.gcode")

    def test_task_name(self):
        self.assertEqual(ps.task_name("  My\x00 cube \n v2 ", "x"), "My cube v2")
        self.assertEqual(ps.task_name("", "fallback"), "fallback")
        self.assertEqual(len(ps.task_name("a" * 300, "x")), 120)

    def test_empty_slot_refused(self):
        with self.assertRaises(kobra.KobraError):
            self.read({"trays": {"0": T[2]}})

    def test_tray_list(self):
        ids, described = ps.tray_list({1: T[1], 3: T[0]}, [fil(1, "PETG", "#0000FF"), fil(3)], 2)
        self.assertEqual(ids, [-1, T[1], -1, T[0]])
        self.assertEqual(described[1], {"colour": "#0000FF", "type": "PETG"})


class Plate(unittest.TestCase):
    def test_summary_and_filaments(self):
        path = os.path.join(tempfile.mkdtemp(), "job.3mf")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Metadata/plate_2.png", b"\x89PNG")
            z.writestr("Metadata/slice_info.config",
                       '<config><plate><metadata key="index" value="2"/><metadata key="prediction" value="3725"/>'
                       '<metadata key="weight" value="12.5"/><filament id="1" type="PLA" color="#112233" used_g="2.5" used_m="0.8"/>'
                       '<filament id="3" type="PETG" color="#AABBCC" used_g="10" used_m="3.2"/></plate></config>')
        plate = ps.plate_summary(path, 2)
        self.assertEqual((plate["seconds"], plate["grams"], plate["thumbnail"]), (3725, 12.5, "iVBORw=="))
        self.assertAlmostEqual(plate["metres"], 4.0)
        self.assertEqual(sorted(plate["filaments"]), [0, 2])
        fils = ps.job_filaments([-1, -1, -1], [], plate)   # OrcaSlicer chose nothing: the plate's list
        self.assertEqual([(f["index"], f["type"], f["colour"]) for f in fils], [(0, "PLA", "#112233"), (2, "PETG", "#AABBCC")])
        told = ps.job_filaments([5, -1], [{"colour": "#FF0000FF", "type": "PLA+"}], plate)
        self.assertEqual(told, [{"index": 0, "colour": "#FF0000", "type": "PLA+", "family": "PLA", "material": "PLA+", "grams": 2.5}])

    def test_unreadable_or_plain_gcode(self):
        path = os.path.join(tempfile.mkdtemp(), "a.gcode")
        with open(path, "w") as f:
            f.write("G1\n")
        self.assertEqual(ps.plate_summary(path)["filaments"], {})
        self.assertEqual(ps.plate_summary("/nope/x.3mf")["seconds"], 0)

    def test_spool_links(self):
        spools = [{"id": 4, "vendor": "Elegoo", "name": "Red", "remaining": 250, "initial": 1000}, {"id": 5, "vendor": "", "name": "", "remaining": 300}]
        self.assertEqual(ps.spool_links(spools, {0: 4, 1: 5, 2: 9}),
                         {0: {"name": "Elegoo Red", "fraction": 0.25}, 1: {"name": "#5", "fraction": None}})

    def test_page_slots_fraction(self):
        """The level drawn on each slot's spool: Spoolman's, else the ACE percentage, else unknown; never for an empty slot."""
        def slot(g, **o):
            return {"global_index": g, "box_id": 0, "box_pos": 1, "index": g, "type": "PLA", "color": [255, 0, 0], "usable": True, **o}
        data = {"slots": [slot(0, percent=80), slot(1, percent=40), slot(2), slot(3, percent=55, usable=False), slot(4, percent=130)]}
        links = {0: {"name": "Elegoo Red", "fraction": 0.25}, 1: {"name": "#5", "fraction": None}}
        got = [(s["spool"], s["fraction"]) for s in ps.page_slots(data, links)]
        self.assertEqual(got, [("Elegoo Red", 0.25), ("#5", 0.4), ("", None), ("", None), ("", 1.0)])


class Numbers(unittest.TestCase):
    def test_infinite_or_bad_numbers_read_as_zero(self):
        self.assertEqual(ps._num("inf", int), 0)
        self.assertEqual(ps._num("nan", int), 0)
        self.assertEqual(ps._num("x"), 0.0)


if __name__ == "__main__":
    unittest.main()
