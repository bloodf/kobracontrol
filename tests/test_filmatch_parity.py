"""filmatch (the shared matcher from @orca-plugins/ui-foundation) keeps Kobra Control's results, and the committed copy
is the foundation's."""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import bambu  # noqa: E402
import spoolman  # noqa: E402

SHARED = os.path.join(ROOT, "ui", "node_modules", "@orca-plugins", "ui-foundation", "python", "filmatch.py")


def _read(path):
    with open(path, "rb") as f:
        return f.read().replace(b"\r\n", b"\n")   # a git checkout on Windows may give CRLF


class FilmatchParityTest(unittest.TestCase):
    def test_generic_ids_and_colours_unchanged(self):
        """fixtures/filmatch_parity.json: the results before the code moved to filmatch."""
        with open(os.path.join(ROOT, "tests", "fixtures", "filmatch_parity.json"), encoding="utf-8") as f:
            golden = json.load(f)
        got = [[m, bambu.material_family(m), bambu.generic_filament_id(m), spoolman.material_family(m)]
               for m, *_ in golden["generic"]]
        self.assertEqual(got, golden["generic"])
        self.assertEqual([[a, b, spoolman.colour_distance(a, b)] for a, b, _ in golden["colour_distance"]],
                         golden["colour_distance"])

    def test_committed_copy_is_the_foundations(self):
        self.assertTrue(os.path.exists(SHARED), "run npm ci in ui/")
        self.assertEqual(_read(os.path.join(ROOT, "src", "kobracontrol", "filmatch.py")), _read(SHARED),
                         "src/kobracontrol/filmatch.py differs from ui-foundation's; run `npm run build` in ui/")


if __name__ == "__main__":
    unittest.main()
