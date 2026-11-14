"""Client certificate discovery in slicer binaries, saving/loading, TLS context."""

import os
import shutil
import ssl
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import certs  # noqa: E402
from fake_kobra import make_tls_files  # noqa: E402

HAS_OPENSSL = bool(shutil.which("openssl"))
DENIED = {"secret", "secrets", "cert", "certs", "certificate", "certificates", "conf", "config"}


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, rel, data):
        path = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path


@unittest.skipUnless(HAS_OPENSSL, "openssl CLI needed to generate throwaway certificates")
class FindTests(Tmp):
    def setUp(self):
        super().setUp()
        self.pems = os.path.join(self.tmp, "pems")
        os.makedirs(self.pems)
        self.tls = make_tls_files(self.pems)   # server pair = decoy, client pair = CN=AnycubicSlicer

    def blob(self, crlf=False):
        parts = [os.urandom(3000), read(self.tls.server_cert), os.urandom(500), read(self.tls.client_key),
                 os.urandom(700), read(self.tls.server_key), b"\x00junk", read(self.tls.client_cert), os.urandom(900)]
        data = b"".join(parts)
        return data.replace(b"\n", b"\r\n") if crlf else data

    def assert_client_pair(self, found):
        self.assertEqual(found.cert_pem.strip(), read(self.tls.client_cert).decode().strip())
        self.assertEqual(found.key_pem.strip(), read(self.tls.client_key).decode().strip())

    def test_picks_anycubic_pair_from_fake_dylib(self):
        lib = self.write("Frameworks/libcloud_mqtt.dylib", self.blob())
        found = certs.find([os.path.join(self.tmp, "Frameworks")])
        self.assert_client_pair(found)
        self.assertEqual(found.source, lib)

    def test_crlf_and_single_file(self):
        lib = self.write("x/cloud_mqtt.dll", self.blob(crlf=True))
        self.assert_client_pair(certs.find([lib]))

    def test_extensionless_scanned_text_ignored(self):
        self.write("tree/MacOS/AnycubicSlicerNext", self.blob())
        self.write("tree/readme.txt", b"nothing")
        self.assert_client_pair(certs.find([os.path.join(self.tmp, "tree")]))

    def test_cert_and_key_in_different_files(self):
        self.write("t/a.so", read(self.tls.client_cert))
        self.write("t/b.so", read(self.tls.client_key) + read(self.tls.server_key))
        found = certs.find([os.path.join(self.tmp, "t")])
        self.assert_client_pair(found)
        self.assertTrue(found.key_source.endswith("b.so"))

    def test_ignored_extension_and_oversized_files(self):
        self.write("t/pems.txt", self.blob())
        self.write("t/big.dylib", self.blob())
        self.write("t/small.so", b"no pem here")
        with mock.patch.object(certs, "MAX_SIZE", 100):
            with self.assertRaises(certs.CertError) as cm:
                certs.find([os.path.join(self.tmp, "t")])
        self.assertIn("0 certificates", str(cm.exception))

    def test_cert_without_matching_key(self):
        self.write("t/a.dylib", read(self.tls.client_cert) + read(self.tls.server_key) + read(self.tls.server_cert))
        with self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "t")])
        msg = str(cm.exception)
        self.assertIn("2 certificates", msg)
        self.assertIn("1 key", msg)
        self.assertNotIn("PRIVATE", msg)

    def test_no_anycubic_cert(self):
        self.write("t/a.dylib", read(self.tls.server_cert) + read(self.tls.server_key))
        with self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "t")])
        self.assertIn("AnycubicSlicer", str(cm.exception))

    def test_context_loads_chain(self):
        ctx = certs.context(self.tls.client_cert, self.tls.client_key)
        self.assertIsInstance(ctx, ssl.SSLContext)
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)

    def test_context_with_mismatched_key(self):
        with self.assertRaises(certs.CertError):
            certs.context(self.tls.client_cert, self.tls.server_key)


class NoOpensslTests(Tmp):
    def test_nothing_found(self):
        self.write("t/a.dylib", os.urandom(2000))
        with self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "t")])
        self.assertIn("0 certificates, 0 keys", str(cm.exception))

    def test_missing_locations(self):
        with self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "nope")])
        self.assertIn("nope", str(cm.exception))

    def test_save_load_round_trip(self):
        folder = os.path.join(self.tmp, "plugin-data")
        cert_path, key_path = certs.save(folder, "CERT\n", "KEY\n")
        self.assertEqual(certs.load(folder), ("CERT\n", "KEY\n"))
        self.assertEqual((cert_path, key_path), certs.paths(folder))
        if os.name == "posix":
            for p in (cert_path, key_path):
                self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        certs.save(folder, "C2\n", "K2\n")
        self.assertEqual(certs.load(folder), ("C2\n", "K2\n"))

    def test_load_missing(self):
        with self.assertRaises(certs.CertError):
            certs.load(self.tmp)

    def test_saved_names_avoid_sandbox_denials(self):
        for name in (certs.CERT_FILE, certs.KEY_FILE, "certs.py"):
            self.assertNotIn(name.lower(), DENIED)
            self.assertFalse(name.lower().endswith((".conf", ".ini")))
            self.assertFalse(name.lower().startswith(("orcaslicer", "gcodeviewer", ".install_state", "user_secret")))

    def test_default_locations(self):
        mac = certs.default_locations("darwin", {})
        self.assertIn("/Applications/AnycubicSlicerNext.app/Contents/Frameworks", mac)
        self.assertIn("/Applications/AnycubicSlicerNext.app/Contents/MacOS", mac)
        win = certs.default_locations("win32", {"ProgramFiles": r"C:\Program Files"})
        self.assertIn(os.path.join(r"C:\Program Files", "AnycubicSlicerNext"), win)
        self.assertTrue(certs.default_locations("linux", {"HOME": "/home/u"}))


if __name__ == "__main__":
    unittest.main()
