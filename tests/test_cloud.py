"""Anycubic Cloud (cloud.py) against a fake API and FakeKobra as the broker. Nothing here reaches Anycubic: every
HTTP call goes to FakeApi, MQTT to 127.0.0.1. Payload shapes follow Bob-41's captures (mqtt_auth_protocol.md).
Run: python3 -m unittest tests/test_cloud.py -v"""

import base64
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import cloud  # noqa: E402
import kobra  # noqa: E402
import service  # noqa: E402
import settings  # noqa: E402
from fake_kobra import FakeKobra  # noqa: E402
from test_service import FakeCamera, FakeSpoolman, wait  # noqa: E402


def jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).rstrip(b"=").decode()  # noqa: E731
    return "%s.%s.sig_%s" % (enc({"alg": "RS256", "kid": "ac_app_crt", "typ": "JWT"}), enc(claims), "x" * 40)


ACCESS = jwt({"email": "someone@example.com", "exp": 4102444800})
WORKBENCH = "eyJhbGciOiJIUzUxMiJ9.eyJ1c2VyX2lkIjoxfQ.workbench"
PRINTER = {"id": 52074, "key": "1e22021da407a52c640c277f6af031e1", "name": "Shop K2", "machine_type": 20021,
           "device_status": 1, "is_printing": 1, "parameter": {"curr_hotbed_temp": 57, "curr_nozzle_temp": 195},
           "version": {"firmware_version": "3.1.5"}}


class FakeApi:
    """The cloud API and S3, by path. `answers[path]` = dict or callable(body) -> dict; `calls` records them."""

    def __init__(self):
        self.calls, self.puts = [], []
        self.projects, self.printers = [], [dict(PRINTER)]
        self.put_status = 200
        self.send_order = lambda body: {"code": 1, "msg": "ok", "data": {}}
        self.answers = {
            "/v3/public/loginWithAccessToken": {"code": 1, "data": {"token": WORKBENCH, "user": {"user_email": "someone@example.com"}}},
            "/work/printer/getPrinters": lambda body: {"code": 1, "data": self.printers},
            "/work/project/getProjects?page=1&limit=20": lambda body: {"code": 1, "data": self.projects},
            "/v2/cloud_storage/lockStorageSpace": {"code": 1, "data": {"id": 77, "preSignUrl": "https://workbentch.s3.us-east-2.amazonaws.com/u/f.gcode?X-Amz-Signature=abc"}},
            "/v2/profile/newUploadFile": {"code": 1, "data": {"id": 101639520}},
            "/v2/cloud_storage/unlockStorageSpace": {"code": 1, "data": None},
            "/work/operation/sendOrder": lambda body: self.send_order(body),
        }

    def __call__(self, method, host, path, headers, body=None, timeout=30, size=None, progress=None, cancelled=None):
        if host != cloud.API_HOST:
            data = body.read(size) if size is not None else body
            self.puts.append({"host": host, "path": path, "data": data})
            return self.put_status, b""
        path = path[len(cloud.API_ROOT):]
        parsed = json.loads(body) if body else None
        self.calls.append({"method": method, "path": path, "body": parsed, "headers": headers})
        answer = self.answers.get(path, {"code": 0, "msg": "unknown"})
        answer = answer(parsed) if callable(answer) else answer
        return 200, json.dumps(answer).encode()

    def paths(self):
        return [c["path"] for c in self.calls]


class Basics(unittest.TestCase):
    def test_signature(self):
        ts, nonce = "1792954956906", "d32ea01e-0000-4000-8000-0000e63a5b02"
        expected = __import__("hashlib").md5((cloud.APP_ID + ts + "2.0.0.3" + cloud.APP_SECRET + nonce + cloud.APP_ID).encode()).hexdigest().upper()
        self.assertEqual(cloud.signature(ts, nonce), expected)
        h = cloud.signed_headers("tok", ts, nonce)
        self.assertEqual((h["XX-Signature"], h["XX-Token"], h["XX-Device-Type"], h["XX-Version"]), (expected, "tok", "pcf", "2.0.0.3"))
        self.assertNotIn("XX-Token", cloud.signed_headers())

    def test_extract_token(self):
        self.assertEqual(cloud.extract_token(' "https://x/?id_token=%s&a=1" ' % ACCESS), ACCESS)
        self.assertEqual(cloud.extract_token("not a token"), "")

    def test_mqtt_login_shape(self):
        client_id, username, password = cloud.mqtt_login("TOKEN", "a@b.c", encrypt=lambda m: b"E" * 256)
        md5 = __import__("hashlib").md5
        self.assertEqual(client_id, "pcf_" + md5(b"TOKEN").hexdigest())
        self.assertEqual(password, base64.b64encode(b"E" * 256).decode())
        self.assertEqual(username, "user|pcf|a@b.c|" + md5((client_id + password + client_id).encode()).hexdigest())

    def test_broker_key_parses(self):
        n, e = cloud.rsa_public_key(cloud.BROKER_KEY)
        self.assertEqual((n.bit_length(), e), (2048, 65537))
        self.assertEqual(len(cloud.rsa_encrypt(b"x" * 200)), 256)

    @unittest.skipUnless(shutil.which("openssl"), "needs the openssl CLI")
    def test_rsa_encrypt_decrypts_with_openssl(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        key, pub = os.path.join(d, "k.pem"), os.path.join(d, "p.der")
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", key], check=True, capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", key, "-pubout", "-outform", "DER", "-out", pub], check=True, capture_output=True)
        secret = WORKBENCH.encode()
        with open(pub, "rb") as f:
            blob = cloud.rsa_encrypt(secret, cloud.rsa_public_key(base64.b64encode(f.read())))
        out = subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", key, "-pkeyopt", "rsa_padding_mode:pkcs1"],
                             input=blob, check=True, capture_output=True).stdout
        self.assertEqual(out, secret)

    def test_tls_context_verifies(self):
        ctx = cloud.tls_context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, __import__("ssl").CERT_REQUIRED)
        self.assertTrue(any("AC Root CA" in str(c.get("subject")) for c in ctx.get_ca_certs()))

    def test_token_from_slicer_logs(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        old, newer, expired = (jwt({"exp": 4102444800 - 10}), jwt({"exp": 4102444800}), jwt({"exp": 1000}))
        for name, token in (("a.log", old), ("b.log", newer), ("c.log", expired)):
            with open(os.path.join(d, name), "w") as f:
                f.write("UrlAllModel:https://x/?pcid=1&id_token=%s\nmore\n" % token)
        self.assertTrue(newer.startswith("eyJhbGciOiJSUzI1NiIs"))
        self.assertEqual(cloud.find_slicer_token([d, os.path.join(d, "missing")], now=2000), newer)
        self.assertEqual(cloud.find_slicer_token([os.path.join(d, "missing")]), "")

    def test_token_store_is_private(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        store = cloud.TokenStore(os.path.join(d, "sub", "cloud.json"))
        store.save({"token": "t", "email": "e"})
        self.assertEqual(store.load(), {"token": "t", "email": "e"})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(os.stat(store.path).st_mode), 0o600)
        store.clear()
        self.assertEqual(store.load(), {})


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.api, self.logs = FakeApi(), []
        self.account = cloud.Account(os.path.join(self.dir, "cloud.json"), self.logs.append, http=self.api, sleep=lambda s: None)
        self.account.sign_in(ACCESS)

    def test_sign_in_keeps_tokens_and_never_logs_them(self):
        self.assertEqual(self.account.email, "someone@example.com")
        login = self.api.calls[0]
        self.assertEqual(login["body"]["access_token"], ACCESS)
        self.assertEqual(login["body"]["device_type"], "pcf")
        self.assertNotIn("XX-Token", login["headers"])
        again = cloud.Account(os.path.join(self.dir, "cloud.json"), http=self.api)
        self.assertTrue(again.signed_in)
        self.account.printers()
        self.assertEqual(self.api.calls[-1]["headers"]["XX-Token"], WORKBENCH)
        self.assertFalse([line for line in self.logs if WORKBENCH in line or ACCESS in line])
        self.account.sign_out()
        self.assertFalse(os.path.exists(os.path.join(self.dir, "cloud.json")))
        with self.assertRaises(cloud.CloudError):
            self.account.printers()

    def test_refused_sign_in(self):
        self.api.answers["/v3/public/loginWithAccessToken"] = {"code": 0, "msg": "token invalid"}
        with self.assertRaises(cloud.CloudError) as e:
            cloud.Account(os.path.join(self.dir, "x.json"), http=self.api).sign_in(ACCESS)
        self.assertIn("token invalid", str(e.exception))
        with self.assertRaises(cloud.CloudError):
            self.account.sign_in("hello")

    def test_upload_streams_unchanged_and_unlocks(self):
        data = b"; generated by OrcaSlicer\nG28\n" * 1000
        file_id = self.account.upload("a.gcode", io.BytesIO(data), len(data))
        self.assertEqual(file_id, 101639520)
        self.assertEqual(self.api.puts[0]["data"], data)   # the G-code as sliced
        self.assertEqual(self.api.puts[0]["host"], "workbentch.s3.us-east-2.amazonaws.com")
        lock = next(c for c in self.api.calls if c["path"].endswith("lockStorageSpace"))
        self.assertEqual(lock["body"], {"size": len(data), "name": "a.gcode", "is_temp_file": 1})
        self.assertEqual(self.api.calls[-1]["body"], {"id": 77, "is_delete_cos": 0})

    def test_failed_put_deletes_the_lock(self):
        self.api.put_status = 403
        with self.assertRaises(cloud.CloudError):
            self.account.upload("a.gcode", io.BytesIO(b"G28\n"), 4)
        self.assertEqual(self.api.calls[-1]["body"], {"id": 77, "is_delete_cos": 1})
        self.assertNotIn("/v2/profile/newUploadFile", self.api.paths())

    def test_start_print_checks_first(self):
        self.api.projects = [{"id": 9, "printer_id": 52074, "print_status": 1, "pause": 0}]
        with self.assertRaises(cloud.CloudError) as e:
            self.account.start_print(52074, 5)
        self.assertIn("already printing", str(e.exception))
        self.api.projects = []
        self.api.printers[0]["device_status"] = 2
        with self.assertRaises(cloud.CloudError):
            self.account.start_print(52074, 5)
        self.assertNotIn("/work/operation/sendOrder", self.api.paths())
        self.api.printers[0]["device_status"] = 1
        tries = []
        self.api.send_order = lambda b: tries.append(b) or ({"code": 0, "msg": "No file found"} if len(tries) < 2 else {"code": 1})
        self.account.start_print(52074, 5)
        self.assertEqual(len(tries), 2)
        self.assertEqual((tries[0]["order_id"], tries[0]["printer_id"], tries[0]["data"]["file_id"]), (1, 52074, 5))

    def test_another_printer_is_never_used(self):
        self.api.printers = [dict(PRINTER, id=1, name="Other")]
        with self.assertRaises(cloud.CloudError) as e:
            self.account.start_print(52074, 5)
        self.assertIn("not on this Anycubic account", str(e.exception))

    def test_controls_reread_the_job(self):
        orders = []
        self.api.send_order = lambda b: orders.append(b) or {"code": 1}
        with self.assertRaises(cloud.CloudError):
            self.account.control(52074, "stop")            # no job: nothing sent
        self.api.projects = [{"id": 9, "printer_id": 1, "print_status": 1, "pause": 0},
                             {"id": 8, "printer_id": 52074, "print_status": 1, "pause": 1}]
        with self.assertRaises(cloud.CloudError):
            self.account.control(52074, "pause")           # already paused
        self.account.control(52074, "resume")
        self.account.control(52074, "stop")
        self.assertEqual([(o["order_id"], o["project_id"]) for o in orders], [(3, 8), (4, 8)])

    def test_info_report(self):
        report = cloud.info_report(PRINTER, {"id": 8, "progress": 40, "remain_time": 30, "pause": 1, "gcode_name": "a.gcode"})
        s = kobra.State()
        s.connected = True
        s.apply("info/report", report)
        v = s.view()
        self.assertEqual((v["state"], v["progress"], v["filename"], v["printer_name"], v["firmware"]),
                         ("paused", 40, "a.gcode", "Shop K2", "3.1.5"))
        s.apply("info/report", cloud.info_report(PRINTER, None))
        self.assertEqual(s.view()["state"], "idle")


class ServiceCommands(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.svc = service.Service(lambda m: None, lambda m: None, cert_dir=self.dir, tls=lambda: None,
                                   camera_factory=FakeCamera, relay_factory=FakeCamera, spoolman_factory=FakeSpoolman)
        self.addCleanup(self.svc.close)
        self.api = FakeApi()

    def test_off_by_default(self):
        self.assertEqual(settings.DEFAULTS["cloud_enabled"], False)
        self.assertFalse(self.svc.cmd_cloud_state()["enabled"])
        with self.assertRaises(kobra.KobraError):
            self.svc.cmd_cloud_printers()
        with self.assertRaises(kobra.KobraError):
            self.svc.connection("cloud:1")      # no cloud connection while the cloud is off

    def test_settings_validation(self):
        self.assertEqual(settings.invalid({"cloud_printer": "52074", "cloud_enabled": True}), [])
        self.assertEqual(settings.invalid({"cloud_printer": "../x"}), ["cloud_printer"])
        self.assertEqual(settings.invalid({"cloud_printer": 5}), ["cloud_printer"])

    def test_sign_in_from_slicer_logs_and_list(self):
        self.svc.cloud = cloud.Account(os.path.join(self.dir, "cloud.json"), http=self.api)
        with mock.patch.object(cloud, "find_slicer_token", return_value=""):
            with self.assertRaises(kobra.KobraError) as e:
                self.svc.cmd_cloud_find()
            self.assertIn("No Anycubic sign-in was found", str(e.exception))
        with mock.patch.object(cloud, "find_slicer_token", side_effect=PermissionError):
            with self.assertRaises(kobra.KobraError) as e:
                self.svc.cmd_cloud_find()
            self.assertIn("did not allow reading", str(e.exception))
        with mock.patch.object(cloud, "find_slicer_token", return_value=ACCESS):
            self.assertEqual(self.svc.cmd_cloud_find(), {"email": "someone@example.com"})
        self.assertEqual(self.svc.cmd_cloud_printers(), [{"id": "52074", "name": "Shop K2", "model": "Anycubic Kobra 2 Pro",
                                                          "online": True, "printing": False}])
        self.assertTrue(self.svc.cmd_cloud_state()["signed_in"])
        self.svc.cmd_cloud_sign_out()
        self.assertFalse(self.svc.cmd_cloud_state()["signed_in"])


class CloudConnectionTests(unittest.TestCase):
    """CloudConnection against FakeKobra as the broker (plain TCP, fixed login)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        self.fake.mode_id, self.fake.device_id = "20021", PRINTER["key"]
        self.fake.username, self.fake.password = "user|pcf|someone@example.com|x", "pw"
        patcher = mock.patch.object(cloud, "mqtt_login", lambda token, email: ("pcf_x", self.fake.username, self.fake.password))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = FakeApi()
        self.account = cloud.Account(os.path.join(self.dir, "cloud.json"), http=self.api, sleep=lambda s: None)
        self.account.sign_in(ACCESS)
        self.published = []
        self.svc = service.Service(self.published.append, lambda m: None, cert_dir=self.dir, tls=lambda: None,
                                   camera_factory=FakeCamera, relay_factory=FakeCamera, spoolman_factory=FakeSpoolman)
        self.addCleanup(self.svc.close)
        self.svc.cloud = self.account
        self.svc.cloud_connection = lambda host: cloud.CloudConnection(host, self.account, lambda m: None, tls=lambda: None,
                                                                       mqtt_host=self.fake.host, mqtt_port=self.fake.mqtt_port)
        self.svc.set_target(service.Target("cloud:52074"))
        self.conn = self.svc.connections["cloud:52074"]
        wait(lambda: self.conn.connected)

    def run_cmd(self, cmd, **args):
        rid = "r%s%f" % (cmd, time.monotonic())
        self.svc.submit(rid, cmd, args)
        return wait(lambda: next((m for m in self.published if m.get("type") == "reply" and m.get("id") == rid), None))

    def test_status_and_capabilities(self):
        self.assertEqual(self.fake.client_ids[-1], "pcf_x")
        self.assertIn("anycubic/anycubicCloud/v1/printer/public/20021/%s/#" % PRINTER["key"], self.fake.subscriptions)
        data, _ = service.status_data(self.conn.view())
        self.assertEqual((data["transport"], data["model"], data["printer_name"], data["state"]),
                         ("cloud", "Anycubic Kobra 2 Pro", "Shop K2", "idle"))
        self.assertEqual(data["upload_url"], "")
        self.assertEqual(data["limits"], {"nozzle_max": 260, "bed_max": 110})
        self.assertFalse(data["can"]["heat"] or data["can"]["move"] or data["can"]["feed"])
        self.assertTrue(data["can"]["print"])
        self.assertEqual(self.fake.requests, [])   # nothing published on the cloud broker
        self.fake.report("print/report", {"type": "print", "action": "start", "state": "printing",
                                          "data": {"taskid": "8", "filename": "a.gcode", "progress": 12}})
        wait(lambda: self.conn.view()["progress"] == 12)

    def test_heat_and_light_refused_without_sending(self):
        self.assertIn("not available over Anycubic Cloud", self.run_cmd("set_temp", nozzle=200)["error"])
        self.assertIn("not available over Anycubic Cloud", self.run_cmd("set_light", on=True)["error"])
        self.assertEqual(self.fake.requests, [])

    def test_print_job_uploads_then_orders(self):
        orders = []
        self.api.send_order = lambda b: orders.append(b) or {"code": 1}
        path = os.path.join(self.dir, "plate.gcode")
        with open(path, "wb") as f:
            f.write(b"G28\nG1 X10\n")
        self.svc.print_job("cloud:52074", path, name="plate.gcode")
        self.assertEqual(self.api.puts[0]["data"], b"G28\nG1 X10\n")
        self.assertEqual([(o["order_id"], o["data"]["file_id"]) for o in orders], [(1, 101639520)])

    def test_pause_is_an_order_after_a_fresh_look(self):
        orders = []
        self.api.send_order = lambda b: orders.append(b) or {"code": 1}
        self.api.projects = [{"id": 8, "printer_id": 52074, "print_status": 1, "pause": 0, "progress": 5}]
        self.conn.poll_now()
        wait(lambda: self.conn.view()["state"] == "printing")
        self.assertTrue(self.run_cmd("pause")["result"])
        self.assertEqual([(o["order_id"], o["project_id"]) for o in orders], [(2, 8)])

    def test_stale_token_is_renewed(self):
        logins = len([c for c in self.api.calls if c["path"] == "/v3/public/loginWithAccessToken"])
        self.fake.connack_code = 5
        self.conn.printer.close()
        wait(lambda: len([c for c in self.api.calls if c["path"] == "/v3/public/loginWithAccessToken"]) > logins)

    def test_offline_printer_is_an_error(self):
        self.api.printers[0]["device_status"] = 2
        self.conn.poll_now()
        wait(lambda: "offline on Anycubic Cloud" in self.conn.error)


if __name__ == "__main__":
    unittest.main()
