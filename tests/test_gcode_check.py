"""gcode_check.py and JobsMixin.check_gcode: read-only checks of the sliced G-code and the printer preset.
Fixtures in tests/fixtures/gcode are OrcaSlicer-shaped files: good, without the config block, without a thumbnail."""

import hashlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "gcode")

import gcode_check  # noqa: E402
import i18n  # noqa: E402
import jobs  # noqa: E402


def read(path):
    with open(path, "rb") as f:
        return f.read()


def fixture(name):
    return read(os.path.join(FIXTURES, name))


def inspect(data):
    return gcode_check.inspect(io.BytesIO(data), len(data))


class Inspect(unittest.TestCase):
    def test_good_file_has_no_problems(self):
        self.assertEqual(inspect(fixture("good.gcode")), [])

    def test_missing_config_block(self):
        self.assertEqual(inspect(fixture("no_config_block.gcode")), [gcode_check.NO_CONFIG])

    def test_missing_thumbnail(self):
        self.assertEqual(inspect(fixture("no_thumbnail.gcode")), [gcode_check.NO_THUMBNAIL])

    def test_jpg_or_qoi_thumbnail_only(self):
        for tag in (b"thumbnail_JPG", b"thumbnail_QOI"):
            data = fixture("good.gcode").replace(b"; thumbnail begin", b"; " + tag + b" begin")
            self.assertEqual(inspect(data), [gcode_check.NOT_PNG], tag)

    def test_png_next_to_another_format_is_fine(self):
        data = fixture("good.gcode").replace(b"; THUMBNAIL_BLOCK_END", b";\n; thumbnail_JPG begin 8x8 4\n; abcd\n"
                                             b"; thumbnail_JPG end\n; THUMBNAIL_BLOCK_END", 1)
        self.assertEqual(inspect(data), [])

    def test_large_file_reads_only_head_and_tail(self):
        good = fixture("good.gcode")
        cut = good.index(b"; EXECUTABLE_BLOCK_END")
        data = good[:cut] + b"G1 X1 Y1 E0.1\n" * 200000 + good[cut:]
        self.assertGreater(len(data), gcode_check.HEAD + gcode_check.TAIL)
        source = io.BytesIO(data)
        reads = []
        read = source.read
        source.read = lambda n=-1: reads.append(n) or read(n)
        self.assertEqual(gcode_check.inspect(source, len(data)), [])
        self.assertEqual(reads, [gcode_check.HEAD, gcode_check.TAIL])
        no_config = fixture("no_config_block.gcode")
        cut = no_config.index(b"; EXECUTABLE_BLOCK_END")
        big = no_config[:cut] + b"G1 X1 Y1 E0.1\n" * 200000 + no_config[cut:]
        self.assertEqual(inspect(big), [gcode_check.NO_CONFIG])

    def test_config_block_at_the_top_counts(self):
        """BBL-style G-code carries the block after the header."""
        data = fixture("no_config_block.gcode").replace(
            b"; HEADER_BLOCK_END\n", b"; HEADER_BLOCK_END\n; CONFIG_BLOCK_START\n; layer_height = 0.2\n; CONFIG_BLOCK_END\n", 1)
        self.assertEqual(inspect(data), [])

    def test_empty_file(self):
        self.assertEqual(inspect(b""), [gcode_check.NO_CONFIG, gcode_check.NO_THUMBNAIL])


class Preset(unittest.TestCase):
    def test_kobra_x_profile_values_are_fine(self):
        self.assertEqual(gcode_check.preset_problems("0", "32x32/PNG, 300x300/PNG"), [])

    def test_skip_config_block_on(self):
        for value in ("1", "true", True):
            self.assertEqual(gcode_check.preset_problems(value, "300x300/PNG"), [(gcode_check.PRESET_SKIPS_CONFIG, ())])

    def test_no_png_thumbnail(self):
        self.assertEqual(gcode_check.preset_problems("0", "300x300/JPG"), [(gcode_check.PRESET_NO_PNG, ("300x300/JPG",))])
        self.assertEqual(gcode_check.preset_problems("0", ""), [(gcode_check.PRESET_NO_PNG, ("-",))])

    def test_size_without_format_is_png(self):
        self.assertEqual(gcode_check.preset_problems("0", "300x300"), [])
        self.assertTrue(gcode_check.writes_png("96x96/QOI, 300x300/png"))

    def test_values_orcaslicer_did_not_give_are_not_judged(self):
        self.assertEqual(gcode_check.preset_problems(None, None), [])


class CheckGcode(unittest.TestCase):
    """JobsMixin.check_gcode on the files OrcaSlicer hands over; the file is never changed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logged = []
        self.jobs = types.SimpleNamespace(log=self.logged.append)
        self.addCleanup(i18n.set_language, "en")

    def check(self, path, plate=1):
        return jobs.JobsMixin.check_gcode(self.jobs, path, plate)

    def write_3mf(self, gcode, plate=1):
        path = os.path.join(self.tmp, "job.gcode.3mf")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Metadata/plate_%d.gcode" % plate, gcode)
        return path

    def test_3mf_plate_is_checked_and_left_unchanged(self):
        path = self.write_3mf(fixture("no_config_block.gcode"), plate=2)
        before = hashlib.sha256(read(path)).hexdigest()
        self.assertEqual(self.check(path, 2), [gcode_check.NO_CONFIG])
        self.assertEqual(hashlib.sha256(read(path)).hexdigest(), before)
        self.assertIn("G-code check", self.logged[0])

    def test_plain_gcode(self):
        self.assertEqual(self.check(os.path.join(FIXTURES, "no_thumbnail.gcode")), [gcode_check.NO_THUMBNAIL])
        self.assertEqual(self.check(os.path.join(FIXTURES, "good.gcode")), [])

    def test_large_3mf_member(self):
        good = fixture("good.gcode")
        cut = good.index(b"; EXECUTABLE_BLOCK_END")
        self.assertEqual(self.check(self.write_3mf(good[:cut] + b"G1 X1 Y1 E0.1\n" * 200000 + good[cut:])), [])

    def test_translated(self):
        i18n.set_language("de")
        self.assertEqual(self.check(os.path.join(FIXTURES, "no_thumbnail.gcode")),
                         [i18n.CATALOGUES["de"][gcode_check.NO_THUMBNAIL]])

    def test_unreadable_file_never_fails(self):
        self.assertEqual(self.check(os.path.join(self.tmp, "missing.gcode")), [])
        self.assertEqual(self.check(self.write_3mf(b"G28\n"), 3), [])   # no plate 3: the upload reports it
        self.assertIn("not checked", self.logged[-1])


if __name__ == "__main__":
    unittest.main()
