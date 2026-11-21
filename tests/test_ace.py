"""Run: python3 -m unittest tests/test_ace.py -v"""

import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import ace  # noqa: E402


def slot(i, status=5, type_="PLA", color=(10, 20, 30), **kw):
    return {"index": i, "status": status, "type": type_, "color": list(color), **kw}


def box(id_, slots, loaded=-1, **kw):
    return {"id": id_, "loaded_slot": loaded, "slots": slots, **kw}


def four(**kw):
    return [slot(i, **kw) for i in range(4)]


HEAD = box(-1, [slot(i, color=(i, 0, 0)) for i in range(3)], loaded=1)
ACE0 = box(0, four(color=(0, 1, 0)), loaded=2)
ACE1 = box(1, four(color=(0, 0, 1)))


class DetectMode(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(ace.detect_filament_mode([]), "toolhead")
        self.assertEqual(ace.detect_filament_mode([HEAD]), "toolhead")
        self.assertEqual(ace.detect_filament_mode([ACE0]), "ace_direct")
        self.assertEqual(ace.detect_filament_mode([HEAD, ACE0]), "ace_hub")

    def test_missing_id_counts_as_head(self):
        self.assertEqual(ace.detect_filament_mode([{"id": None, "slots": []}]), "toolhead")


class AggregateSlots(unittest.TestCase):
    def test_no_boxes(self):
        self.assertEqual(ace.aggregate_slots([], "toolhead"), ([], -1))

    def test_head_only(self):
        slots, loaded = ace.aggregate_slots([HEAD], "toolhead")
        self.assertEqual([s["global_index"] for s in slots], [0, 1, 2])
        self.assertEqual(loaded, 1)
        self.assertTrue(all(s["box_id"] == -1 and s["box_pos"] == 0 for s in slots))
        self.assertEqual(slots[1]["color"], [1, 0, 0])
        self.assertEqual(slots[0]["activity"], "")

    def test_one_ace(self):
        slots, loaded = ace.aggregate_slots([ACE0], "ace_direct")
        self.assertEqual([s["global_index"] for s in slots], [0, 1, 2, 3])
        self.assertEqual(loaded, 2)

    def test_two_aces_sorted_and_loaded_last_wins(self):
        b1 = box(1, four(), loaded=3)
        slots, loaded = ace.aggregate_slots([b1, ACE0], "ace_direct")
        self.assertEqual([s["global_index"] for s in slots], list(range(8)))
        self.assertEqual([s["box_id"] for s in slots], [0] * 4 + [1] * 4)
        self.assertEqual([s["box_pos"] for s in slots], [0] * 4 + [1] * 4)
        self.assertEqual(loaded, 7)

    def test_direct_truncates_to_four_slots(self):
        b = box(0, [slot(i) for i in range(6)])
        slots, _ = ace.aggregate_slots([b], "ace_direct")
        self.assertEqual(len(slots), 4)

    def test_direct_loaded_out_of_range_ignored(self):
        _, loaded = ace.aggregate_slots([box(0, four(), loaded=4)], "ace_direct")
        self.assertEqual(loaded, -1)

    def test_hub(self):
        # The ACE units keep their ace_direct numbers; the head (the spool holder) is the unit after the last ACE
        slots, loaded = ace.aggregate_slots([HEAD, ACE0, ACE1], "ace_hub")
        self.assertEqual([s["global_index"] for s in slots], list(range(11)))
        self.assertEqual([s["box_id"] for s in slots], [0] * 4 + [1] * 4 + [-1] * 3)
        self.assertEqual([s["box_pos"] for s in slots], [0] * 4 + [1] * 4 + [2] * 3)
        self.assertEqual(loaded, 2)  # ace0 slot 2 overrides head loaded=1

    def test_hub_seven_sources(self):
        slots, _ = ace.aggregate_slots([HEAD, ACE0], "ace_hub")
        self.assertEqual([(s["box_id"], s["index"], s["global_index"]) for s in slots],
                         [(0, 0, 0), (0, 1, 1), (0, 2, 2), (0, 3, 3), (-1, 0, 4), (-1, 1, 5), (-1, 2, 6)])
        self.assertEqual([ace.slot_to_print_ams_index(s, "ace_hub") for s in slots], [4, 5, 6, 7, 0, 1, 2])
        self.assertEqual([ace.tray_id(s) for s in slots], list(range(7)))

    def test_hub_head_loaded_kept_when_ace_not_loaded(self):
        _, loaded = ace.aggregate_slots([HEAD, ACE1], "ace_hub")
        self.assertEqual(loaded, 2 * 4 + 1)  # ACE 1 is unit 1, the head unit 2

    def test_hub_head_truncated_to_three(self):
        h = box(-1, [slot(i) for i in range(4)])
        slots, _ = ace.aggregate_slots([h], "ace_hub")
        self.assertEqual(len(slots), 3)

    def test_colour_variants(self):
        b = box(-1, [slot(0, color=(1, 2, 3, 4)), slot(1, color=()), {"index": 2, "status": 5}])
        slots, _ = ace.aggregate_slots([b], "toolhead")
        self.assertEqual(slots[0]["color"], [1, 2, 3])
        self.assertEqual(slots[1]["color"], [255, 255, 255])
        self.assertEqual(slots[2]["color"], [255, 255, 255])
        self.assertEqual(slots[2]["type"], "")

    def test_optional_fields(self):
        b = box(-1, [slot(0, rfid=1, sku="X1"), slot(1)])
        slots, _ = ace.aggregate_slots([b], "toolhead")
        self.assertEqual((slots[0]["rfid"], slots[0]["sku"]), (1, "X1"))
        self.assertEqual((slots[1]["rfid"], slots[1]["sku"]), (None, None))

    def test_does_not_mutate(self):
        boxes = [copy.deepcopy(HEAD), copy.deepcopy(ACE0)]
        before = copy.deepcopy(boxes)
        ace.aggregate_slots(boxes, "ace_hub")
        self.assertEqual(boxes, before)


class Usable(unittest.TestCase):
    def s(self, status, box_id):
        return {"status": status, "box_id": box_id}

    def test_status_must_be_5(self):
        for st in (0, 1, 2, 4, 6):
            self.assertFalse(ace.slot_usable_for_print(self.s(st, 0), "ace_hub"))

    def test_by_mode(self):
        self.assertTrue(ace.slot_usable_for_print(self.s(5, -1), "ace_hub"))
        self.assertTrue(ace.slot_usable_for_print(self.s(5, 0), "ace_hub"))
        self.assertTrue(ace.slot_usable_for_print(self.s(5, 0), "ace_direct"))
        self.assertFalse(ace.slot_usable_for_print(self.s(5, -1), "ace_direct"))
        self.assertTrue(ace.slot_usable_for_print(self.s(5, -1), "toolhead"))
        self.assertFalse(ace.slot_usable_for_print(self.s(5, 0), "toolhead"))


def fs(status, idx, type_):
    return {"current_status": status, "slot_index": idx, "type": type_}


class Activity(unittest.TestCase):
    def test_loading_and_unloading(self):
        a = box(0, four(), feed_status=fs(5, 1, 1))
        b = box(1, four(), feed_status=fs(5, 2, 2))
        m = ace.slot_activity_map([a, b], -1, "ace_direct")
        self.assertEqual(m, {1: "loading", 6: "unloading"})

    def test_swap_marks_old_slot_unloading(self):
        a = box(0, four(), feed_status=fs(5, 3, 1))
        self.assertEqual(ace.slot_activity_map([a], 0, "ace_direct"), {0: "unloading", 3: "loading"})

    def test_pending_load_slot_ignores_transient(self):
        a = box(0, four(), feed_status=fs(5, 3, 1))
        m = ace.slot_activity_map([a], 0, "ace_direct", pending_load_slot=2)
        self.assertEqual(m, {0: "unloading"})
        m = ace.slot_activity_map([a], 3, "ace_direct", pending_load_slot=3)
        self.assertEqual(m, {3: "loading"})
        m = ace.slot_activity_map([a], -1, "ace_direct", pending_load_slot=2)
        self.assertEqual(m, {})

    def test_completion_events_and_idle_carry_no_activity(self):
        for st in (-1, 10, 11):
            a = box(0, four(), feed_status=fs(st, 1, 1))
            self.assertEqual(ace.slot_activity_map([a], -1, "ace_direct"), {})

    def test_empty_slot_or_bad_type_skipped(self):
        a = box(0, [slot(0, status=0)] + four()[1:], feed_status=fs(5, 0, 1))
        b = box(1, four(), feed_status=fs(5, 1, 7))
        c = box(2, four(), feed_status=fs(5, 9, 1))
        self.assertEqual(ace.slot_activity_map([a, b, c, box(3, [])], -1, "ace_direct"), {})

    def test_loaded_marker_added_once(self):
        a = box(0, four(), feed_status=fs(5, 1, 2))
        self.assertEqual(ace.slot_activity_map([a], 1, "ace_direct"), {1: "unloading"})
        self.assertEqual(ace.slot_activity_map([a], 2, "ace_direct"), {1: "unloading", 2: "loaded"})

    def test_hub_and_toolhead_globals(self):
        h = box(-1, [slot(i) for i in range(3)], feed_status=fs(5, 2, 1))
        a = box(0, four(), feed_status=fs(5, 1, 2))
        self.assertEqual(ace.slot_activity_map([h, a], -1, "ace_hub"), {6: "loading", 1: "unloading"})
        self.assertEqual(ace.slot_activity_map([h], -1, "toolhead"), {2: "loading"})

    def test_box_local_to_global(self):
        self.assertEqual(ace.box_local_to_global(-1, 2, "ace_hub", head_pos=1), 6)
        self.assertEqual(ace.box_local_to_global(-1, 2, "toolhead", head_pos=1), 2)
        self.assertEqual(ace.box_local_to_global(1, 2, "ace_direct"), 6)
        self.assertEqual(ace.box_local_to_global(1, 2, "ace_hub"), 6)


class PrintIndex(unittest.TestCase):
    def test_rules(self):
        s = {"box_id": 1, "index": 2, "global_index": 9}
        self.assertEqual(ace.slot_to_print_ams_index(s, "ace_hub"), 4 + 4 + 2)
        self.assertEqual(ace.slot_to_print_ams_index(s, "ace_direct"), 9)
        h = {"box_id": -1, "index": 1, "global_index": 5}
        self.assertEqual(ace.slot_to_print_ams_index(h, "ace_hub"), 1)
        self.assertEqual(ace.slot_to_print_ams_index(dict(h, global_index=1), "toolhead"), 1)


class AutoMapping(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(ace.build_auto_ams_box_mapping([], "toolhead"), [])

    def test_gaps_filled_with_highest(self):
        slots, _ = ace.aggregate_slots([ACE0], "ace_direct")
        loaded = [slots[0], slots[2]]
        m = ace.build_auto_ams_box_mapping(loaded, "ace_direct")
        self.assertEqual([e["paint_index"] for e in m], [0, 1, 2])
        self.assertEqual([e["ams_index"] for e in m], [0, 2, 2])
        self.assertEqual(m[0]["paint_color"], [255, 255, 255, 255])
        self.assertEqual(m[0]["ams_color"], [0, 1, 0, 255])
        self.assertEqual(m[0]["material_type"], "PLA")

    def test_blank_type_defaults_pla(self):
        s = {"global_index": 0, "box_id": -1, "index": 0, "type": "", "color": [1, 2, 3]}
        self.assertEqual(ace.build_auto_ams_box_mapping([s], "toolhead")[0]["material_type"], "PLA")


class AssignedMapping(unittest.TestCase):
    def setUp(self):
        self.slots, _ = ace.aggregate_slots(
            [HEAD, box(0, [slot(0, type_="PETG"), slot(1, status=0)] + [slot(2), slot(3)])], "ace_hub"
        )
        self.fil = [
            {"slot_index": 0, "color_hex": "#FF8000", "material": "ABS"},
            {"slot_index": 1, "color_hex": "bad", "material": ""},
        ]

    def test_assigned(self):
        a = [
            {"paint_index": 0, "slot_index": 0, "is_used": True},
            {"paint_index": 1, "slot_index": -1},
            {"paint_index": 2, "slot_index": 1},
            {"paint_index": 3, "slot_index": 99},
            {"paint_index": 4, "slot_index": 4, "is_used": False},
        ]
        r = ace.build_assigned_ams_box_mapping(a, self.fil, self.slots, "ace_hub")
        self.assertEqual((r["unused"], r["invalid"]), (2, 2))
        (e,) = r["mapping"]
        self.assertEqual(e["ams_index"], 4)
        self.assertEqual(e["paint_color"], [255, 128, 0, 255])
        self.assertEqual(e["material_type"], "PETG")

    def test_fallbacks(self):
        a = [{"paint_index": 1, "slot_index": 6}, {"paint_index": 7, "slot_index": 6}]
        s = [dict(x, type="") for x in self.slots]
        r = ace.build_assigned_ams_box_mapping(a, self.fil, s, "ace_hub")
        self.assertEqual(r["mapping"][0]["paint_color"], [255, 255, 255, 255])
        self.assertEqual(r["mapping"][0]["ams_index"], 2)  # holder position 3
        self.assertEqual(r["mapping"][0]["material_type"], "PLA")
        self.assertEqual(r["mapping"][1]["material_type"], "PLA")


class GlobalToBoxSlot(unittest.TestCase):
    def test_found(self):
        slots, _ = ace.aggregate_slots([HEAD, ACE0], "ace_hub")
        self.assertEqual(ace.global_to_box_slot(slots, 2, "ace_hub"), (0, 2))
        self.assertEqual(ace.global_to_box_slot(slots, 5, "ace_hub"), (-1, 1))

    def test_fallbacks(self):
        ace_slots, _ = ace.aggregate_slots([ACE0], "ace_direct")
        self.assertEqual(ace.global_to_box_slot(ace_slots, 9, "ace_direct"), (2, 1))
        self.assertEqual(ace.global_to_box_slot([], 2, "toolhead"), (-1, 2))
        self.assertEqual(ace.global_to_box_slot(ace_slots, 6, "ace_hub"), (-1, 2))   # the unit after ACE 0
        self.assertEqual(ace.global_to_box_slot(ace_slots, 2, "ace_hub"), (0, 2))


class AceUnits(unittest.TestCase):
    def test_empty(self):
        units, drying = ace.aggregate_ace_units([], [])
        self.assertEqual(units, [])
        self.assertEqual(drying, ace.EMPTY_DRYING)

    def test_units_and_primary(self):
        b0 = box(0, [], auto_feed=1, drying_status={"status": 0})
        b1 = box(
            1, [], auto_feed=0,
            drying_status={"status": 2, "target_temp": 50, "duration": 120, "remain_time": 7200 * 60, "humidity": 12, "temp": 40},
        )
        head = box(-1, [])
        units, drying = ace.aggregate_ace_units([b1, head, b0, box(4, [])], [])
        self.assertEqual([u["id"] for u in units], [0, 1])
        self.assertTrue(units[0]["auto_feed"])
        self.assertFalse(units[1]["auto_feed"])
        self.assertEqual(drying["status"], 2)
        self.assertEqual(drying["remain_time"], 7200)  # > 1440 treated as seconds
        self.assertEqual(drying["duration"], 120)
        self.assertEqual((drying["humidity"], drying["current_temp"]), (12.0, 40.0))

    def test_previous_kept_and_settings_fallback(self):
        prev = [{"id": 0, "auto_feed": True, "drying": dict(ace.EMPTY_DRYING, status=1)}]
        units, drying = ace.aggregate_ace_units([box(0, [])], prev)
        self.assertTrue(units[0]["auto_feed"])
        self.assertEqual(drying["status"], 1)
        units, _ = ace.aggregate_ace_units([box(0, [], drying_settings={"target_temp": 55}, humidity=9)], [])
        self.assertEqual(units[0]["drying"]["target_temp"], 55)
        self.assertEqual(units[0]["drying"]["humidity"], 9.0)

    def test_empty_drying_dict_is_truthy_source(self):
        units, _ = ace.aggregate_ace_units([box(0, [], drying_status={})], [])
        self.assertEqual(units[0]["drying"], ace.EMPTY_DRYING)

    def test_empty_drying_not_shared(self):
        units, _ = ace.aggregate_ace_units([box(0, [])], [])
        units[0]["drying"]["status"] = 9
        self.assertEqual(ace.EMPTY_DRYING["status"], 0)


class Trays(unittest.TestCase):
    def test_tray_id_matches_rule(self):
        slots, _ = ace.aggregate_slots([HEAD, ACE0, ACE1], "ace_hub")
        for s in slots:  # a slot's number is its tray id (Spooler's "S<n>" location), in every mode
            self.assertEqual(ace.tray_id(s), s["global_index"])
        head = [s for s in slots if s["box_id"] == -1]
        self.assertEqual([ace.tray_id(s) for s in head], [8, 9, 10])
        self.assertEqual([ace.slot_to_print_ams_index(s, "ace_hub") for s in head], [0, 1, 2])

    def test_direct_tray(self):
        slots, _ = ace.aggregate_slots([ACE0, ACE1], "ace_direct")
        self.assertEqual([ace.tray_id(s) for s in slots], list(range(8)))

    def test_tray_stable_with_id_gaps(self):
        slots, _ = ace.aggregate_slots([box(1, four())], "ace_direct")
        self.assertEqual([ace.tray_id(s) for s in slots], [4, 5, 6, 7])
        self.assertEqual(ace.slot_for_tray(5, slots)["global_index"], 5)
        slots, _ = ace.aggregate_slots([HEAD, box(2, four())], "ace_hub")
        self.assertEqual(ace.tray_id(slots[0]), 8)
        self.assertEqual(ace.slot_to_print_ams_index(slots[0], "ace_hub"), 12)
        self.assertEqual([ace.tray_id(s) for s in slots[4:]], [12, 13, 14])

    def test_slot_for_tray(self):
        slots, _ = ace.aggregate_slots([HEAD, ACE0], "ace_hub")
        self.assertEqual(ace.slot_for_tray(5, slots)["global_index"], 5)
        self.assertEqual(ace.slot_for_tray(5, slots)["box_id"], -1)
        self.assertIsNone(ace.slot_for_tray(7, slots))  # the holder has 3 positions
        self.assertIsNone(ace.slot_for_tray(-1, slots))
        self.assertIsNone(ace.slot_for_tray(99, slots))


class MappingFromTrays(unittest.TestCase):
    def setUp(self):
        self.boxes = [HEAD, box(0, [slot(0, type_="PETG", color=(9, 8, 7)), slot(1, status=0), slot(2), slot(3)])]
        self.slots, _ = ace.aggregate_slots(self.boxes, "ace_hub")

    def run_(self, trays, fils):
        return ace.mapping_from_trays(trays, fils, self.slots, "ace_hub")

    def test_ok(self):
        fils = [{"colour": "#FF0000", "type": "PLA"}, {"colour": "00FF0080", "type": "PETG"}, {"colour": "#000000", "type": "ABS"}]
        mapping, problems = self.run_([-1, 0, 5], fils)
        self.assertEqual(problems, [])
        self.assertEqual([m["paint_index"] for m in mapping], [1, 2])
        self.assertEqual(mapping[0]["ams_index"], 4)
        self.assertEqual(mapping[0]["paint_color"], [0, 255, 0, 128])
        self.assertEqual(mapping[0]["ams_color"], [9, 8, 7, 255])
        self.assertEqual(mapping[0]["material_type"], "PETG")
        self.assertEqual(mapping[1]["ams_index"], 1)
        self.assertEqual(mapping[1]["ams_color"], [1, 0, 0, 255])

    def test_problems_reported(self):
        fils = [{"colour": "#FF0000", "type": "PLA"}] * 4
        mapping, problems = self.run_([99, 1, 7, -2], fils)
        self.assertEqual(mapping, [])
        self.assertEqual(len(problems), 4)
        self.assertIn("99", problems[0])
        self.assertIn("1", problems[1])
        self.assertIn("7", problems[2])

    def test_slot_not_usable_in_mode(self):
        mapping, problems = ace.mapping_from_trays([0], [{"colour": "#FFFFFF", "type": "PLA"}], self.slots, "toolhead")
        self.assertEqual(mapping, [])
        self.assertEqual(len(problems), 1)

    def test_bad_colour_and_type_fallback(self):
        mapping, problems = self.run_([2], [{"colour": "zz", "type": ""}])
        self.assertEqual(mapping[0]["paint_color"], [255, 255, 255, 255])
        self.assertEqual(len(problems), 1)
        self.assertEqual(mapping[0]["material_type"], "PLA")

    def test_filament_type_used_when_slot_has_none(self):
        slots = [dict(s, type="") for s in self.slots]
        mapping, _ = ace.mapping_from_trays([0], [{"colour": "#102030", "type": "TPU"}], slots, "ace_hub")
        self.assertEqual(mapping[0]["material_type"], "TPU")

    def test_length_mismatch(self):
        mapping, problems = self.run_([0, 4], [{"colour": "#FFFFFF", "type": "PLA"}])
        self.assertEqual([m["paint_index"] for m in mapping], [0, 1])
        self.assertEqual(len(problems), 1)

    def test_no_mutation(self):
        slots = copy.deepcopy(self.slots)
        self.run_([0], [{"colour": "#FFFFFF", "type": "PLA"}])
        self.assertEqual(slots, self.slots)


# ---- ported from KX-Bridge tests -------------------------------------------

def kx_slot(index, type_="PLA", color=(1, 2, 3), status=5):
    return {"index": index, "sku": "", "type": type_, "color": list(color), "edit_status": 0, "status": status,
            "color_group": [list(color) + [255]], "icon_type": 0, "consumables_percent": 50}


def kx_ace(box_id, loaded=-1):
    return {"id": box_id, "status": 1, "auto_feed": 1, "loaded_slot": loaded,
            "feed_status": {"code": 200, "type": -1, "current_status": -1, "slot_index": -1},
            "temp": 30, "humidity": 0, "drying_status": {"status": 0, "target_temp": 0, "duration": 0, "remain_time": 0},
            "slots": [kx_slot(i) for i in range(4)]}


class MultiAce(unittest.TestCase):  # test_multi_ace_slots.py
    def test_modes_and_slot_counts(self):
        self.assertEqual(ace.detect_filament_mode([kx_ace(0), kx_ace(1)]), "ace_direct")
        self.assertEqual(len(ace.aggregate_slots([kx_ace(0)], "ace_direct")[0]), 4)
        slots, _ = ace.aggregate_slots([kx_ace(1), kx_ace(0)], "ace_direct")
        self.assertEqual([s["global_index"] for s in slots], list(range(8)))
        self.assertEqual([s["box_id"] for s in slots], [0] * 4 + [1] * 4)

    def test_loaded(self):
        self.assertEqual(ace.aggregate_slots([kx_ace(0), kx_ace(1, 2)], "ace_direct")[1], 6)
        self.assertEqual(ace.aggregate_slots([kx_ace(0, 3), kx_ace(1)], "ace_direct")[1], 3)

    def test_hub_numbering(self):
        boxes = [dict(kx_ace(-1)), kx_ace(0), kx_ace(1)]
        self.assertEqual(ace.detect_filament_mode(boxes, 1), "ace_hub")
        slots, _ = ace.aggregate_slots(boxes, "ace_hub")
        self.assertEqual([s["global_index"] for s in slots], list(range(11)))
        self.assertEqual([s["box_id"] for s in slots][-3:], [-1, -1, -1])

    def test_round_trip(self):
        slots, _ = ace.aggregate_slots([kx_ace(0), kx_ace(1)], "ace_direct")
        for g in range(8):
            b, local = ace.global_to_box_slot(slots, g, "ace_direct")
            self.assertEqual((b, local), (g // 4, g % 4))
            self.assertEqual(ace.box_local_to_global(b, local, "ace_direct"), g)


class EmptyTrayPlaceholder(unittest.TestCase):  # test_auto_ams_box_mapping_empty_slot.py
    def setUp(self):
        raw = [(5, "PLA", (101, 88, 177)), (5, "PLA SILK", (239, 96, 163)), (4, "PLA", (223, 221, 220)), (5, "PLA", (117, 120, 123))]
        self.slots, _ = ace.aggregate_slots(
            [box(-1, [slot(i, status=st, type_=t, color=c) for i, (st, t, c) in enumerate(raw)])], "toolhead")
        self.loaded_idx = {s["global_index"] for s in self.slots if s["status"] == 5}

    def assert_all_loaded(self, mapping):
        self.assertEqual([e["ams_index"] in self.loaded_idx for e in mapping], [True] * len(mapping))

    def test_only_used_slot_loaded(self):
        m = ace.build_auto_ams_box_mapping([self.slots[3]], "toolhead")
        self.assertEqual([e["paint_index"] for e in m], [0, 1, 2, 3])
        self.assert_all_loaded(m)

    def test_gap_in_loaded_set(self):
        m = ace.build_auto_ams_box_mapping([self.slots[i] for i in (0, 1, 3)], "toolhead")
        self.assertEqual([e["paint_index"] for e in m], [0, 1, 2, 3])
        self.assert_all_loaded(m)
        self.assertEqual([m[0]["ams_index"], m[1]["ams_index"], m[3]["ams_index"]], [0, 1, 3])

    def test_all_full_is_identity(self):
        slots = [dict(s, status=5) for s in self.slots]
        m = ace.build_auto_ams_box_mapping(slots, "toolhead")
        self.assertEqual([e["ams_index"] for e in m], [0, 1, 2, 3])


class MulticolorReport(unittest.TestCase):  # test_multicolor_box_failed_state.py
    def test_failed_list_data(self):
        r = ace.parse_multicolor_report({"state": "failed", "data": ["multi_color_box", [{"filaments": {"id": 2}, "id": 0}]]})
        self.assertEqual(r, {"failed": True, "boxes": [], "head_tools_model": None})

    def test_success_and_non_dict_data(self):
        r = ace.parse_multicolor_report({"state": "success", "data": {"head_tools_model": 1, "multi_color_box": [{"id": -1, "slots": []}]}})
        self.assertEqual((r["failed"], r["head_tools_model"], len(r["boxes"])), (False, 1, 1))
        for bad in ({"state": "success", "data": ["multi_color_box", []]}, None, {"data": {}}):
            self.assertEqual(ace.parse_multicolor_report(bad)["boxes"], [])
            self.assertFalse(ace.parse_multicolor_report(bad)["failed"])


GEEETECH = [
    {"id": "GTPLA01", "name": "Geeetech PLA Basic", "vendor": "Geeetech", "type": "PLA"},
    {"id": "GTPLA03", "name": "Geeetech PLA Matte", "vendor": "Geeetech", "type": "PLA"},
    {"id": "X1", "name": "Other PETG", "vendor": "Other", "type": "PETG"},
]


class Rfid(unittest.TestCase):  # test_ace_rfid_vendor_matching.py (pure parts)
    vendors = ["Geeetech", "Other"]

    def test_parse(self):
        self.assertEqual(ace.parse_combined_rfid_type("GEEETECH PLA Bas", self.vendors), ("Geeetech", "PLA"))
        self.assertEqual(ace.parse_combined_rfid_type("PLA", self.vendors), ("", ""))
        self.assertEqual(ace.parse_combined_rfid_type("TOTALLYUNKNOWNBRAND PLA Bas", self.vendors), ("", ""))
        self.assertEqual(ace.parse_combined_rfid_type("Geeetech ???", self.vendors), ("Geeetech", "???"))

    def test_match(self):
        self.assertEqual(ace.match_profile_by_vendor_family(GEEETECH[:1] + GEEETECH[2:], "Geeetech", "PLA")["name"], "Geeetech PLA Basic")
        self.assertEqual(ace.match_profile_by_vendor_family(GEEETECH, "Geeetech", "PETG"), {})
        self.assertEqual(ace.match_profile_by_vendor_family(GEEETECH, "Geeetech", "PLA")["name"], "Geeetech PLA Basic")

    def test_variant_disambiguation(self):
        self.assertEqual(ace.match_profile_by_vendor_family(GEEETECH, "Geeetech", "PLA", ["bas"])["name"], "Geeetech PLA Basic")
        self.assertEqual(ace.match_profile_by_vendor_family(GEEETECH, "Geeetech", "PLA", ["mat"])["name"], "Geeetech PLA Matte")

    def test_variant_tokens(self):
        self.assertEqual(ace.rfid_variant_tokens("GEEETECH PLA Bas"), ["bas"])
        self.assertEqual(ace.rfid_variant_tokens("GEEETECH PLA"), [])
        self.assertEqual(ace.rfid_variant_tokens("PLA"), [])


class Material(unittest.TestCase):
    def test_normalize_and_family(self):
        self.assertEqual(ace.normalize_material(" pla-plus "), "PLA+")
        self.assertEqual(ace.normalize_material("silk_pla"), "PLA SILK")
        self.assertEqual(ace.normalize_material("tpe"), "TPU")
        self.assertEqual(ace.normalize_material("Petg Plus"), "PETG+")
        self.assertEqual(ace.normalize_material("pa12"), "PA")
        self.assertEqual(ace.normalize_material("PLA Matte"), "PLA MATTE")
        self.assertEqual(ace.material_family(""), "")
        self.assertEqual(ace.material_family("PLA Silk"), "PLA")
        self.assertEqual(ace.material_family("petg+"), "PETG")
        self.assertEqual(ace.material_family("PET"), "PET")
        self.assertEqual(ace.material_family("NYLON"), "NYLON")


class DryingState(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(ace.humidity_from({"cur_humidity": "33"}), 33.0)
        self.assertEqual(ace.humidity_from({"humidity": "x"}, 7), 7)
        self.assertIsNone(ace.humidity_from({}))
        self.assertEqual(ace.current_temp_from({"temperature": 41}), 41.0)
        self.assertEqual(ace.minutes_from({"duration": 90}, "duration"), 90)
        self.assertEqual(ace.minutes_from({"duration": 7200}, "duration"), 120)
        self.assertEqual(ace.minutes_from({}, "duration", 5), 5)
        self.assertEqual(ace.minutes_from({"duration": "bad"}, "duration"), 0)
        self.assertEqual(ace.minutes_from({"duration": -5}, "duration"), 0)

    def test_per_unit_only(self):
        b0 = box(0, [], drying_status={"status": 0})
        b1 = box(1, [], drying_status={"status": 2, "target_temp": 50, "duration": 120, "remain_time": 3600, "humidity": 15}, temp=40)
        r = ace.aggregate_drying_state({}, [b0, b1, box(-1, [])], None)
        self.assertEqual([u["id"] for u in r["units"]], [0, 1])
        self.assertEqual((r["status"], r["target_temp"], r["remain_time"], r["humidity"]), (2, 50, 60, 15.0))

    def test_top_level_source_and_carry(self):
        cur = {"status": 1, "target_temp": 45, "duration": 10, "remain_time": 3, "humidity": 9.0, "current_temp": 30.0}
        r = ace.aggregate_drying_state({"drying_status": {"status": 3}}, [], cur)
        self.assertEqual((r["status"], r["target_temp"], r["humidity"], r["units"]), (3, 45, 9.0, []))
        self.assertEqual(ace.aggregate_drying_state({}, [], cur), cur)
        self.assertEqual(ace.aggregate_drying_state({}, [], None), {})

    def test_box_level_humidity_creates_unit(self):
        r = ace.aggregate_drying_state({}, [box(0, [], humidity=12)], None)
        self.assertEqual(r["units"][0]["humidity"], 12.0)

    def test_presets(self):
        d = ace.default_ace_dry_presets()
        d["pla"]["temp"] = 1
        self.assertEqual(ace.default_ace_dry_presets()["pla"]["temp"], 45)
        r = ace.sanitize_ace_dry_presets({"pla": {"temp": 500, "duration_sec": 1}, "petg": {"temp": "x"},
                                          "custom_1": {"name": "  Mine ", "temp": 20}, "bogus": {}})
        self.assertEqual((r["pla"]["temp"], r["pla"]["duration_sec"]), (80, 600))
        self.assertEqual(r["petg"]["temp"], 50)
        self.assertEqual((r["custom_1"]["name"], r["custom_1"]["temp"]), ("Mine", 30))
        self.assertNotIn("bogus", r)
        self.assertEqual(ace.sanitize_ace_dry_presets(None), ace.default_ace_dry_presets())


class SelectLoaded(unittest.TestCase):
    def setUp(self):
        self.slots, _ = ace.aggregate_slots([box(0, [slot(0), slot(1, status=0), slot(2), slot(3)])], "ace_direct")

    def test_auto_and_fixed(self):
        self.assertEqual([s["global_index"] for s in ace.select_loaded_slots_for_print(self.slots, "ace_direct")[0]], [0, 2, 3])
        chosen, warn = ace.select_loaded_slots_for_print(self.slots, "ace_direct", "2")
        self.assertEqual(([s["global_index"] for s in chosen], warn), ([2], None))

    def test_fallback_warns(self):
        for d in (1, "zz"):
            chosen, warn = ace.select_loaded_slots_for_print(self.slots, "ace_direct", d)
            self.assertEqual(len(chosen), 3)
            self.assertIn(str(d), warn)


class SetSlotPayload(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(ace.set_info_payload(0, 2, "petg", [1, 2, 3]),
                         {"multi_color_box": [{"id": 0, "slots": [{"index": 2, "type": "PETG", "color": [1, 2, 3]}]}]})

    def test_bad_color(self):
        for c in ([1, 2], [1, 2, 3, 4], [0, 0, 256], [0, 0, "1"], "abc", [True, 0, 0]):
            with self.assertRaises(ValueError):
                ace.set_info_payload(0, 0, "PLA", c)


# ---- real Kobra X report (firmware 2.0.2.8, one ACE, direct mode) -----------

def real_slot(i, color):
    return {"brand_name": "public", "color": list(color), "color_group": [list(color) + [255]],
            "consumables_percent": 100, "edit_status": 1, "icon_type": 0, "index": i,
            "material_name": "", "sku": "", "status": 5, "type": "PLA", "weight": 1000}


REAL = {"head_tools_model": 0, "multi_color_box": [{
    "auto_feed": 1, "drying_status": {"duration": 86400, "remain_time": 901, "status": 1, "target_temp": 45},
    "humidity": 32, "id": 0, "loaded_slot": -1, "model_id": 40002,
    "slots": [real_slot(0, (225, 6, 0)), real_slot(1, (124, 77, 58)), real_slot(2, (212, 185, 150)), real_slot(3, (101, 137, 70))],
    "status": 1, "temp": 45}]}


class RealReport(unittest.TestCase):
    def setUp(self):
        self.boxes = REAL["multi_color_box"]
        self.before = copy.deepcopy(REAL)

    def test_mode_slots(self):
        mode = ace.detect_filament_mode(self.boxes, REAL["head_tools_model"])
        self.assertEqual(mode, "ace_direct")
        slots, loaded = ace.aggregate_slots(self.boxes, mode)
        self.assertEqual(loaded, -1)
        self.assertTrue(all(ace.slot_usable_for_print(s, mode) for s in slots))
        self.assertEqual(len(slots), 4)
        s = slots[0]
        self.assertEqual((s["percent"], s["weight"], s["brand"], s["material_name"]), (100, 1000, "", ""))
        self.assertEqual(s["color"], [225, 6, 0])
        self.assertEqual(REAL, self.before)

    def test_slot_fields_absent_and_brand(self):
        b = box(0, [{"index": 0, "status": 5, "type": "PLA", "brand_name": "eSun", "material_name": "PLA+"}, slot(1)])
        a, c = ace.aggregate_slots([b], "ace_direct")[0]
        self.assertEqual((a["brand"], a["material_name"]), ("eSun", "PLA+"))
        self.assertEqual((c["percent"], c["weight"], c["brand"], c["material_name"]), (None, None, "", ""))
        self.assertEqual(ace.aggregate_slots([box(0, [{"index": 0, "brand_name": "Public"}])], "ace_direct")[0][0]["brand"], "")

    def test_unit_keys(self):
        units, drying = ace.aggregate_ace_units(self.boxes, [])
        u = units[0]
        self.assertEqual((u["id"], u["auto_feed"], u["humidity"], u["temp"], u["status"], u["model_id"]), (0, True, 32.0, 45.0, 1, 40002))
        self.assertEqual((u["drying"]["humidity"], u["drying"]["current_temp"]), (32.0, 45.0))
        self.assertEqual((drying["status"], drying["target_temp"], drying["remain_time"]), (1, 45, 901))
        self.assertEqual(REAL, self.before)

    def test_unit_keys_absent(self):
        u = ace.aggregate_ace_units([box(0, [])], [])[0][0]
        self.assertEqual((u["humidity"], u["temp"], u["status"], u["model_id"]), (None, None, None, None))

    def test_drying_state(self):
        r = ace.aggregate_drying_state({}, self.boxes, None)
        self.assertEqual((r["status"], r["target_temp"], r["remain_time"], r["humidity"], r["current_temp"]), (1, 45, 901, 32.0, 45.0))
        # remain_time is minutes (measured 898 -> 896 over 126 s): never rescaled
        self.assertEqual(r["remain_time"], 901)
        # duration 86400 is read as seconds -> 1440 min; it is not the elapsed total, UI must show remain_time
        self.assertEqual(r["duration"], 1440)

    def test_box_level_temp_humidity_helpers(self):
        self.assertEqual(ace.current_temp_from(self.boxes[0]), 45.0)
        self.assertEqual(ace.humidity_from(self.boxes[0]), 32.0)


class SetDryPayload(unittest.TestCase):
    def test_start(self):
        self.assertEqual(ace.set_dry_payload([0], 45, 240),
                         {"multi_color_box": [{"id": 0, "drying_status": {"status": 1, "target_temp": 45, "duration": 240, "remain_time": 240}}]})

    def test_stop_and_multi(self):
        self.assertEqual(ace.set_dry_payload([0, 1]), {"multi_color_box": [
            {"id": 0, "drying_status": {"status": 0}}, {"id": 1, "drying_status": {"status": 0}}]})

    def test_validation(self):
        for t, d in ((29, 240), (81, 240), (45, 9), (45, 1441), ("45", 240), (45, True)):
            with self.assertRaises(ValueError):
                ace.set_dry_payload([0], t, d)
        for ids in ([], [4], [-1], ["0"]):
            with self.assertRaises(ValueError):
                ace.set_dry_payload(ids, 45, 240)


if __name__ == "__main__":
    unittest.main()
