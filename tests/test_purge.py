"""The purge-and-bed-wait add-on (purge.py) on G-code fixtures (tests/gcode), and in a print job: a copy is sent,
the sliced file is never changed. Run: python3 -m unittest tests/test_purge.py -v"""

import glob
import hashlib
import io
import os
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import kobra  # noqa: E402
import purge  # noqa: E402
import settings  # noqa: E402
from test_service import Base, wait  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "gcode")
OPTS = {"length": 15.0, "speed": 5.0, "corner": "front_left"}


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def run(data, opts=OPTS):
    out = io.BytesIO()
    info = purge.scan(io.BytesIO(data))
    done = purge.transform(io.BytesIO(data), out.write, opts, info)
    return out.getvalue().decode().splitlines(), done


def block_after(lines, marker):
    """The add-on block that follows the first line equal to `marker`."""
    i = lines.index(marker) + 1
    end = lines.index(purge.END, i)
    return lines[i:end + 1]


class Fixtures(unittest.TestCase):
    def test_single_colour_gets_bed_wait_and_no_purge(self):
        lines, done = run(fixture("single.gcode"))
        self.assertEqual(done, {"purges": 0, "bed_wait": True})   # its only T0 is in the start G-code
        first = lines.index(";LAYER_CHANGE")
        self.assertEqual(lines[first - 3:first], [purge.START, "M190 S60 ; wait for the first-layer bed temperature", purge.END])
        self.assertEqual(lines.count(purge.START), 1)

    def test_original_lines_kept_in_order(self):
        data = fixture("multi.gcode")
        lines, _ = run(data)
        inserted, inside = [], False
        for line in lines:
            if line == purge.START:
                inside = True
            elif line == purge.END:
                inside = False
            elif not inside:
                inserted.append(line)
        self.assertEqual(inserted, data.decode().splitlines())

    def test_purge_is_a_moving_line_in_its_own_lane(self):
        lines, done = run(fixture("multi.gcode"))
        self.assertEqual(done, {"purges": 2, "bed_wait": True})   # T1 and T2; T0 comes before the first layer
        up = purge._num(purge.lift(OPTS))
        self.assertGreater(purge.lift(OPTS), purge.LIFT)          # raised for the purged line's own height
        t1 = block_after(lines, "T1")
        self.assertEqual(t1, [purge.START, "M83", "G91", "G1 Z%s F1200" % up, "G90", "G1 X5 Y5 F12000", "G91",
                              "G1 Z-%s F1200" % up, "G90", "M83", "G1 X35 Y5 E15 F600", "G91", "G1 Z%s F1200" % up, "G90",
                              "G1 X110 Y100 F12000", "G91", "G1 Z-%s F1200" % up, "G90", "M83", purge.END])
        t2 = block_after(lines, "T2 ; next filament")
        self.assertIn("G1 X35 Y8 E15 F600", t2)    # the next lane, never on top of the first
        self.assertIn("G1 X100 Y110 F12000", t2)   # back to the last X/Y before T2
        self.assertEqual(lines.count("G1 Z-%s F1200" % up), lines.count("G1 Z%s F1200" % up))

    def test_lanes_never_repeat_and_stay_on_the_bed(self):
        bed = (0.0, 0.0, 260.0, 260.0)
        for corner in purge.CORNERS:
            opts = dict(OPTS, corner=corner)
            seen = set()
            for i in range(purge.lanes(bed)):
                (x0, y), (x1, _) = purge.lane(opts, bed, i)
                self.assertNotIn((x0, y), seen)
                seen.add((x0, y))
                for x in (x0, x1):
                    self.assertTrue(purge.MARGIN <= x <= 260 - purge.MARGIN, (corner, i, x))
                self.assertTrue(purge.MARGIN <= y <= 260 - purge.MARGIN, (corner, i, y))

    def test_more_tool_changes_than_lanes_refused(self):
        body = b"".join(b"T%d\nG1 X100 Y100 E1\n" % (i % 4) for i in range(purge.lanes((0, 0, 260, 260)) + 1))
        data = fixture("multi.gcode").replace(b";LAYER_CHANGE\n;Z:0.2\n", b";LAYER_CHANGE\n;Z:0.2\n" + body, 1)
        with self.assertRaisesRegex(purge.PurgeError, "room for"):
            run(data)

    def test_only_between_the_first_layer_and_the_end_gcode(self):
        lines, done = run(fixture("edges.gcode"))
        self.assertEqual(done, {"purges": 1, "bed_wait": False})   # only T2: not T1 (start), T255, T0 (end) or T3
        self.assertEqual(lines.count(purge.START), 1)
        self.assertEqual(lines[lines.index("T2") + 1], purge.START)

    def test_absolute_extrusion_is_restored_exactly(self):
        lines, _ = run(fixture("edges.gcode"))
        t2 = block_after(lines, "T2")
        self.assertEqual(t2[1], "M83")
        self.assertEqual(t2[-3:], ["M82", "G92 E2.5", purge.END])   # back to M82 at the E the file had reached

    def test_arcs_and_compact_moves_update_the_return_point(self):
        data = fixture("multi.gcode").replace(b"G1 X100 Y110 E0.6\n", b"G1X100Y110E0.6\nG2 X90 Y120 I-5 J5 E1\n")
        lines, _ = run(data)
        self.assertIn("G1 X90 Y120 F12000", block_after(lines, "T2 ; next filament"))

    def test_m83_again_after_g90_before_extruding(self):
        lines, _ = run(fixture("edges.gcode"))
        t2 = block_after(lines, "T2")
        i = next(i for i, l in enumerate(t2) if " E" in l and l.startswith("G1 X"))
        self.assertEqual(t2[i - 2:i], ["G90", "M83"])

    def test_existing_m190_is_not_doubled(self):
        lines, done = run(fixture("has_m190.gcode"))
        self.assertEqual(done, {"purges": 0, "bed_wait": False})
        self.assertEqual([line for line in lines if line.startswith("M190")], ["M190 S70"])

    def test_relative_moves_at_tool_change_refused(self):
        data = fixture("multi.gcode").replace(b"T1\n", b"G91\nT1\n")
        with self.assertRaisesRegex(purge.PurgeError, "G90"):
            run(data)

    def test_no_bed_size_refused(self):
        data = fixture("single.gcode").replace(b"; printable_area", b"; other_area")
        with self.assertRaisesRegex(purge.PurgeError, "bed size"):
            run(data)

    def test_no_bed_temperature_refused(self):
        data = fixture("single.gcode").replace(b"G9111 bedTemp=60", b"G9111 bedTemp=0")
        with self.assertRaisesRegex(purge.PurgeError, "bed temperature"):
            run(data)

    def test_bed_temperature_after_the_first_layer_is_ignored(self):
        data = fixture("single.gcode").replace(b"G9111 bedTemp=60 extruderTemp=220\n", b"")
        with self.assertRaisesRegex(purge.PurgeError, "bed temperature"):   # only "M140 S0" late in the file
            run(data)

    def test_corners_stay_inside_the_bed(self):
        bed = purge.parse_area("10x20,210x20,210x220,10x220")
        self.assertEqual(bed, (10.0, 20.0, 210.0, 220.0))
        points = {c: purge.purge_point({"corner": c}, bed) for c in purge.CORNERS}   # lane 0
        self.assertEqual(points, {"front_left": (15, 25), "front_right": (205, 25), "back_left": (15, 215),
                                  "back_right": (205, 215)})
        for bad in ("", "0x0,5x0,5x5", "nonsense", "0x0,260x0", "0x0,nanx0,260x260,0x260", "0x0,1e9x0,1e9x1e9,0x1e9"):
            self.assertIsNone(purge.parse_area(bad), bad)

    def test_options_clamped_and_defaulted(self):
        self.assertEqual(purge.options({}), purge.DEFAULTS)
        self.assertEqual(purge.options({"purge_length": 900, "purge_speed": 0, "purge_corner": "middle"}),
                         {"length": 50.0, "speed": 1.0, "corner": "front_left"})
        self.assertEqual(purge.options({"purge_length": True})["length"], 15.0)

    def test_preview(self):
        p = purge.preview(dict(OPTS, length=30.0), (0, 0, 260, 260), "<t>")
        self.assertEqual(p["bed_wait"][1], "M190 S<t> ; wait for the first-layer bed temperature")
        self.assertIn("G1 X<X> Y<Y> F12000", p["purge"])
        self.assertIn("G1 X35 Y5 E30 F300", p["purge"])
        self.assertEqual(p["point"], ["5", "5"])


class Settings(unittest.TestCase):
    def test_off_by_default_and_validated(self):
        store = settings.Store()
        self.assertFalse(store.effective()["purge_enabled"])
        out = store.update({"purge_enabled": True, "purge_length": 40, "purge_speed": 50, "purge_corner": "back_left"})
        self.assertEqual((out["purge_enabled"], out["purge_length"], out["purge_speed"], out["purge_corner"]),
                         (True, 40.0, 5.0, "back_left"))   # 50 mm/s is out of range: the default stays
        self.assertEqual(store.update({"purge_corner": "middle"})["purge_corner"], "back_left")


class InAJob(Base):
    def setUp(self):
        super().setUp()
        self.fake.print_start = "ok"
        self.svc.work_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "multi.gcode")
        with open(self.path, "wb") as f:
            f.write(fixture("multi.gcode"))

    def digest(self):
        with open(self.path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def test_off_sends_the_file_as_sliced(self):
        self.svc.send_file(self.fake.host, self.path, "part")
        self.assertEqual(self.fake.uploads[0]["data"], fixture("multi.gcode"))

    def test_on_sends_a_processed_copy_and_keeps_the_original(self):
        before = self.digest()
        self.svc.purge_options = dict(OPTS)
        self.svc.print_job(self.fake.host, self.path, 1, "part", [0], [{"colour": "#FF0000", "type": "PLA"}])
        sent = self.fake.uploads[0]["data"].decode()
        self.assertEqual(sent.count(purge.START), 3)   # bed wait + the two tool changes after the first layer
        self.assertEqual(self.digest(), before)
        self.assertEqual(glob.glob(os.path.join(self.svc.work_dir, "*")), [])   # the copy is removed
        wait(lambda: self.sent("print", "start"))

    def test_refused_file_sends_nothing(self):
        with open(self.path, "wb") as f:
            f.write(fixture("multi.gcode").replace(b"T1\n", b"G91\nT1\n"))   # relative moves at a tool change
        self.svc.purge_options = dict(OPTS)
        with self.assertRaisesRegex(kobra.KobraError, "nothing was sent"):
            self.svc.print_job(self.fake.host, self.path, 1, "part", [0], [{"colour": "#FF0000", "type": "PLA"}])
        time.sleep(0.2)
        self.assertEqual(self.fake.uploads, [])
        self.assertFalse(self.sent("print", "start"))
        self.assertEqual(glob.glob(os.path.join(self.svc.work_dir, "*")), [])


if __name__ == "__main__":
    unittest.main()
