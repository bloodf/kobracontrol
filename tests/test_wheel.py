"""The built wheel: expected files, valid RECORD, metadata, no dynamic code execution, and that it imports and
registers its capabilities under a fake `orca`."""

import ast
import base64
import hashlib
import re
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
import build  # noqa: E402
import fake_orca  # noqa: E402

PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
DIST_INFO = "kobracontrol-%s.dist-info/" % PROJECT["version"]
EXPECTED = {"kobracontrol/%s.py" % n for n in ("__init__", "_assets") + build.MODULES} | {
    "kobracontrol/anycubic_slicer.pem", "kobracontrol/anycubic_slicer_key.pem"} | {
    DIST_INFO + n for n in ("METADATA", "WHEEL", "RECORD", "top_level.txt", "licenses/LICENSE", "licenses/PrimeUIX.txt",
                            "licenses/PrimeVue.txt", "licenses/Vue.txt")}
# (?<![.\w]): a JS method call such as RegExp .exec( in the embedded page is not Python exec().
FORBIDDEN = re.compile(r"(?<![.\w])exec\(|(?<![.\w])eval\(|__import__|importlib")
DYNAMIC_BUILTINS = {"exec", "eval", "compile", "__import__"}


class WheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = build.build(out_dir=Path(tempfile.mkdtemp()))
        cls.zip = zipfile.ZipFile(cls.path)
        cls.addClassCleanup(cls.zip.close)

    def read(self, name):
        return self.zip.read(name).decode("utf-8")

    def test_every_source_module_is_packed(self):
        sources = {p.stem for p in (ROOT / "src" / "kobracontrol").glob("*.py")} - {"plugin"}
        self.assertEqual(sources, set(build.MODULES))

    def test_exact_file_list(self):
        self.assertEqual(set(self.zip.namelist()), EXPECTED)
        self.assertEqual(len(self.zip.namelist()), len(EXPECTED))

    def test_record_hashes_and_sizes(self):
        rows = {}
        for line in self.read(DIST_INFO + "RECORD").splitlines():
            name, digest, size = line.rsplit(",", 2)
            rows[name] = (digest, size)
        self.assertEqual(set(rows), EXPECTED)
        self.assertEqual(rows[DIST_INFO + "RECORD"], ("", ""))
        for name in EXPECTED - {DIST_INFO + "RECORD"}:
            data = self.zip.read(name)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            self.assertEqual(rows[name], ("sha256=" + digest, str(len(data))), name)

    def test_metadata_and_wheel_files(self):
        meta = dict(line.split(": ", 1) for line in self.read(DIST_INFO + "METADATA").splitlines() if ": " in line)
        self.assertEqual(meta["Name"], "kobracontrol")
        self.assertEqual(meta["Version"], PROJECT["version"])
        self.assertEqual(meta["License"], PROJECT["license"])
        self.assertNotIn("Requires-Dist", self.read(DIST_INFO + "METADATA"))
        wheel = self.read(DIST_INFO + "WHEEL")
        for line in ("Wheel-Version: 1.0", "Root-Is-Purelib: true", "Tag: py3-none-any"):
            self.assertIn(line, wheel.splitlines())
        self.assertEqual(self.read(DIST_INFO + "top_level.txt").strip(), "kobracontrol")

    def test_version_matches_pyproject(self):
        self.assertIn("VERSION = %r" % PROJECT["version"], self.read("kobracontrol/__init__.py"))

    def test_imports_are_package_relative(self):
        names = "|".join(build.MODULES)
        for name in (n for n in EXPECTED if n.endswith(".py") and not n.endswith("_assets.py")):
            text = self.read(name)
            self.assertIsNone(re.search(r"(?m)^\s*(import (%s)\b|from (%s) import)" % (names, names), text), name)

    def test_no_dynamic_execution(self):
        for name in (n for n in EXPECTED if n.endswith(".py")):
            text = self.read(name)
            self.assertIsNone(FORBIDDEN.search(text), name)
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, DYNAMIC_BUILTINS, name)

    def test_loads_and_registers_under_fake_orca(self):
        orca = fake_orca.install_orca()
        orca.registered.clear()
        ns = fake_orca.load_wheel(self.path)
        ns["KobraControl"]().register_capabilities()
        self.assertEqual([c.__name__ for c in orca.registered],
                         ["KobraAgent", "KobraControlPage", "CheckConnection", "FindCertificate"])
        self.assertEqual(ns["KobraAgent"]().get_agent_info().id, "kobracontrol")
        page = ns["KobraControlPage"]().get_ui()
        self.assertNotIn("__BOOT__", page)
        self.assertNotIn("__ICONS__", page)

    def test_reproducible(self):
        again = build.build(out_dir=Path(tempfile.mkdtemp()))
        self.assertEqual(again.read_bytes(), self.path.read_bytes())

    def test_sha256sums(self):
        line = (self.path.parent / "SHA256SUMS").read_text("utf-8").strip()
        self.assertEqual(line, "%s  kobracontrol_any.whl" % hashlib.sha256(self.path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
