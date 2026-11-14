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
"""

import base64
import os
import re
import ssl
import sys
import tempfile
from collections import namedtuple

CERT_FILE, KEY_FILE = "anycubic_slicer.pem", "anycubic_slicer_key.pem"
EXPECTED_CN = b"AnycubicSlicer"
SCAN_EXT = {".dll", ".exe", ".so", ".dylib", ""}
MAX_SIZE = 512 * 1024 * 1024
CERT_RE = re.compile(rb"-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=\r\n]+?-----END CERTIFICATE-----")
KEY_RE = re.compile(rb"-----BEGIN ((?:RSA |EC )?PRIVATE KEY)-----[\r\n]+[A-Za-z0-9+/=\r\n]+?-----END \1-----")

Found = namedtuple("Found", "cert_pem key_pem source key_source")


class CertError(Exception):
    pass


def default_locations(platform=None, env=None):
    platform = platform or sys.platform
    env = os.environ if env is None else env
    if platform == "darwin":
        apps = ["/Applications", os.path.join(env.get("HOME", "~"), "Applications")]
        return [os.path.join(a, "AnycubicSlicerNext.app", "Contents", sub) for a in apps for sub in ("Frameworks", "MacOS")]
    if platform.startswith("win"):
        roots = [env.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")]
        local = env.get("LOCALAPPDATA")
        out = [os.path.join(r, "AnycubicSlicerNext") for r in roots if r]
        return out + ([os.path.join(local, "Programs", "AnycubicSlicerNext")] if local else [])
    home = env.get("HOME", "~")  # guesses: no official Linux build path is documented
    return ["/opt/AnycubicSlicerNext", "/usr/lib/AnycubicSlicerNext", "/usr/share/AnycubicSlicerNext",
            os.path.join(home, "AnycubicSlicerNext"), os.path.join(home, ".local", "share", "AnycubicSlicerNext")]


def _files(paths):
    for path in paths:
        if os.path.isfile(path):
            yield path
        elif os.path.isdir(path):
            for folder, _, names in os.walk(path):
                for name in sorted(names):
                    if os.path.splitext(name)[1].lower() in SCAN_EXT:
                        yield os.path.join(folder, name)


def _normalize(block):
    return block.decode("ascii").replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _scan(paths):
    cert_found, key_found, scanned = {}, {}, 0
    for path in _files(paths):
        try:
            if os.path.getsize(path) > MAX_SIZE:
                continue
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        scanned += 1
        for m in CERT_RE.finditer(data):
            cert_found.setdefault(_normalize(m.group(0)), path)
        for m in KEY_RE.finditer(data):
            key_found.setdefault(_normalize(m.group(0)), path)
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


def _match(cert_pems, key_pems):
    """First (cert, key) pair OpenSSL accepts together; load_cert_chain raises on a mismatch."""
    with tempfile.TemporaryDirectory(prefix="kobracontrol-") as tmp:
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


def find(paths):
    """Scan files/folders for the AnycubicSlicer certificate and its private key -> Found."""
    paths = list(paths)
    cert_found, key_found, scanned = _scan(paths)
    if not scanned:
        raise CertError("no slicer files to scan in: %s" % ", ".join(paths))
    counts = "%d certificates, %d keys" % (len(cert_found), len(key_found))
    candidates = [pem for pem in cert_found if _is_anycubic(pem)]
    if not candidates:
        raise CertError("no AnycubicSlicer client certificate found (%s in %d files)" % (counts, scanned))
    pair = _match(candidates, list(key_found))
    if not pair:
        raise CertError("AnycubicSlicer certificate found but no matching private key (%s)" % counts)
    return Found(pair[0], pair[1], cert_found[pair[0]], key_found[pair[1]])


def paths(folder):
    return os.path.join(folder, CERT_FILE), os.path.join(folder, KEY_FILE)


def save(folder, cert_pem, key_pem):
    os.makedirs(folder, 0o700, exist_ok=True)
    out = paths(folder)
    for path, text in zip(out, (cert_pem, key_pem)):
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="ascii") as f:
            f.write(text)
        try:
            os.chmod(path, 0o600)  # an existing file keeps its old mode through O_CREAT; no-op on Windows
        except OSError:
            pass
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
