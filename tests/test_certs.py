"""Client certificate discovery in slicer binaries, saving/loading, TLS context."""

import json
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


def pem_body(pem):
    """A PEM block's base64 body without any whitespace or line endings."""
    return "".join(pem.strip().splitlines()[1:-1]).replace(" ", "").replace("\r", "")


def read(path):
    with open(path, "rb") as f:
        return f.read()


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, rel, data):
        """rel uses "/"; the file is written at, and its path returned in, this OS's own form."""
        path = os.path.join(self.tmp, *rel.split("/"))
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
        """The same PEM blocks whatever their line endings: openssl writes CRLF files on Windows, and find()
        returns every block in one form (LF, 64-character lines)."""
        self.assertEqual(pem_body(found.cert_pem), pem_body(read(self.tls.client_cert).decode()))
        self.assertEqual(pem_body(found.key_pem), pem_body(read(self.tls.client_key).decode()))
        for pem in (found.cert_pem, found.key_pem):
            self.assertNotIn("\r", pem)
            self.assertTrue(all(len(line) <= 64 for line in pem.splitlines()))

    def test_any_line_endings_pair(self):
        """A certificate and its key are paired whatever line endings the binary carries: LF, CRLF (Windows), CR,
        CR CR LF (CRLF text converted twice), blank lines, or one form for the certificate and another for the
        key. Pinned on every OS: the fixtures' own endings (CRLF on Windows) are first made LF."""
        def lf(path):
            return read(path).replace(b"\r\n", b"\n")
        forms = {"lf": b"\n", "crlf": b"\r\n", "cr": b"\r", "crcrlf": b"\r\r\n", "blank": b"\n\n"}
        for cert_form, key_form in [(f, f) for f in forms] + [("lf", "crlf"), ("crlf", "cr"), ("crcrlf", "lf")]:
            data = (b"\x00" + lf(self.tls.client_cert).replace(b"\n", forms[cert_form]) + b"\x01"
                    + lf(self.tls.client_key).replace(b"\n", forms[key_form]) + b"\x02")
            lib = self.write("e/%s-%s.dll" % (cert_form, key_form), data)
            with self.subTest(cert=cert_form, key=key_form):
                self.assert_client_pair(certs.find([lib]))

    def test_picks_anycubic_pair_from_fake_dylib(self):
        lib = self.write("Frameworks/libcloud_mqtt.dylib", self.blob())
        found = certs.find([os.path.join(self.tmp, "Frameworks")])
        self.assert_client_pair(found)
        # find() walks the folder itself, so the path it reports (and Find certificate shows) is a native one
        self.assertEqual(found.source, os.path.join(self.tmp, "Frameworks", "libcloud_mqtt.dylib"))
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

    def test_refused_files_say_denied_not_nothing_found(self):
        """OrcaSlicer's sandbox refusing every file must not read as "no slicer files" (the user would keep
        pressing Find certificate, each press another blocked scan)."""
        self.write("t/libcloud_mqtt.dylib", b"x")
        with mock.patch.object(certs, "_chunks", side_effect=PermissionError(13, "audit permission required")), \
                self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "t")])
        self.assertIn("OrcaSlicer did not let kobracontrol read", str(cm.exception))
        self.assertIn("bundled with the plugin is used", str(cm.exception))

    def test_refused_folder_says_denied(self):
        folder = os.path.join(self.tmp, "t")
        with mock.patch.object(certs.os, "stat", side_effect=PermissionError(13, "denied", folder)), \
                self.assertRaises(certs.CertError) as cm:
            certs.find([folder])
        self.assertIn("OrcaSlicer did not let kobracontrol read", str(cm.exception))

    def test_refused_listing_inside_a_folder_says_denied(self):
        self.write("t/sub/a.dylib", b"x")
        real = os.scandir

        def scandir(path="."):
            if os.path.basename(str(path)) == "t":
                raise PermissionError(13, "denied", str(path))
            return real(path)
        with mock.patch.object(os, "scandir", scandir), self.assertRaises(certs.CertError) as cm:
            certs.find([os.path.join(self.tmp, "t")])
        self.assertIn("OrcaSlicer did not let kobracontrol read", str(cm.exception))

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
    def test_save_writes_0600_without_chmod_or_descriptor_opens(self):
        """L3: an existing 0644 key file is replaced by a fresh 0600 one. In OrcaSlicer fchmod and open(fd) raise
        audit events with no path, which the owner's log showed blocked ("event=os.chmod reason=audit permission
        required"): save uses neither."""
        folder = os.path.join(self.tmp, "keep")
        os.makedirs(folder)
        key_path = certs.paths(folder)[1]
        with open(key_path, "w") as f:
            f.write("old")
        os.chmod(key_path, 0o644)
        real_open = open

        def no_descriptor_open(file, *a, **kw):
            assert not isinstance(file, int), "open() of a file descriptor"
            return real_open(file, *a, **kw)
        with mock.patch.object(certs.os, "fchmod", side_effect=AssertionError("fchmod"), create=True), \
                mock.patch.object(certs.os, "chmod", side_effect=AssertionError("chmod")), \
                mock.patch("builtins.open", no_descriptor_open):
            certs.save(folder, "C\n", "SECRET KEY\n")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(os.stat(key_path).st_mode), 0o600)
        self.assertEqual(certs.load(folder)[1], "SECRET KEY\n")
        self.assertEqual(sorted(os.listdir(folder)), sorted(os.path.basename(p) for p in certs.paths(folder)))

    @unittest.skipUnless(hasattr(os, "symlink") and os.name != "nt", "symlinks")
    def test_save_replaces_a_symlinked_key_file_without_following_it(self):
        folder = os.path.join(self.tmp, "keep")
        os.makedirs(folder)
        target = os.path.join(self.tmp, "elsewhere.txt")
        with open(target, "w") as f:
            f.write("untouched")
        os.symlink(target, certs.paths(folder)[1])
        certs.save(folder, "C\n", "KEY\n")
        with open(target) as f:
            self.assertEqual(f.read(), "untouched")
        self.assertFalse(os.path.islink(certs.paths(folder)[1]))
        self.assertEqual(certs.load(folder)[1], "KEY\n")

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

    def test_default_locations(self):
        mac = certs.default_locations("darwin", {})   # the one library with the pair: one read, one prompt
        self.assertEqual(mac[0], "/Applications/AnycubicSlicerNext.app/Contents/Frameworks/libcloud_mqtt.dylib")
        self.assertEqual(len(mac), 2)
        win = certs.default_locations("win32", {"ProgramFiles": r"C:\Program Files"})
        self.assertIn(r"C:\Program Files\AnycubicSlicerNext", win)
        self.assertIn(r"C:\Users\u\AppData\Local\Programs\AnycubicSlicerNext",
                      certs.default_locations("win32", {"LOCALAPPDATA": r"C:\Users\u\AppData\Local"}))
        self.assertIn("/home/u/.local/share/AnycubicSlicerNext", certs.default_locations("linux", {"HOME": "/home/u"}))


class PinTests(unittest.TestCase):
    """The printer's TLS certificate, remembered per address: a change is reported, never refused."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "printers.json")

    def test_first_same_and_changed(self):
        pins = certs.Pins(self.path)
        self.assertEqual(pins.check("10.0.0.5", "aa"), None)
        self.assertEqual(pins.check("10.0.0.5", "aa"), None)
        self.assertEqual(certs.Pins(self.path).check("10.0.0.5", "bb"), "aa")   # survives a restart
        self.assertEqual(certs.Pins(self.path).check("10.0.0.5", "bb"), None)    # the new one is remembered
        self.assertEqual(pins.check("10.0.0.6", "aa"), None)                   # per address

    def test_unreadable_file_starts_over(self):
        with open(self.path, "w") as f:
            f.write("{not json")
        self.assertEqual(certs.Pins(self.path).check("h", "aa"), None)
        with open(self.path) as f:
            self.assertEqual(json.load(f)["printers"], {"h": "aa"})

    def test_bad_entries_are_ignored(self):
        with open(self.path, "w") as f:
            json.dump({"printers": {"h": 5, "g": "cc"}}, f)
        pins = certs.Pins(self.path)
        self.assertEqual(pins.check("h", "aa"), None)
        self.assertEqual(pins.check("g", "dd"), "cc")


class BundledTests(unittest.TestCase):
    def test_bundled_cert_ships_and_loads(self):
        """The AnycubicSlicer certificate committed next to certs.py is present and the pair loads."""
        shipped = certs.bundled()
        self.assertIsNotNone(shipped, "bundled Anycubic certificate missing from the package")
        cert_path, key_path = shipped
        self.assertTrue(certs._is_anycubic(read(cert_path).decode("ascii")))
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
