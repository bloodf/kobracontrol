"""The Anycubic Slicer TLS client identity the Kobra X MQTT broker (port 9883) requires.

Anycubic Slicer Next ships its client certificate (CN `AnycubicSlicer`) and private key as plain PEM
text inside its binaries (libcloud_mqtt.dylib / cloud_mqtt.dll). `find` scans for them, `save`/`load`
keep a copy in the plugin's data folder, `context` builds the ssl.SSLContext for mqtt.Client.

Sandbox naming rule (OrcaSlicer v2.5.0, docs/HLSD/plugin-permissions.md and PluginAuditManager.cpp):
before any grant or full access, a plugin path is refused when its base name starts with
`OrcaSlicer.conf|.ini`, `GCodeViewer.conf|.ini`, the cloud user-secret file or `.install_state.json`
(case-insensitive prefix), or when ANY path component equals (case-insensitive, whole component)
`secret, secrets, cert, certs, certificate, certificates, conf, config`, or ends in `.conf`/`.ini`.
Whole-component matching means this module file `certs.py` is reachable, but a folder named `certs`
is not. Saved files are therefore `anycubic_slicer.pem` and `anycubic_slicer_key.pem`, and callers
must pass a folder whose components avoid the words above.

Key file handling: `save` makes the folder 0700 and each file 0600 (fchmod before any byte is
written, O_NOFOLLOW where available, so a symlink planted at the key path is refused). On Windows
these modes have no effect; the files are then protected only by the user profile's ACLs. `find`
writes candidate PEMs to a private 0700 folder that is removed even when matching fails: with
`workdir` (inside OrcaSlicer: the plugin's storage folder) a `match-<8 hex>` sub-folder made with
os.mkdir and removed with os.remove/os.rmdir, because OrcaSlicer denies every tempfile.* creator off
the main thread; without it (scripts/probe.py) a tempfile.TemporaryDirectory.
`find` is bounded: at most MAX_FILES files examined, MAX_DEPTH folder levels, files up to MAX_SIZE
read in CHUNK pieces (OVERLAP bytes shared between pieces so a PEM block on a boundary is still
seen), symlinked folders never followed.
"""

import base64
import contextlib
import json
import ntpath
import os
import posixpath
import re
import secrets
import ssl
import sys
import tempfile
import threading
from collections import namedtuple

CERT_FILE, KEY_FILE = "anycubic_slicer.pem", "anycubic_slicer_key.pem"
PINS_FILE = "printers.json"
EXPECTED_CN = b"AnycubicSlicer"
SCAN_EXT = {".dll", ".exe", ".so", ".dylib", ""}
MAX_SIZE = 200 * 1024 * 1024
MAX_FILES = 20000
MAX_DEPTH = 16
CHUNK = 16 * 1024 * 1024
OVERLAP = 64 * 1024  # far larger than a PEM certificate or RSA key block
CERT_RE = re.compile(rb"-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=\r\n]+?-----END CERTIFICATE-----")
KEY_RE = re.compile(rb"-----BEGIN ((?:RSA |EC )?PRIVATE KEY)-----[\r\n]+[A-Za-z0-9+/=\r\n]+?-----END \1-----")

Found = namedtuple("Found", "cert_pem key_pem source key_source")


class CertError(Exception):
    pass


def default_locations(platform=None, env=None):
    """The install folders of Anycubic Slicer Next on `platform`, joined with that platform's separators (so the
    answer does not depend on the OS this runs on)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "darwin":
        apps = ["/Applications", posixpath.join(env.get("HOME", "~"), "Applications")]
        return [posixpath.join(a, "AnycubicSlicerNext.app", "Contents", sub) for a in apps for sub in ("Frameworks", "MacOS")]
    if platform.startswith("win"):
        roots = [env.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        local = env.get("LOCALAPPDATA")
        out = [ntpath.join(r, "AnycubicSlicerNext") for r in roots if r]
        return out + ([ntpath.join(local, "Programs", "AnycubicSlicerNext")] if local else [])
    home = env.get("HOME", "~")  # guesses: no official Linux build path is documented
    return ["/opt/AnycubicSlicerNext", "/usr/lib/AnycubicSlicerNext", "/usr/share/AnycubicSlicerNext",
            posixpath.join(home, "AnycubicSlicerNext"), posixpath.join(home, ".local", "share", "AnycubicSlicerNext")]


def _files(paths):
    seen = 0
    for path in paths:
        if os.path.isfile(path):
            yield path
        elif os.path.isdir(path):
            base = path.rstrip(os.sep).count(os.sep)
            for folder, dirs, names in os.walk(path):  # followlinks=False: symlinked folders are skipped
                if folder.count(os.sep) - base > MAX_DEPTH:
                    raise CertError("%s is nested deeper than %d folders; point to the slicer's library folder"
                                    % (path, MAX_DEPTH))
                dirs.sort()
                seen += len(names)
                if seen > MAX_FILES:
                    raise CertError("more than %d files under %s; point to the slicer's library folder"
                                    % (MAX_FILES, path))
                for name in sorted(names):
                    if os.path.splitext(name)[1].lower() in SCAN_EXT:
                        yield os.path.join(folder, name)


def _chunks(path):
    """The file in CHUNK pieces, each starting OVERLAP bytes before the previous one ended."""
    with open(path, "rb") as f:
        tail = b""
        while True:
            data = f.read(CHUNK)
            if not data:
                return
            yield tail + data
            tail = (tail + data)[-OVERLAP:]


def _normalize(block):
    """One form for a PEM block found in a binary, whatever its line endings (LF, CRLF, CR, CR CR LF, blank
    lines): header, base64 body in 64-character lines, footer, LF. OpenSSL refuses a block with blank lines in
    its body, so the block is rebuilt rather than only converted; equal blocks also become equal keys here."""
    text = block.decode("ascii")
    head_end = text.index("-----", 5) + 5           # end of "-----BEGIN <label>-----"
    foot_start = text.rindex("-----END")
    body = "".join(text[head_end:foot_start].split())
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "\n".join([text[:head_end], *lines, text[foot_start:].strip()]) + "\n"


def _scan(paths):
    cert_found, key_found, scanned = {}, {}, 0
    for path in _files(paths):
        try:
            if os.path.getsize(path) > MAX_SIZE:
                continue
            for data in _chunks(path):
                for m in CERT_RE.finditer(data):
                    cert_found.setdefault(_normalize(m.group(0)), path)
                for m in KEY_RE.finditer(data):
                    key_found.setdefault(_normalize(m.group(0)), path)
        except OSError:
            continue
        scanned += 1
    return cert_found, key_found, scanned


def _is_anycubic(pem):
    body = "".join(pem.strip().splitlines()[1:-1])
    try:
        return EXPECTED_CN in base64.b64decode(body)
    except ValueError:
        return False


def _client_context():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # SECLEVEL=0: the slicer's key/signature may be below newer OpenSSL default security levels.
    ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


@contextlib.contextmanager
def _private_dir(workdir):
    """A fresh 0700 folder for the candidates, removed afterwards with the files written in it."""
    if workdir is None:
        with tempfile.TemporaryDirectory(prefix="kobracontrol-") as tmp:
            yield tmp
        return
    tmp = os.path.join(workdir, "match-" + secrets.token_hex(4))  # never a denied component name
    os.mkdir(tmp, 0o700)
    try:
        yield tmp
    finally:
        for name in os.listdir(tmp):
            os.remove(os.path.join(tmp, name))
        os.rmdir(tmp)


def _match(cert_pems, key_pems, workdir=None):
    """First (cert, key) pair OpenSSL accepts together; load_cert_chain raises on a mismatch."""
    with _private_dir(workdir) as tmp:
        written = []
        for i, pem in enumerate(cert_pems + key_pems):
            path = os.path.join(tmp, "%d.pem" % i)
            with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
                f.write(pem)
            written.append(path)
        cert_paths, key_paths = written[:len(cert_pems)], written[len(cert_pems):]
        for ci, cp in enumerate(cert_paths):
            for ki, kp in enumerate(key_paths):
                try:
                    _client_context().load_cert_chain(cp, kp)
                except ssl.SSLError:
                    continue
                return cert_pems[ci], key_pems[ki]
    return None


def find(paths, workdir=None):
    """Scan files/folders for the AnycubicSlicer certificate and its private key -> Found.
    workdir: an existing folder the candidates may be written to for matching (see the module doc)."""
    paths = list(paths)
    cert_found, key_found, scanned = _scan(paths)
    if not scanned:
        raise CertError("no slicer files to scan in: %s" % ", ".join(paths))
    counts = "%d certificates, %d keys" % (len(cert_found), len(key_found))
    candidates = [pem for pem in cert_found if _is_anycubic(pem)]
    if not candidates:
        raise CertError("no AnycubicSlicer client certificate found (%s in %d files)" % (counts, scanned))
    pair = _match(candidates, list(key_found), workdir)
    if not pair:
        raise CertError("AnycubicSlicer certificate found but no matching private key (%s)" % counts)
    return Found(pair[0], pair[1], cert_found[pair[0]], key_found[pair[1]])


def grant_targets():
    """default_locations() as OrcaSlicer tree grants: realpath + "/*", plus the given form when it differs."""
    out = []
    for folder in default_locations():
        for form in (os.path.realpath(folder), folder):
            target = form.rstrip("/\\") + "/*"
            if target not in out:
                out.append(target)
    return out


def paths(folder):
    return os.path.join(folder, CERT_FILE), os.path.join(folder, KEY_FILE)


def bundled():
    """The AnycubicSlicer certificate and key shipped next to this module (committed into the repo and
    carried in the wheel), or None when absent. This is Anycubic's shared client identity, the same for
    every Anycubic Slicer Next install; it is not the user's own secret. Used as a fallback so the plugin
    works without the local Find certificate step."""
    cert_path, key_path = paths(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(cert_path) and os.path.isfile(key_path):
        return cert_path, key_path
    return None


def _write_private(path, text):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)  # an existing file keeps its old mode through O_CREAT: tighten it first
    except OSError:
        os.close(fd)
        raise
    with open(fd, "w", encoding="ascii") as f:
        f.write(text)


def save(folder, cert_pem, key_pem):
    out = paths(folder)
    try:
        os.makedirs(folder, 0o700, exist_ok=True)
        os.chmod(folder, 0o700)  # makedirs leaves an existing folder as it was
        for path, text in zip(out, (cert_pem, key_pem)):
            _write_private(path, text)
    except OSError as e:
        raise CertError("cannot save the client certificate in %s (%s)" % (folder, e.strerror or e)) from None
    return out


def load(folder):
    try:
        result = []
        for path in paths(folder):
            with open(path, encoding="ascii") as f:
                result.append(f.read())
        return tuple(result)
    except OSError:
        raise CertError("no saved Anycubic Slicer client certificate in %s" % folder) from None


def context(cert_path, key_path):
    """TLS client context for the printer broker. The printer presents a self-signed certificate,
    so the server is not verified; the client identity is what the broker checks."""
    ctx = _client_context()
    try:
        ctx.load_cert_chain(cert_path, key_path)
    except (ssl.SSLError, OSError) as e:
        raise CertError("cannot load the client certificate and key (%s)" % (getattr(e, "reason", None) or type(e).__name__)) from None
    return ctx


class Pins:
    """The certificate each printer address presented last time (SHA-256 hex), in a JSON file. The printer's
    certificate is self-signed and is never verified (see SECURITY.md); this only notices when it changes.
    check() never refuses anything: it remembers the new fingerprint and returns the old one so the caller
    can warn. A file that cannot be read starts over; a write that fails raises OSError."""

    def __init__(self, path):
        self.path, self._lock = path, threading.Lock()

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        printers = data.get("printers") if isinstance(data, dict) else None
        return {k: v for k, v in printers.items() if isinstance(v, str)} if isinstance(printers, dict) else {}

    def check(self, key, fingerprint):
        """None when `fingerprint` is the one remembered for `key` or the first one seen; else the old one."""
        with self._lock:
            known = self._read()
            previous = known.get(key)
            if previous == fingerprint:
                return None
            known[key] = fingerprint
            os.makedirs(os.path.dirname(self.path) or ".", 0o700, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"printers": known}, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
            return previous
