"""Anycubic Cloud, opt-in (Settings > Anycubic Cloud): for printers without a LAN mode (the Kobra 2 series) and for
anyone who keeps LAN mode off. Free of the `orca` module.

  Account          the signed-in account: tokens in cloud.json in the storage folder (0600, never logged), the signed
                   HTTP API, the cloud MQTT login.
  CloudConnection  one cloud printer, with the surface service.py uses on connection.Connection: status from the
                   account's MQTT reports and a slow REST poll, `printer` a CloudPrinter.
  CloudPrinter     what jobs.py and service.py call on kobra.Printer: upload, print, pause, resume and stop are REST
                   orders, each after a fresh look at the printer and its job. Nothing else is sent: no heat, move,
                   feed or printer setting goes over the cloud.

Ported from two MIT-licensed projects; their copyright and permission notices are in NOTICE.md:
  OrcaSlicer plugin "OrcaCubic" (https://github.com/cathome1/OrcaCubic), Copyright (c) 2026 cathome1: the request
    signature (orcacubic/auth.py) and the MQTT login with RSA PKCS#1 v1.5 done with pow() (orcacubic/mqtt_client.py).
  OrcaSlicer plugin "anycubic-plugin" (https://github.com/Bob-41/anycubic-plugin), Copyright (c) 2026 Anycubic Cloud
    Print Contributors: the token exchange, the token found in Anycubic Slicer Next's logs, the broker's CA with
    verified TLS, the upload (lock, PUT, claim, unlock), the order ids, and the look at the printer and its active job
    right before every order (plugin/plugin.py, mqtt_auth_protocol.md).
Neither G-code rewriting (OrcaCubic) nor a fall-back to "the first online printer" is taken: the G-code goes as sliced,
and only the printer the user chose is ever used.

Nothing here talks to Anycubic until the user turns the cloud on and signs in. The API, the broker and the S3 upload
hosts are the only ones contacted."""

import base64
import dataclasses
import glob
import hashlib
import http.client
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import uuid

import certs
import connection
import kobra
import profiles
from i18n import lazy, tr

HOST_PREFIX = "cloud:"          # Target.host of a cloud printer: "cloud:<printer id>"
API_HOST, API_ROOT = "cloud-universe.anycubic.com", "/p/p/workbench/api"
MQTT_HOST, MQTT_PORT = "mqtt-universe.anycubic.com", 8883
# The S3 hosts upload URLs point to (Bob-41's permission list); OrcaSlicer is asked about them when the cloud is on.
UPLOAD_HOSTS = ("workbentch.s3.us-east-2.amazonaws.com", "workbench.s3.us-east-2.amazonaws.com")
# Anycubic Slicer Next's request-signing pair: static strings in its libcloud_sdk_cpp, the same in every copy (also in
# OrcaCubic, Bob-41 and hass-anycubic_cloud). Anycubic can change them, and then every third-party client stops.
APP_ID, APP_SECRET = "f9b3528877c94d5c9c5af32245db46ef", "0cf75926606049a3937f56b0373b99fb"
APP_VERSION, DEVICE_TYPE = "2.0.0.3", "pcf"
# The broker's public key: the MQTT password is the token encrypted with it (both references carry the same bytes).
BROKER_KEY = ("MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAn2Kpx1AzT2Df1kf1MImTdqCgq5JDGdFTMw/Mx4TN6+oYUQyVUcSs8j+EPFla"
              "Cja7t9nXoNLrfS26PwdDzJEt+wVDCdoWvNxuie+0w2Zk8lpRHn76z+waTONO3OLaneWe0xINNMtAqmuV0w2HSoNmvrLqJ7iO8moNeUO92fHU"
              "AnwkrNCtKeWpB80DLdVJBZRUeiL7KKH+7ud343KcfWLpC5cj9RyZYVCEShwY9/tPN40Jg+jk43JiFbu5ruAMPuUWn5Iy/6ENnyBKk21uYxED"
              "3y/OKNVJyl8+fZMgZriCzIP2YsU52O7nbr2iWytA1a1ZTIyiUPpGYQSYY8PSV7vwxwIDAQAB")
TOKEN_FILE = "cloud.json"
ACTIVE = {1, 4, 5, 6, 7}        # project print_status of a job that has not ended (Bob-41: ACTIVE_PROJECT_STATES)
PRINTING = 1                    # ... the only one pause and resume apply to; paused = pause != 0
ORDERS = {"print": 1, "pause": 2, "resume": 3, "stop": 4}
VERB = {"pause": "pausing", "resume": "resuming", "stop": "stopping"}
NO_FILE_TRIES, NO_FILE_WAIT = 3, 3.0   # a fresh upload can answer "No file found" for a few seconds (Bob-41)
REST_EVERY = 15.0               # s between REST status polls; MQTT reports arrive in between
MAX_BODY = 4 << 20
LOG_FILES = 5                   # newest Anycubic Slicer Next logs searched for a sign-in
JWT = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
LOG_TOKEN = re.compile(r"id_token=(eyJhbGciOiJSUzI1NiIs[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)")

NOT_SIGNED_IN = lazy("not signed in to Anycubic Cloud: sign in under Settings > Anycubic Cloud")
NOT_ON_CLOUD = lazy("this is not available over Anycubic Cloud; nothing was sent")
OFFLINE = lazy("%s is offline on Anycubic Cloud")
NOT_ON_ACCOUNT = lazy("printer %s is not on this Anycubic account any more")
BUSY = lazy("%s is already printing; nothing was sent")
NO_JOB = lazy("there is no print running on %s; nothing was sent")

# Anycubic's root CA ("AC Root CA", valid until 2123; Bob-41 tls/ca.pem): the broker's certificate is verified.
CA_PEM = """-----BEGIN CERTIFICATE-----
MIIECDCCAvCgAwIBAgIBATANBgkqhkiG9w0BAQsFADCBmzELMAkGA1UEBhMCQ04x
EjAQBgNVBAgMCUd1YW5nZG9uZzERMA8GA1UEBwwIU2hlbnpoZW4xETAPBgNVBAoM
CEFueWN1YmljMREwDwYDVQQLDAhBbnljdWJpYzETMBEGA1UEAwwKQUMgUm9vdCBD
QTEqMCgGCSqGSIb3DQEJARYbYW55Y3ViaWNfY2xvdWRAYW55Y3ViaWMuY29tMCAX
DTIzMDcxMjA2NDgwNVoYDzIxMjMwNzEzMDY0ODA1WjCBmzELMAkGA1UEBhMCQ04x
EjAQBgNVBAgMCUd1YW5nZG9uZzERMA8GA1UEBwwIU2hlbnpoZW4xETAPBgNVBAoM
CEFueWN1YmljMREwDwYDVQQLDAhBbnljdWJpYzETMBEGA1UEAwwKQUMgUm9vdCBD
QTEqMCgGCSqGSIb3DQEJARYbYW55Y3ViaWNfY2xvdWRAYW55Y3ViaWMuY29tMIIB
IjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAn2Kpx1AzT2Df1kf1MImTdqCg
q5JDGdFTMw/Mx4TN6+oYUQyVUcSs8j+EPFlaCja7t9nXoNLrfS26PwdDzJEt+wVD
CdoWvNxuie+0w2Zk8lpRHn76z+waTONO3OLaneWe0xINNMtAqmuV0w2HSoNmvrLq
J7iO8moNeUO92fHUAnwkrNCtKeWpB80DLdVJBZRUeiL7KKH+7ud343KcfWLpC5cj
9RyZYVCEShwY9/tPN40Jg+jk43JiFbu5ruAMPuUWn5Iy/6ENnyBKk21uYxED3y/O
KNVJyl8+fZMgZriCzIP2YsU52O7nbr2iWytA1a1ZTIyiUPpGYQSYY8PSV7vwxwID
AQABo1MwUTAdBgNVHQ4EFgQUJZA6qRREX697ta0fYDWzSrYKxyIwHwYDVR0jBBgw
FoAUJZA6qRREX697ta0fYDWzSrYKxyIwDwYDVR0TAQH/BAUwAwEB/zANBgkqhkiG
9w0BAQsFAAOCAQEALPq1pVM6KjsJJx2Dk12JEN3AdYjj6oBKTBOYm1GvuuY+zN/a
ZTCuNADJQHg/UUypx5ZygJudIkDcLLmYPv99C+kNacbPIl6BqUQUEo4qNuxHqvCT
d48HMO6dngGY98pjBzHfHUH25LLAb0I/BqIx++XgZK/u7hea7xOkcBi11gpSplnj
Bzf3h7gl9iGr+FEAWmZAKVyNXZ9tMsf5AEJVgfaDG6UXyPKeMhO6zVC58quArL5r
LXVIJknBKbtnQ9n3qqExNyBWsvkQxgD+o07rZzdehnExZ5+LjeF6ktyP0e7BgFqW
mqBFWhzKUShFFw+6tjt9piDil2agec2b2JEEuA==
-----END CERTIFICATE-----
"""


class CloudError(kobra.KobraError):
    pass


def printer_id(host):
    """'cloud:123' -> '123'; '' for a LAN address."""
    return host[len(HOST_PREFIX):] if isinstance(host, str) and host.startswith(HOST_PREFIX) else ""


# signing, tokens ----------------------------------------------------------------------------------------------------
def signature(ts, nonce, version=APP_VERSION):
    """XX-Signature: md5(id + ts + version + secret + nonce + id), upper-case hex as Anycubic Slicer Next sends
    (Bob-41 verified 27 of 27 captures; OrcaCubic's lower-case one works too, the server ignores the case)."""
    return hashlib.md5((APP_ID + ts + version + APP_SECRET + nonce + APP_ID).encode()).hexdigest().upper()


def signed_headers(token="", ts=None, nonce=None):
    ts = ts or str(int(time.time() * 1000))
    nonce = nonce or str(uuid.uuid4())
    out = {"Accept": "*/*", "Content-Type": "application/json; charset=UTF-8", "XX-Device-Type": DEVICE_TYPE,
           "XX-IS-CN": "0", "XX-LANGUAGE": "US", "XX-Nonce": nonce, "XX-Signature": signature(ts, nonce),
           "XX-Timestamp": ts, "XX-Version": APP_VERSION}
    if token:
        out["XX-Token"] = token
    return out


def jwt_claims(token):
    """The (unverified) payload of a JWT, {} when it is not one."""
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError, TypeError, AttributeError):
        return {}


def extract_token(text):
    """The JWT in pasted text (a bare token, a URL with id_token=..., quotes), else ""."""
    match = JWT.search(str(text or ""))
    return match.group(0) if match else ""


def slicer_log_dirs():
    home, appdata = os.path.expanduser("~"), os.environ.get("APPDATA", "")
    out = [os.path.join(home, "Library", "Application Support", name, "log") for name in ("AnycubicSlicerNext", "Anycubic Slicer Next")]
    out += [os.path.join(home, ".config", name, "log") for name in ("AnycubicSlicerNext", "Anycubic Slicer Next")]
    if appdata:
        out += [os.path.join(appdata, name, "log") for name in ("AnycubicSlicerNext", "Anycubic Slicer Next")]
    return out


def find_slicer_token(dirs=None, now=None):
    """The newest unexpired Anycubic account sign-in Anycubic Slicer Next wrote to its logs (the id_token of its sign-in
    page), else "". Read only; the token is never logged. Slicer Next 2.0.0.3 logs it; newer builds may not."""
    now = time.time() if now is None else now
    best, best_exp = "", 0
    for folder in dirs if dirs is not None else slicer_log_dirs():
        try:
            files = sorted(glob.glob(os.path.join(folder, "*.log")), key=os.path.getmtime, reverse=True)[:LOG_FILES]
        except OSError:
            continue
        for path in files:
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except PermissionError:
                raise   # OrcaSlicer refused the read: the caller says so instead of "nothing found"
            except OSError:
                continue
            for token in LOG_TOKEN.findall(text):
                exp = int(jwt_claims(token).get("exp") or 0)
                if exp > now and exp > best_exp:
                    best, best_exp = token, exp
    return best


# MQTT login --------------------------------------------------------------------------------------------------------
def _der_int(der, i):
    """(int, next index) of the DER INTEGER at der[i]."""
    if der[i] != 0x02:
        raise ValueError("not an INTEGER")
    n, i = der[i + 1], i + 2
    if n & 0x80:
        size, n = n & 0x7F, int.from_bytes(der[i:i + (n & 0x7F)], "big")
        i += size
    return int.from_bytes(der[i:i + n], "big"), i + n


def rsa_public_key(b64):
    """(n, e) of a 2048-bit RSA SubjectPublicKeyInfo (base64 DER)."""
    der = base64.b64decode(b64)
    i = der.index(b"\x03\x82\x01\x0f\x00") + 5   # BIT STRING of the RSAPublicKey
    i += 4 if der[i + 1] == 0x82 else 3          # its SEQUENCE header
    n, i = _der_int(der, i)
    e, _ = _der_int(der, i)
    return n, e


def rsa_encrypt(message, key=None, random=os.urandom):
    """RSAES-PKCS1-v1_5 with the broker key, stdlib only (OrcaCubic's pow() form)."""
    n, e = key or rsa_public_key(BROKER_KEY)
    k = (n.bit_length() + 7) // 8
    pad = k - len(message) - 3
    if pad < 8:
        raise ValueError("message too long for the key")
    ps = bytearray()
    while len(ps) < pad:
        ps += bytes(b for b in random(pad) if b)
    em = b"\x00\x02" + bytes(ps[:pad]) + b"\x00" + message
    return pow(int.from_bytes(em, "big"), e, n).to_bytes(k, "big")


def mqtt_login(token, email, encrypt=rsa_encrypt):
    """(client_id, username, password) for the broker, from the workbench token (Bob-41 mqtt_auth_protocol.md §2)."""
    digest = hashlib.md5(token.encode()).hexdigest()
    password = base64.b64encode(encrypt(token.encode())).decode("ascii")
    client_id = "pcf_" + digest
    check = hashlib.md5((client_id + password + client_id).encode()).hexdigest()
    return client_id, "user|pcf|%s|%s" % (email, check), password


def tls_context():
    """TLS to the broker, verified against Anycubic's root CA and the broker's name. SECLEVEL=0: the broker's
    certificate is SHA-1 signed, which OpenSSL leaves out of the handshake at its default level (Bob-41)."""
    ctx = ssl.create_default_context(cadata=CA_PEM)
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=0")
    except ssl.SSLError:
        pass
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


# token store -------------------------------------------------------------------------------------------------------
class TokenStore:
    """cloud.json in the plugin's storage folder, readable by the user only: {"access_token" (the Anycubic account
    sign-in, about a year), "token" (the workbench token made from it), "email", "pc_id"}."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        return {k: data[k] for k in ("access_token", "token", "email", "pc_id") if isinstance(data.get(k), str)} \
            if isinstance(data, dict) else {}

    def save(self, data):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, 0o700, exist_ok=True)
        certs._write_private(self.path, json.dumps(data))   # a fresh 0600 file moved into place, no chmod (certs.py)

    def clear(self):
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


# HTTP ----------------------------------------------------------------------------------------------------------------
def https(method, host, path, headers, body=None, timeout=30, size=None, progress=None, cancelled=None):
    """One HTTPS request through http.client (audited by host, like the printer's); body: bytes, or a readable file
    streamed in 64 KiB pieces when size is given. -> (status, body bytes, at most MAX_BODY)."""
    conn = http.client.HTTPSConnection(host, 443, timeout=timeout, context=ssl.create_default_context())
    try:
        if size is None:
            conn.request(method, path, body=body, headers=headers)
        else:
            conn.putrequest(method, path, skip_accept_encoding=True)
            for k, v in {**headers, "Content-Length": str(size)}.items():
                conn.putheader(k, v)
            conn.endheaders()
            sent = 0
            while sent < size:
                if cancelled and cancelled():
                    raise kobra.Cancelled(tr("upload cancelled"))
                chunk = body.read(min(65536, size - sent))
                if not chunk:
                    raise CloudError(tr("the file ended before its size"))
                conn.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, size)
        resp = conn.getresponse()
        return resp.status, resp.read(MAX_BODY)
    except (OSError, http.client.HTTPException) as e:
        if isinstance(e, PermissionError):
            raise CloudError(tr("OrcaSlicer denied network access to %s (grant it in the plugin's permissions)") % host,
                             code="denied") from None
        raise CloudError(tr("Anycubic Cloud not reachable (%s)") % e, code="unreachable") from None
    finally:
        conn.close()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _obj(v):
    """A dict, also from a JSON string (the cloud sends some fields as strings); {} otherwise."""
    if isinstance(v, str) and v[:1] == "{":
        try:
            v = json.loads(v)
        except ValueError:
            return {}
    return v if isinstance(v, dict) else {}


class Account:
    """The signed-in Anycubic account. Thread-safe; tokens never leave this object except to Anycubic."""

    def __init__(self, path, log=print, http=https, sleep=time.sleep):
        self.store, self.log, self.http, self.sleep = TokenStore(path), log, http, sleep
        self._lock, self._order = threading.Lock(), threading.Lock()
        self._data = self.store.load()

    # sign-in
    @property
    def signed_in(self):
        return bool(self._data.get("token"))

    @property
    def email(self):
        return self._data.get("email", "")

    def sign_in(self, access_token):
        """Exchange an Anycubic account sign-in (RS256 JWT: pasted, or found in Slicer Next's logs) for a workbench
        token (POST /v3/public/loginWithAccessToken) and keep both. -> the account's e-mail address."""
        token = extract_token(access_token)
        if not token:
            raise CloudError(tr("that is not an Anycubic sign-in token (it starts with eyJ and has two dots)"))
        pc_id = self._data.get("pc_id") or uuid.uuid4().hex.upper()
        answer = self.call("POST", "/v3/public/loginWithAccessToken",
                           {"device_type": DEVICE_TYPE, "access_token": token, "pc_id": pc_id}, signed_in=False)
        data = _obj(answer.get("data"))
        if not isinstance(data.get("token"), str) or not data["token"]:
            raise CloudError(tr("Anycubic Cloud accepted the sign-in but returned no session"))
        email = _obj(data.get("user")).get("user_email") or jwt_claims(token).get("email") or ""
        with self._lock:
            self._data = {"access_token": token, "token": data["token"], "email": str(email), "pc_id": pc_id}
            self.store.save(self._data)
        return self.email

    def sign_out(self):
        with self._lock:
            self._data = {}
            self.store.clear()

    def renew(self):
        """The broker refused the workbench token (a later sign-in elsewhere rotates it): make a new one from the
        stored sign-in. False when there is none or it is refused too."""
        access = self._data.get("access_token")
        if not access:
            return False
        try:
            self.sign_in(access)
            return True
        except kobra.KobraError as e:
            self.log("kobracontrol: Anycubic Cloud sign-in not renewed (%s)" % e)
            return False

    # API
    def call(self, method, path, body=None, signed_in=True, timeout=30):
        """A signed API call -> its JSON answer; CloudError unless code is 1."""
        token = self._data.get("token", "") if signed_in else ""
        if signed_in and not token:
            raise CloudError(tr(NOT_SIGNED_IN), code="signed_out")
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        status, raw = self.http(method, API_HOST, API_ROOT + path, signed_headers(token), payload, timeout)
        try:
            answer = json.loads(raw)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            raise CloudError(tr("Anycubic Cloud answered HTTP %d without JSON") % status)
        if answer.get("code") != 1:
            raise CloudError(tr("Anycubic Cloud refused it (code %s): %s") % (answer.get("code"), answer.get("msg") or ""),
                             code=answer.get("code"))
        return answer

    def printers(self):
        """The account's FDM printers: [{"id", "key", "name", "machine_type", "device_status", "is_printing", ...}]."""
        body = {"page": 1, "limit": 1000, "is_farm": 0, "query_status": 0, "printer_id": 0, "machine_type": 0,
                "bulk_id": 0, "query_project": 0, "sort_by": 0, "type": "FDM", "label_name": None, "printer_ids": [],
                "ams_info": {"use_ams": False, "padding2": 0, "padding1": 0, "padding": 0, "ams_box_mapping": []}}
        data = self.call("POST", "/work/printer/getPrinters", body).get("data")
        return [p for p in data if isinstance(p, dict)] if isinstance(data, list) else []

    def printer(self, pid):
        return next((p for p in self.printers() if str(p.get("id")) == str(pid)), None)

    def active_project(self, pid):
        """The newest job on this printer that has not ended, None when there is none."""
        data = self.call("GET", "/work/project/getProjects?page=1&limit=20").get("data")
        for p in data if isinstance(data, list) else []:
            if isinstance(p, dict) and str(p.get("printer_id")) == str(pid) and _int(p.get("print_status")) in ACTIVE:
                return p
        return None

    def upload(self, name, source, size, progress=None, cancelled=None):
        """The G-code into the account's cloud storage, unchanged -> its file id. Lock, PUT to the presigned URL,
        claim, then always unlock (deleting the stored object when nothing was claimed). Temporary file: it does
        not fill the user's cloud storage (OrcaCubic's is_temp_file)."""
        lock = _obj(self.call("POST", "/v2/cloud_storage/lockStorageSpace",
                              {"size": int(size), "name": name, "is_temp_file": 1}).get("data"))
        url = lock.get("preSignUrl") or lock.get("url")
        if not lock.get("id") or not isinstance(url, str) or not url.startswith("https://"):
            raise CloudError(tr("Anycubic Cloud gave no upload address"))
        file_id = None
        try:
            parts = urllib.parse.urlsplit(url)
            opened = open(source, "rb") if isinstance(source, str) else None
            try:
                status, raw = self.http("PUT", parts.hostname, parts.path + ("?" + parts.query if parts.query else ""),
                                        {"Content-Type": "application/octet-stream"}, opened or source, 600, size,
                                        progress, cancelled)
            finally:
                if opened:
                    opened.close()
            if status not in (200, 201):
                raise CloudError(tr("the cloud storage refused the upload (HTTP %d)") % status)
            file_id = _int(_obj(self.call("POST", "/v2/profile/newUploadFile",
                                          {"user_lock_space_id": lock["id"]}).get("data")).get("id"))
            if not file_id:
                raise CloudError(tr("Anycubic Cloud returned no file id for the upload"))
        finally:
            try:
                self.call("POST", "/v2/cloud_storage/unlockStorageSpace", {"id": lock["id"], "is_delete_cos": 0 if file_id else 1})
            except kobra.KobraError as e:
                self.log("kobracontrol: Anycubic Cloud storage not unlocked (%s)" % e)
        return file_id

    def _fresh(self, pid):
        """The printer as the cloud sees it now; CloudError when it is gone or offline."""
        entry = self.printer(pid)
        if entry is None:
            raise CloudError(tr(NOT_ON_ACCOUNT) % pid)
        if _int(entry.get("device_status")) != 1:
            raise CloudError(tr(OFFLINE) % (entry.get("name") or pid))
        return entry

    def start_print(self, pid, file_id):
        """Order 1 for an uploaded file, after a fresh look: the printer is online and runs no job (one that started
        while the file uploaded is never interrupted). Only "No file found" is retried."""
        with self._order:
            entry = self._fresh(pid)
            if self.active_project(pid) is not None:
                raise CloudError(tr(BUSY) % (entry.get("name") or pid))
            body = {"order_id": ORDERS["print"], "printer_id": int(pid), "project_id": 0, "ams_info": None, "settings": None,
                    "data": {"filetype": 0, "file_key": "", "file_name": "", "file_id": int(file_id), "hollow_param": None,
                             "task_settings": {"ai_detect": 0, "camera_timelapse": 0}, "is_delete_file": 0, "matrix": "",
                             "project_type": 1, "punching_param": None, "slice_param": None, "slice_size": None,
                             "template_id": 0}}
            for attempt in range(NO_FILE_TRIES):
                try:
                    return self.call("POST", "/work/operation/sendOrder", body)
                except CloudError as e:
                    if "No file found" not in str(e) or attempt == NO_FILE_TRIES - 1:
                        raise
                self.sleep(NO_FILE_WAIT)

    def control(self, pid, action):
        """Pause, resume or stop (orders 2, 3, 4) the printer's active job, re-read right before sending: a job that
        already ended, or one in the other state, is never ordered about. One order at a time."""
        with self._order:
            entry = self._fresh(pid)
            name = entry.get("name") or pid
            project = self.active_project(pid)
            if project is None or _int(project.get("id")) is None:
                raise CloudError(tr(NO_JOB) % name)
            paused = _int(project.get("pause")) not in (None, 0)
            printing = _int(project.get("print_status")) == PRINTING
            if action == "pause" and (paused or not printing) or action == "resume" and not (paused and printing):
                raise CloudError(tr("%s is not possible now: the job on %s is %s; nothing was sent")
                                 % (tr(VERB[action]), name, tr("paused") if paused else tr("printing")))
            return self.call("POST", "/work/operation/sendOrder", {"order_id": ORDERS[action], "printer_id": int(pid),
                             "project_id": _int(project["id"]), "data": None, "ams_info": None, "settings": None})

    def mqtt_credentials(self, entry):
        """(kobra.Credentials for the broker, MQTT client id) of one printer entry."""
        if not self.signed_in:
            raise CloudError(tr(NOT_SIGNED_IN), code="signed_out")
        client_id, username, password = mqtt_login(self._data["token"], self.email)
        return kobra.Credentials(MQTT_HOST, username, password, str(entry.get("key") or ""),
                                 str(entry.get("machine_type") or ""), str(entry.get("name") or "")), client_id


def info_report(entry, project):
    """A printers list entry and its active job as the info/report kobra.State already folds. Field names: Bob-41's
    capture of a Kobra 2 Pro (getPrinters `parameter`, `version`; getProjects `progress`, `remain_time`, `pause`);
    remain_time in minutes as on the LAN: UNVERIFIED."""
    temps = _obj(entry.get("parameter"))
    data = {"printerName": str(entry.get("name") or ""), "version": str(_obj(entry.get("version")).get("firmware_version") or ""),
            "temp": {k: temps[k] for k in ("curr_nozzle_temp", "curr_hotbed_temp", "target_nozzle_temp", "target_hotbed_temp")
                     if isinstance(temps.get(k), (int, float))},
            "state": "busy" if project else "free", "project": None}
    if project:
        data["project"] = {"state": "paused" if _int(project.get("pause")) else "printing",
                           "taskid": str(project.get("id") or ""), "progress": _int(project.get("progress")) or 0,
                           "remain_time": _int(project.get("remain_time")) or 0,
                           "filename": str(project.get("gcode_name") or project.get("name") or "")}
    return {"type": "info", "action": "report", "state": "done", "code": 200, "data": data}


class CloudPrinter:
    """The kobra.Printer surface over the cloud. Status arrives on the account's MQTT session (`inner`, read only:
    nothing is published on it); every command is a REST order. Anything else raises NOT_ON_CLOUD."""

    def __init__(self, conn, inner):
        self.conn, self.inner, self._files = conn, inner, {}

    connected = property(lambda self: self.inner.connected)
    last_rx = property(lambda self: self.inner.last_rx)
    tls_fingerprint = property(lambda self: "")

    def connect(self, wait=True):
        return self.inner.connect(wait)

    def close(self):
        self.inner.close()

    def query_info(self):
        self.conn.poll_now()

    def upload(self, filename, source, upload_url, size=None, progress=None, cancelled=None):
        self._files[filename] = self.conn.account.upload(filename, source, size, progress, cancelled)
        return {"state": "done", "code": 200}

    def start_print(self, payload, timeout=15):
        file_id = self._files.get(payload.get("filename"))
        if not file_id:
            raise CloudError(tr("%s was not uploaded to Anycubic Cloud in this session; nothing was sent") % payload.get("filename"))
        self.conn.account.start_print(self.conn.printer_id, file_id)
        self.conn.poll_now()
        return {"state": "done", "code": 200, "action": "start"}

    def _control(self, action):
        self.conn.account.control(self.conn.printer_id, action)
        self.conn.poll_now()
        return {"state": "done", "code": 200}

    def pause_print(self, taskid="-1"):
        return self._control("pause")

    def resume_print(self, taskid="-1"):
        return self._control("resume")

    def stop_print(self, taskid="-1"):
        return self._control("stop")

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def refused(*args, **kwargs):
            raise CloudError(tr(NOT_ON_CLOUD))
        return refused


class CloudConnection(connection.Connection):
    """One cloud printer ("cloud:<id>") with connection.Connection's loop, listeners and backoff: the printer comes
    from the account's printer list, MQTT from the account's token (renewed once when the broker refuses it), and the
    poll is the REST printer list and job list every REST_EVERY seconds instead of MQTT queries."""

    def __init__(self, host, account, log=print, tls=tls_context, mqtt_host=MQTT_HOST, mqtt_port=MQTT_PORT):
        super().__init__(host, tls, log, mqtt_port=mqtt_port, fetch=None)
        self.account, self.printer_id, self.mqtt_host = account, printer_id(host), mqtt_host
        self._rest_at = 0.0

    def view(self):
        return {**self.state.view(), "transport": "cloud", "upload_url": "cloud"}

    def _open(self):
        old, self.printer, inner = self.printer, None, None
        if old:
            old.close()
        self.http_failed = True
        try:
            entry = self.account._fresh(self.printer_id)
            creds, client_id = self.account.mqtt_credentials(entry)
            creds = dataclasses.replace(creds, ip=self.mqtt_host)
            profile = profiles.get(creds.mode_id)
            self.state.set_model(creds.mode_id, profile["name"] if profile else creds.model)
            self.http_failed = False
            inner = kobra.Printer(creds, ssl_context=self.tls(), mqtt_port=self.mqtt_port, on_report=self._report,
                                  on_disconnect=self._dropped)
            inner.client_id = client_id
            inner.connect()
        except (kobra.KobraError, OSError) as e:
            if inner:
                inner.close()
            if not self.http_failed and getattr(e, "code", None) in (4, 5) and self.account.renew():
                self.log("kobracontrol: Anycubic Cloud session renewed; connecting again")
            self._fail(str(e), False)
            return False
        if self._stop.is_set():
            inner.close()
            return False
        self.printer = CloudPrinter(self, inner)
        self._poll(initial=True)
        self.state.connected = True
        self._opened_at = time.monotonic()
        self.error, self.no_certificate = "", False
        self._connected.set()
        self.log("kobracontrol: connected to %s over Anycubic Cloud" % self.host)
        self._notify()
        return True

    def poll_now(self):
        self._rest_at = 0.0
        self._poll()

    def _poll(self, initial=False):
        if time.monotonic() < self._rest_at:
            return
        self._rest_at = time.monotonic() + REST_EVERY
        try:
            entry = self.account._fresh(self.printer_id)
            project = self.account.active_project(self.printer_id)
        except kobra.KobraError as e:
            self.log("kobracontrol: %s: Anycubic Cloud status not read (%s)" % (self.host, e))
            if isinstance(e, CloudError) and self.printer and not initial:
                self.error = str(e)
                self.printer.close()   # offline or gone: the loop reconnects with its backoff
            return
        self.state.apply("info/report", info_report(entry, project))
        self._notify()

    def _note_certificate(self, fingerprint):
        self.server_cert = None   # verified against Anycubic's CA: nothing to pin
