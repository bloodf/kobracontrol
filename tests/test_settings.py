import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import settings  # noqa: E402


class StoreTests(unittest.TestCase):
    def test_defaults_without_storage(self):
        s = settings.Store().effective()
        self.assertEqual(s, settings.DEFAULTS)
        self.assertEqual(s["printer_name"], "Anycubic Kobra X")
        self.assertTrue(s["camera_enabled"])
        self.assertEqual(s["ui_language"], "auto")

    def test_update_validates_and_ignores_unknown(self):
        st = settings.Store()
        out = st.update({"host": "192.168.1.9", "camera_enabled": False, "auto_leveling": "yes", "nope": 1,
                         "ui_language": "klingon", "printer_name": "  Bob   X  "})
        self.assertEqual(out["host"], "192.168.1.9")
        self.assertFalse(out["camera_enabled"])
        self.assertTrue(out["auto_leveling"])              # wrong type ignored
        self.assertNotIn("nope", out)
        self.assertEqual(out["ui_language"], "auto")       # not in UI_LANGUAGES
        self.assertEqual(out["printer_name"], "Bob X")     # whitespace collapsed
        self.assertEqual(st.update({"ui_language": "pt-BR"})["ui_language"], "pt-BR")

    def test_empty_printer_name_falls_back(self):
        self.assertEqual(settings.Store().update({"printer_name": "   "})["printer_name"], "Anycubic Kobra X")

    def test_file_roundtrip_atomic_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "settings.json")
            settings.Store(path).update({"spoolman_url": "box:7912"})
            self.assertEqual(settings.Store(path).effective()["spoolman_url"], "box:7912")
            self.assertEqual([n for n in os.listdir(d)], ["settings.json"])
            with open(path, "w") as f:
                f.write("{broken")
            self.assertEqual(settings.Store(path).effective(), settings.DEFAULTS)

    def test_callables(self):
        box = []
        st = settings.Store(load=lambda: box[-1] if box else "", save=box.append)
        st.update({"host": "h"})
        self.assertEqual(json.loads(box[-1])["host"], "h")
        self.assertEqual(settings.Store(load=lambda: box[-1], save=box.append).effective()["host"], "h")

    def test_effective_is_a_copy_and_unchanged_update_does_not_write(self):
        box = []
        st = settings.Store(load=lambda: "", save=box.append)
        st.effective()["host"] = "x"
        self.assertEqual(st.effective()["host"], "")
        st.update({"host": "a"})
        st.update({"host": "a", "bogus": 1})
        self.assertEqual(len(box), 1)

    def test_printer_label(self):
        self.assertEqual(settings.printer_label("  a   b "), "a b")
        self.assertEqual(settings.printer_label(None), settings.DEFAULT_PRINTER_NAME)

    def test_no_secret_keys(self):
        self.assertFalse([k for k in settings.DEFAULTS if "key" in k or "password" in k or "token" in k])


if __name__ == "__main__":
    unittest.main()
