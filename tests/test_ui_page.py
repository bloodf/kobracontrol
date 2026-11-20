"""Behaviour of the compiled Kobra Control page (Vue 3 + PrimeVue, ui/ -> src/kobracontrol/ui/app.html): its real
production build runs in an owned headless Chrome under a host-like CSP, with a scripted OrcaSlicer bridge
(ui/tests/page/run.mjs). Needs Node.js (`node` on PATH or NODE=...) and Chrome/Chromium (found automatically or CHROME=...)."""

import os
import shutil
import subprocess
import sys
import tempfile
import json
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "scripts")]

import build  # noqa: E402

NODE = os.environ.get("NODE") or shutil.which("node")
RUNNER = os.path.join(ROOT, "ui", "tests", "page", "run.mjs")
UNIT = os.path.join(ROOT, "ui", "tests", "unit")


class PageLogic(unittest.TestCase):
    def test_unit_tests_of_the_page_rules(self):
        """node --test of ui/tests/unit (targets, slots, locale, messages, tracker timeout/no-retry)."""
        if not NODE:
            self.fail("Node.js is needed: put node on PATH or set NODE")
        files = sorted(os.path.join(UNIT, f) for f in os.listdir(UNIT) if f.endswith(".test.ts"))
        proc = subprocess.run([NODE, "--test", *files], capture_output=True, text=True, timeout=120, cwd=os.path.join(ROOT, "ui"))
        self.assertEqual(proc.returncode, 0, proc.stdout[-4000:] + proc.stderr[-2000:])


class BuiltPage(unittest.TestCase):
    def test_page_scenarios_in_headless_chrome(self):
        if not NODE:
            self.fail("Node.js is needed for the page tests: put node on PATH or set NODE")
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "app.html")
            with open(page, "w", encoding="utf-8") as f:
                f.write(build.page_html("app.html"))   # icons injected exactly as in the wheel
            results = os.path.join(tmp, "results.json")
            env = {**os.environ, "PAGE": page, "RESULTS": results}
            proc = subprocess.run([NODE, RUNNER], capture_output=True, text=True, timeout=600, env=env, cwd=os.path.join(ROOT, "ui"))
            failed = []
            if os.path.exists(results):
                with open(results, encoding="utf-8") as f:
                    failed = ["%s: %s" % (r["name"], r.get("error", "")) for r in json.load(f) if not r["ok"]]
            # the failing scenarios by name and assertion first, then the runner's own output
            self.assertEqual(proc.returncode, 0, "failed page scenarios:\n  " + "\n  ".join(failed) + "\n\n" + proc.stdout[-4000:] + proc.stderr[-3000:])
            self.assertIn("PASS", proc.stdout)
            with open(results, encoding="utf-8") as f:
                done = json.load(f)
            self.assertGreaterEqual(len(done), 40)
            self.assertTrue(all(r["ok"] for r in done))


if __name__ == "__main__":
    unittest.main()
