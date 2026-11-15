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

    def test_blocks_across_chunk_boundaries(self):
        """L6: large files are read in chunks with an overlap; a PEM split by a boundary is still found."""
        lib = self.blob()
        cut = lib.index(read(self.tls.client_cert)) + 100
        self.write("c/lib.dylib", lib)
        with mock.patch.object(certs, "CHUNK", cut), mock.patch.object(certs, "OVERLAP", 8192):
            self.assert_client_pair(certs.find([os.path.join(self.tmp, "c")]))

    def test_match_cleans_up_on_error(self):
        """L3: candidate keys live in a private 0700 temp dir that is removed even on exceptions."""
        private = os.path.join(self.tmp, "tmp")
        os.makedirs(private)
        self.write("t/a.dylib", self.blob())
        modes = []

        def boom():
            d = [os.path.join(private, n) for n in os.listdir(private)][0]
            modes.append(stat.S_IMODE(os.stat(d).st_mode))
            raise RuntimeError("boom")
        with mock.patch.object(tempfile, "tempdir", private), mock.patch.object(certs, "_client_context", boom):
            with self.assertRaises(RuntimeError):
                certs.find([os.path.join(self.tmp, "t")])
        self.assertEqual(os.listdir(private), [])
        if os.name == "posix":
            self.assertEqual(modes, [0o700])

    def test_find_with_workdir_uses_no_tempfile(self):
        """C3: OrcaSlicer denies tempfile creators off the main thread; with workdir the match dir is
        os.mkdir'ed inside it and removed explicitly, also when matching fails."""
        lib = self.write("w/lib.dylib", self.blob())
        work = os.path.join(self.tmp, "storage")
        os.makedirs(work)
        made = []
        real_mkdir = os.mkdir

        def spy(path, mode=0o777):
            if os.path.dirname(path) == work:
                made.append((os.path.basename(path), mode))
            real_mkdir(path, mode)
        no = mock.Mock(side_effect=AssertionError("tempfile used"))
        with mock.patch.multiple(tempfile, mkstemp=no, mkdtemp=no, TemporaryDirectory=no), \
                mock.patch.object(certs.os, "mkdir", spy):
            self.assert_client_pair(certs.find([lib], workdir=work))
            self.assertEqual(os.listdir(work), [])
            with mock.patch.object(certs, "_client_context", side_effect=RuntimeError("boom")):
                with self.assertRaises(RuntimeError):
                    certs.find([lib], workdir=work)
            self.assertEqual(os.listdir(work), [])
            self.write("w2/lib.dylib", read(self.tls.client_cert) + read(self.tls.server_key))
            with self.assertRaises(certs.CertError):
                certs.find([os.path.join(self.tmp, "w2")], workdir=work)
            self.assertEqual(os.listdir(work), [])
        self.assertEqual(len(made), 3)
        for name, mode in made:
            self.assertRegex(name, r"^match-[0-9a-f]{8}$")
            self.assertNotIn(name.lower(), DENIED)
            self.assertEqual(mode, 0o700)

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

    @unittest.skipUnless(os.name == "posix", "file modes are POSIX only")
    def test_save_tightens_before_writing(self):
        """L3: an existing 0644 key file is made 0600 before the key goes in; the folder becomes 0700."""
        folder = os.path.join(self.tmp, "keep")
        os.makedirs(folder, 0o755)
        os.chmod(folder, 0o755)
        key_path = certs.paths(folder)[1]
        with open(key_path, "w") as f:
            f.write("old")
        os.chmod(key_path, 0o644)
        seen = []
        real = os.fchmod

        def spy(fd, mode):
            real(fd, mode)
            st = os.fstat(fd)
            seen.append((stat.S_IMODE(st.st_mode), st.st_size))
        with mock.patch.object(certs.os, "fchmod", spy):
            certs.save(folder, "C\n", "SECRET KEY\n")
        self.assertEqual(seen, [(0o600, 0), (0o600, 0)])
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        self.assertEqual(certs.load(folder)[1], "SECRET KEY\n")

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "O_NOFOLLOW not available")
    def test_save_refuses_symlinked_key_file(self):
        folder = os.path.join(self.tmp, "keep")
        os.makedirs(folder)
        target = os.path.join(self.tmp, "elsewhere.txt")
        with open(target, "w") as f:
            f.write("untouched")
        os.symlink(target, certs.paths(folder)[1])
        with self.assertRaises(certs.CertError):
            certs.save(folder, "C\n", "KEY\n")
        with open(target) as f:
            self.assertEqual(f.read(), "untouched")

    def test_walk_is_bounded(self):
        """L6: too many files or too deep a tree is a clear CertError."""
        for i in range(5):
            self.write("many/f%d.so" % i, b"x")
        with mock.patch.object(certs, "MAX_FILES", 3):
            with self.assertRaisesRegex(certs.CertError, "more than 3 files"):
                certs.find([os.path.join(self.tmp, "many")])
        self.write("deep/" + "/".join("d%d" % i for i in range(5)) + "/a.so", b"x")
        with mock.patch.object(certs, "MAX_DEPTH", 3):
            with self.assertRaisesRegex(certs.CertError, "deeper than 3"):
                certs.find([os.path.join(self.tmp, "deep")])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks not available")
    def test_symlinked_directories_are_not_followed(self):
        outside = os.path.join(self.tmp, "outside")
        self.write("outside/lib.so", b"-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n")
        self.write("tree/real.so", b"nothing")
        os.symlink(outside, os.path.join(self.tmp, "tree", "link"))
        with self.assertRaisesRegex(certs.CertError, "0 certificates") as cm:
            certs.find([os.path.join(self.tmp, "tree")])
        self.assertIn("in 1 files", str(cm.exception))

    def test_max_size_lowered(self):
        self.assertLessEqual(certs.MAX_SIZE, 200 * 1024 * 1024)

    def test_load_missing(self):
        with self.assertRaises(certs.CertError):
            certs.load(self.tmp)

    def test_saved_names_avoid_sandbox_denials(self):
        for name in (certs.CERT_FILE, certs.KEY_FILE, "certs.py"):
            self.assertNotIn(name.lower(), DENIED)
            self.assertFalse(name.lower().endswith((".conf", ".ini")))
            self.assertFalse(name.lower().startswith(("orcaslicer", "gcodeviewer", ".install_state", "user_secret")))

    def test_grant_targets(self):
        """C3: tree grants for OrcaSlicer: realpath + "/*", plus the given form when it differs."""
        real = os.path.join(self.tmp, "real")
        os.makedirs(real)
        alias = os.path.join(self.tmp, "alias")
        os.symlink(real, alias)
        with mock.patch.object(certs, "default_locations", return_value=[real, alias]):
            targets = certs.grant_targets()
        rp = os.path.realpath(real)
        self.assertEqual(targets[0], rp + "/*")
        self.assertIn(alias + "/*", targets)
        self.assertEqual(len(targets), len(set(targets)))
        self.assertTrue(all(t.endswith("/*") for t in certs.grant_targets()))

    def test_default_locations(self):
        mac = certs.default_locations("darwin", {})
        self.assertIn("/Applications/AnycubicSlicerNext.app/Contents/Frameworks", mac)
        self.assertIn("/Applications/AnycubicSlicerNext.app/Contents/MacOS", mac)
        win = certs.default_locations("win32", {"ProgramFiles": r"C:\Program Files"})
        self.assertIn(os.path.join(r"C:\Program Files", "AnycubicSlicerNext"), win)
        self.assertTrue(certs.default_locations("linux", {"HOME": "/home/u"}))


class BundledTests(unittest.TestCase):
    def test_bundled_cert_ships_and_loads(self):
        """The AnycubicSlicer certificate committed next to certs.py is present and the pair loads."""
        shipped = certs.bundled()
        self.assertIsNotNone(shipped, "bundled Anycubic certificate missing from the package")
        cert_path, key_path = shipped
        self.assertTrue(certs._is_anycubic(open(cert_path, encoding="ascii").read()))
        certs.context(cert_path, key_path)   # raises on a mismatched pair

    def test_unloadable_bundled_pair_is_no_certificate(self):
        """A bundled pair that is unreadable or broken (and no saved one) says what to do, not a generic error."""
        import connection
        bad = tempfile.mkdtemp()
        for name in ("c.pem", "k.pem"):
            with open(os.path.join(bad, name), "w") as f:
                f.write("not a pem")
        with mock.patch.object(certs, "bundled", return_value=(os.path.join(bad, "c.pem"), os.path.join(bad, "k.pem"))):
            with self.assertRaises(connection.NoCertificate) as raised:
                connection.tls_from(tempfile.mkdtemp())()
        self.assertIn("bundled", str(raised.exception))
        self.assertIn("Find Anycubic certificate", str(raised.exception))

    def test_bundled_is_none_without_files(self):
        with mock.patch.object(certs, "paths", return_value=("/no/such.pem", "/no/such_key.pem")):
            self.assertIsNone(certs.bundled())


if __name__ == "__main__":
    unittest.main()
