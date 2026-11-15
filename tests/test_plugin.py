"""plugin.py with a fake `orca` module, against FakeKobra on 127.0.0.1. Run: python3 -m unittest tests/test_plugin.py -v"""

import json
import os
import sys
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import audit_guard  # noqa: E402
import fake_orca  # noqa: E402
from fake_kobra import FakeKobra, make_tls_files  # noqa: E402
import test_service  # noqa: E402
from test_service import ACE0, FakeCamera, make_3mf, wait  # noqa: E402

orca = fake_orca.install_orca(preset={"name": "Anycubic Kobra X 0.4 nozzle", "printer_model": "Anycubic Kobra X",
                                      "print_host": "http://127.0.0.1:18910"},
                              filament_names=["Generic PLA @System"],
                              filament_meta={"Generic PLA @System": {"filament_id": "OGFL99"}})
import certs  # noqa: E402
import plugin  # noqa: E402
import service  # noqa: E402

pa = orca.printer_agent


class Base(unittest.TestCase):
    state = "free"

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        f = self.fake
        f.reply("info", "query", {"printerName": "KX", "version": "2.1.0", "project": {"state": self.state, "taskid": "9"},
                                  "urls": {"fileUploadurl": f.upload_url, "rtspUrl": "rtsp://127.0.0.1:1/live"}})
        f.reply("print", "query", {"taskid": "9"}, state=self.state)
        f.reply("multiColorBox", "getInfo", {"multi_color_box": [ACE0]})
        f.print_start = "ok"
        self.tmp = tempfile.mkdtemp()
        plugin._storage_dir, plugin._store = self.tmp, None
        self.published = []
        plugin._service = service.Service(self.published.append, lambda m: None, cert_dir=self.tmp, tls=lambda: None,
                                          http_port=f.http_port, mqtt_port=f.mqtt_port, camera_factory=FakeCamera)
        self.addCleanup(self.close_service)
        self.agent = plugin.KobraAgent()
        self.events = {"connect": [], "message": [], "ssdp": [], "queued": 0}
        self.agent.set_on_local_connect_fn(lambda *a: self.events["connect"].append(a))
        self.agent.set_on_local_message_fn(lambda dev, msg: self.events["message"].append(json.loads(msg)))
        self.agent.set_on_ssdp_msg_fn(lambda msg: self.events["ssdp"].append(json.loads(msg)))
        self.agent.set_queue_on_main_fn(self.queue)
        self.addCleanup(self.agent.disconnect_printer)

    def close_service(self):
        svc, plugin._service = plugin._service, None
        if svc:
            svc.close()

    def queue(self, task):
        self.events["queued"] += 1
        task()

    def connect(self):
        params = pa.PrinterConnectionParams(dev_id="127.0.0.1", host=self.fake.host, password="1234")
        started = time.monotonic()
        self.assertEqual(self.agent.connect_printer(params), 0)
        self.assertLess(time.monotonic() - started, 0.5)   # UI thread: returns at once
        wait(lambda: self.events["connect"])
        return wait(lambda: next((m for m in self.events["message"] if m.get("print", {}).get("ams", {}).get("ams")), None))

    def sent(self, type_, action):
        return [r["msg"] for r in self.fake.requests if isinstance(r["msg"], dict)
                and (r["msg"].get("type"), r["msg"].get("action")) == (type_, action)]


class Registration(unittest.TestCase):
    def test_capabilities_and_permissions(self):
        orca.registered.clear()
        orca.permissions.clear()
        plugin._storage_dir, plugin._store = tempfile.mkdtemp(), None
        plugin.KobraControl().register_capabilities()
        self.assertEqual(orca.registered, [plugin.KobraAgent, plugin.KobraControlPage, plugin.CheckConnection,
                                           plugin.FindCertificate])
        perms = orca.permissions[-1]
        self.assertTrue(perms["threading"])
        self.assertEqual(perms["network"], ["http://127.0.0.1"])
        self.assertEqual(perms["fs_read"], certs.grant_targets() + plugin.job_read_grants())
        self.assertNotIn("fs_readwrite", perms)   # L7: the plugin writes no downloads

    def test_agent_info(self):
        info = plugin.KobraAgent().get_agent_info()
        self.assertEqual((info.id, info.version), ("kobracontrol", plugin.VERSION))
        self.assertEqual(plugin.KobraAgent().request_bind_ticket(), (0, ""))
        self.assertEqual(plugin.KobraAgent().get_filament_sync_mode(), pa.FilamentSyncMode.Subscription)

    def test_host_of(self):
        for raw, want in (("http://192.168.1.5:18910/x", "192.168.1.5"), ("192.168.1.5", "192.168.1.5"),
                          (' "https://kx.lan" ', "kx.lan"), ("", "")):
            self.assertEqual(plugin.host_of(raw), want)


class Agent(Base):
    def test_connect_pushes_status_with_trays(self):
        msg = self.connect()["print"]
        self.assertEqual(self.events["connect"][0], (0, "127.0.0.1", "0"))
        self.assertGreater(self.events["queued"], 0)
        self.assertEqual(msg["gcode_state"], "IDLE")
        self.assertTrue(msg["sdcard"])
        tray = msg["ams"]["ams"][0]["tray"][0]
        self.assertEqual((tray["tray_type"], tray["tray_info_idx"]), ("PLA", "OGFL99"))
        self.assertEqual(msg["ams"]["ams"][0]["tray"][1]["tray_info_idx"], "")   # no Generic PETG preset loaded

    def test_status_push_survives_a_failing_sample(self):
        """One status sample that raises must not end the Device tab's pusher thread for the rest of the session."""
        self.connect()
        real, calls = plugin.bambu.push_status, []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("bad sample")
            return real(*a, **kw)
        plugin.bambu.push_status = flaky
        self.addCleanup(setattr, plugin.bambu, "push_status", real)
        self.events["message"].clear()
        self.agent._dirty.set()
        wait(lambda: calls)
        self.agent._dirty.set()
        wait(lambda: self.events["message"])
        self.assertTrue(self.agent._pusher.is_alive())

    def test_device_tab_unload_with_nothing_loaded_is_refused(self):
        self.connect()
        unload = {"print": {"command": "ams_change_filament", "ams_id": 255, "slot_id": 255, "target": 255}}
        self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps(unload), 0, 0), plugin.ERR_INVALID_HANDLE)
        time.sleep(0.2)
        self.assertFalse(self.sent("multiColorBox", "feedFilament"))

    def test_start_camera_with_no_printer(self):
        """command_start_camera never starts a capture thread for a session that has just gone."""
        self.connect()
        conn = plugin._service.connections["127.0.0.1"]
        errors = []
        old = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_value)
        self.addCleanup(setattr, threading, "excepthook", old)

        class Swapped:
            connected, printer, host = True, None, "127.0.0.1"

            def view(self):
                return conn.view()
        plugin._service.connections["127.0.0.1"] = Swapped()
        self.addCleanup(plugin._service.connections.__setitem__, "127.0.0.1", conn)
        self.assertEqual(self.agent.command_start_camera("127.0.0.1"), plugin.ERR_CONNECT)
        time.sleep(0.2)
        self.assertEqual(errors, [])

    def test_print_a_file_on_the_printer(self):
        """start_sdcard_print: the file already on the printer, with both print options and a finished stage."""
        self.connect()
        self.fake.reply("file", "listLocal", {"records": [{"filename": "a.gcode", "size": 1, "timestamp": 1}]}, code=200)
        stages = []
        params = pa.PrintParams(dst_file="/a.gcode", task_bed_leveling=True, task_vibration_cali=True)
        self.assertEqual(self.agent.start_sdcard_print(params, lambda *a: stages.append(a), lambda: False), 0)
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual(start["filename"], "a.gcode")
        self.assertEqual((start["task_settings"]["auto_leveling"], start["task_settings"]["vibration_compensation"]), (1, 1))
        self.assertEqual(stages[-1][0], plugin.STAGE_FINISHED)

    def test_switching_printer_releases_the_old_connection(self):
        """connect_printer for another address closes the session to the previous one (disconnect_printer does)."""
        self.connect()
        params = pa.PrinterConnectionParams(dev_id="other", host="127.0.0.2", password="")
        self.assertEqual(self.agent.connect_printer(params), 0)
        wait(lambda: "127.0.0.1" not in plugin._service.connections)
        self.assertIn("127.0.0.2", plugin._service.connections)

    def test_discovery_announces_the_printer(self):
        self.connect()
        self.assertTrue(self.agent.start_discovery(True, False))
        self.assertEqual(self.events["ssdp"][-1]["dev_ip"], "127.0.0.1")
        detect = pa.DetectResult()
        self.assertEqual(self.agent.bind_detect("127.0.0.1", "", detect), 0)
        self.assertEqual((detect.dev_id, detect.dev_name, detect.version), ("127.0.0.1", "KX", "2.1.0"))

    def test_replies_and_codes(self):
        self.connect()
        send = self.agent.send_message_to_printer
        self.assertEqual(send("127.0.0.1", json.dumps({"info": {"command": "get_version"}}), 0, 0), 0)
        self.assertEqual(self.events["message"][-1]["info"]["module"][0]["sw_ver"], "2.1.0")
        self.assertEqual(send("127.0.0.1", json.dumps({"system": {"command": "get_access_code"}}), 0, 0), 0)
        self.assertEqual(self.events["message"][-1]["system"]["access_code"], "1234")
        self.assertEqual(send("127.0.0.1", json.dumps({"print": {"command": "skip_objects", "obj_list": [1]}}), 0, 0), -7010)
        self.assertEqual(send("127.0.0.1", "{bad", 0, 0), -19)
        self.assertEqual(send("127.0.0.1", json.dumps({"print": {"command": "pause"}}), 0, 0), -1)   # idle
        time.sleep(0.2)
        self.assertFalse(self.sent("print", "pause"))

    def test_gcode_commands(self):
        self.connect()
        cmd = {"print": {"command": "gcode_line", "param": "M104 S210\n", "sequence_id": "5"}}
        self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps(cmd), 0, 0), 0)
        self.assertEqual(wait(lambda: self.sent("tempature", "set"))[0]["data"]["target_nozzle_temp"], 210)
        reply = wait(lambda: next((m for m in self.events["message"] if m.get("print", {}).get("command") == "gcode_line"), None))
        self.assertEqual((reply["print"]["sequence_id"], reply["print"]["result"]), ("5", "success"))
        light = {"system": {"command": "ledctrl", "led_node": "chamber_light", "led_mode": "on"}}
        self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps(light), 0, 0), 0)
        wait(lambda: self.sent("light", "control"))
        setting = {"print": {"command": "ams_filament_setting", "ams_id": 0, "slot_id": 2, "tray_color": "112233FF",
                             "tray_type": "ABS"}}
        self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps(setting), 0, 0), 0)
        info = wait(lambda: self.sent("multiColorBox", "setInfo"))[0]["data"]["multi_color_box"][0]
        self.assertEqual((info["id"], info["slots"][0]["index"], info["slots"][0]["type"]), (0, 2, "ABS"))

    def test_verify_job_does_not_upload(self):
        self.connect()
        params = pa.PrintParams(project_name="verify_job", filename=make_3mf(self.tmp), dev_ip="127.0.0.1")
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, None, None, None), 0)
        self.assertEqual(self.fake.uploads, [])

    def test_send_uploads_only(self):
        self.connect()
        stages = []
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), plate_index=1)
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, lambda *a: stages.append(a), lambda: False, None), 0)
        self.assertEqual(self.fake.uploads[0]["filename"], "cube.gcode")
        self.assertEqual(stages[-1][0], plugin.STAGE_FINISHED)
        time.sleep(0.2)
        self.assertFalse(self.sent("print", "start"))

    def test_print_with_tray_mapping(self):
        self.connect()
        stages = []
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), plate_index=1, ams_mapping="[3, -1]",
                                ams_mapping_info=json.dumps([{"ams": 3, "sourceColor": "#00FF00", "filamentType": "PLA"},
                                                             {"ams": -1}]),
                                task_bed_leveling=True)
        self.assertEqual(self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False), 0)
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual([(m["paint_index"], m["ams_index"]) for m in start["ams_settings"]["ams_box_mapping"]], [(0, 3)])
        self.assertEqual(start["task_settings"]["auto_leveling"], 1)
        self.assertEqual([s[0] for s in stages][0], plugin.STAGE_CREATE)
        self.assertIn(plugin.STAGE_UPLOAD, [s[0] for s in stages])
        self.assertEqual(stages[-1][0], plugin.STAGE_FINISHED)

    def test_cancelled_print(self):
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        self.assertEqual(self.agent.start_local_print(params, None, lambda: True), plugin.ERR_CANCELED)
        self.assertEqual(self.fake.uploads, [])

    def test_camera_mode_follows_url_scheme(self):   # the real Kobra X: http://<ip>:18088/live/<token>
        self.connect()
        for url, mode in (("http://127.0.0.1:18088/live/tok", pa.CameraStreamMode.HTTP),
                          ("https://127.0.0.1/live", pa.CameraStreamMode.HTTPS),
                          ("rtsp://127.0.0.1/live", pa.CameraStreamMode.RTSP),
                          ("ftp://127.0.0.1/x", pa.CameraStreamMode.None_)):
            self.fake.report("info/report", {"type": "info", "action": "update", "state": "success",
                                             "data": {"urls": {"rtspUrl": url}}})
            wait(lambda: plugin._service.view_for(self.fake.host)["camera_url"] == url)
            self.assertEqual(self.agent.get_camera_stream_mode(), mode, url)

    def test_foreign_camera_host_is_not_handed_to_orca(self):   # M2
        self.connect()
        self.fake.report("info/report", {"type": "info", "action": "update", "state": "success",
                                         "data": {"urls": {"rtspUrl": "rtsp://203.0.113.9/live"}}})
        wait(lambda: plugin._service.view_for(self.fake.host)["camera_url"].startswith("rtsp://203"))
        self.assertEqual(self.agent.get_camera_url(), "")
        self.assertEqual(self.agent.get_camera_stream_mode(), pa.CameraStreamMode.None_)

    def test_camera(self):
        self.connect()
        self.assertEqual(self.agent.get_camera_stream_mode(), pa.CameraStreamMode.RTSP)
        self.assertEqual(self.agent.get_camera_url(), "rtsp://127.0.0.1:1/live")
        time.sleep(0.2)
        self.assertFalse(self.sent("video", "startCapture"))
        self.assertEqual(self.agent.command_start_camera("127.0.0.1"), 0)
        wait(lambda: self.sent("video", "startCapture"))

    def test_disconnect_is_fast(self):
        self.connect()
        started = time.monotonic()
        self.assertEqual(self.agent.disconnect_printer(), 0)
        self.assertLess(time.monotonic() - started, 0.5)


class AgentWhilePrinting(Base):
    state = "printing"

    def test_print_refused_and_error_reported(self):
        self.connect()
        stages = []
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        code = self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False)
        self.assertEqual(code, plugin.ERR_LP_PUBLISH)
        self.assertEqual(stages[-1][0], plugin.STAGE_ERROR)
        self.assertIn("printing", stages[-1][2])
        self.assertEqual(self.fake.uploads, [])

    def test_device_tab_jog_refused(self):
        self.connect()
        jog = {"print": {"command": "gcode_line", "param": "G91 \nG1 X10.0 F3000\nG90 \n"}}
        self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps(jog), 0, 0), -1)
        self.assertEqual(self.connect()["print"]["gcode_state"], "RUNNING")


class Page(Base):
    def page(self):
        page = plugin.KobraControlPage()
        page.posted = []
        return page

    def test_hello_connects_and_sends_config(self):
        page = self.page()
        page.on_message({"type": "hello", "id": 1})
        reply = wait(lambda: next((m for m in page.posted if m.get("type") == "reply" and m.get("id") == 1), None))
        self.assertEqual(reply["result"]["address"], "127.0.0.1")
        config = next(m for m in page.posted if m["type"] == "config")
        self.assertEqual(config["limits"], {"nozzle_max": 320, "bed_max": 120})
        self.assertEqual(config["certificate"], {"found": True, "source": "bundled"})   # the bundled certificate
        self.assertEqual(config["version"], plugin.VERSION)

    def test_only_retry_hello_asks_for_a_retry(self):
        """The page says hello on open and on selection changes; only its Retry button may cut the backoff short."""
        page = self.page()
        svc = plugin.service(page.post_message)
        with mock.patch.object(svc, "submit") as submit:
            page.on_message({"type": "hello", "id": 1})
            page.on_message({"type": "hello", "id": 2, "retry": True})
            page.on_message({"type": "hello", "id": 3, "retry": "yes"})
        self.assertEqual([c.args[1:3] for c in submit.call_args_list],
                         [("connect", {"retry": False}), ("connect", {"retry": True}), ("connect", {"retry": False})])

    def test_certificate_state_matches_the_one_in_use(self):
        """A saved pair that does not load is not used (connection.tls_from falls back to the bundled one), so the
        page must not call it "saved"."""
        folder = plugin.cert_dir()
        os.makedirs(folder, exist_ok=True)
        for path in certs.paths(folder):
            with open(path, "w") as f:
                f.write("not a pem")
        self.assertEqual(plugin.certificate_state(), {"found": True, "source": "bundled"})

    def test_hello_without_kobra_preset(self):
        preset = orca.host.preset_bundle().current_printer_preset()
        old = type(preset).name, type(preset).config_value
        type(preset).name = "Bambu Lab X1C"
        type(preset).config_value = lambda self, key: {"printer_model": "Bambu Lab X1 Carbon"}.get(key)
        try:
            page = self.page()
            page.on_message({"type": "hello", "id": 2})
            self.assertTrue(page.posted[-1]["no_target"])
            plugin.get_store().update({"host": "http://127.0.0.1:1234"})
            self.assertEqual(plugin.selected_host(), "127.0.0.1")   # the host setting overrides the preset
        finally:
            type(preset).name, type(preset).config_value = old

    def test_commands_and_settings(self):
        page = self.page()
        page.on_message({"type": "hello", "id": 1})
        wait(lambda: any(m.get("id") == 1 for m in page.posted))
        page.on_message({"type": "cmd", "id": 3, "cmd": "set_fan", "args": {"pct": 40},
                         "gen": plugin._service.generation})
        wait(lambda: self.sent("fan", "setSpeed"))
        page.on_message({"type": "save_settings", "id": 4, "settings": {"printer_name": "Lab KX", "bogus": 1}})
        self.assertTrue(page.posted[-1]["result"]["saved"])
        self.assertEqual(plugin.get_store().effective()["printer_name"], "Lab KX")
        page.on_message({"type": "ui_language", "value": "pt-BR"})
        self.assertEqual(plugin.get_store().effective()["ui_language"], "pt-BR")
        self.assertIn('"pref": "pt-BR"', page.get_ui())


class OneSession(Base):
    def test_agent_page_and_script_share_one_mqtt_session(self):
        self.connect()
        page = plugin.KobraControlPage()
        page.posted = []
        page.on_message({"type": "hello", "id": 1})
        wait(lambda: any(m.get("id") == 1 and "result" in m for m in page.posted))
        self.assertEqual(plugin.CheckConnection().execute().status, "success")
        params = pa.PrintParams(project_name="verify_job", filename=make_3mf(self.tmp))
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, None, None, None), 0)
        self.assertEqual(len(self.fake.client_ids), 1)
        self.assertEqual(len(self.fake.ctrl_calls), 1)
        self.assertEqual(len(plugin._service.connections), 1)


class Scripts(Base):
    def test_check_connection(self):
        result = plugin.CheckConnection().execute()
        self.assertEqual(result.status, "success")
        self.assertIn("KX at 127.0.0.1", result.message)

    def test_find_certificate_reports_nothing_found(self):
        empty = tempfile.mkdtemp()
        old = certs.default_locations
        certs.default_locations = lambda: [empty]
        try:
            result = plugin.FindCertificate().execute()
        finally:
            certs.default_locations = old
        self.assertEqual(result.status, "skipped")


if __name__ == "__main__":
    unittest.main()


class PushingNoop(Base):
    def test_pushing_start_and_stop_succeed(self):   # M7
        self.connect()
        for name in ("start", "stop"):
            self.assertEqual(self.agent.send_message_to_printer("127.0.0.1", json.dumps({"pushing": {"command": name}}),
                                                                0, 0), 0)


class UnloadCycles(Base):
    """M5: disable/enable never leaks a service or its threads; one capability unloading leaves the other's."""

    def test_cycles_return_to_baseline(self):
        self.close_service()
        plugin._service_options = {"tls": lambda: None, "http_port": self.fake.http_port,
                                   "mqtt_port": self.fake.mqtt_port, "camera_factory": FakeCamera}
        self.addCleanup(setattr, plugin, "_service_options", {})
        time.sleep(0.5)
        baseline = threading.active_count()
        for _ in range(3):
            page, agent = plugin.KobraControlPage(), plugin.KobraAgent()
            page.posted = []
            page.on_load()
            agent.on_load()
            agent.connect_printer(pa.PrinterConnectionParams(dev_id="127.0.0.1", host=self.fake.host))
            wait(lambda: plugin._service.connections[self.fake.host].connected)
            page.on_unload()
            self.assertIsNotNone(plugin._service)   # the agent still uses it
            self.assertTrue(plugin._service.connections[self.fake.host].connected)
            agent.disconnect_printer()
            agent.on_unload()
            self.assertIsNone(plugin._service)
            time.sleep(0.3)
            self.assertIsNone(plugin._service)   # the release thread did not create a new one
        wait(lambda: threading.active_count() <= baseline + 1, 10)


def run_off_main(fn):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("value", fn()), name="orca-job")
    t.start()
    t.join(30)
    return box.get("value")


class Guarded(Base):
    """C1-C3 under tests/audit_guard.py: OrcaSlicer's permission model for plugin threads."""

    def setUp(self):
        super().setUp()
        orca.permissions.clear()
        self.slicer = tempfile.mkdtemp(prefix="anycubic-")
        self.old_locations = plugin.certs.default_locations
        plugin.certs.default_locations = lambda: [self.slicer]
        self.addCleanup(setattr, plugin.certs, "default_locations", self.old_locations)
        plugin.KobraControl().register_capabilities()
        self.perms = orca.permissions[-1]
        audit_guard.enable(self.perms, self.tmp)
        self.addCleanup(audit_guard.disable)

    def ungranted_dir(self, prefix):
        """A folder no grant covers on any OS. Not under the system temp folder: on Windows OrcaSlicer's job
        folder is that temp folder itself (plugin.slicer_temp_root), so the plugin is granted all of it."""
        folder = tempfile.mkdtemp(prefix=prefix, dir=ROOT)
        self.addCleanup(shutil.rmtree, folder, True)
        root = os.path.realpath(plugin.slicer_temp_root())
        self.assertFalse(os.path.realpath(folder).startswith(root.rstrip(os.sep) + os.sep))
        return folder

    def job_dir(self):
        folder = os.path.join(plugin.slicer_temp_root(), "kobracontrol-test")
        os.makedirs(folder, exist_ok=True)
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_slicer_temp_root(self):
        if os.name != "nt":
            self.assertEqual(plugin.slicer_temp_root(), os.path.join(tempfile.gettempdir(), "orcaslicer_%d" % os.getuid()))
        self.assertIn(os.path.realpath(plugin.slicer_temp_root()) + "/*", self.perms["fs_read"])

    def test_print_from_orca_temp_dir(self):   # C1 + C2
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.job_dir()), ams_mapping="[0]")
        code = run_off_main(lambda: self.agent.start_local_print(params, None, lambda: False))
        self.assertEqual((code, audit_guard.denials()), (0, []))
        self.assertEqual(self.fake.uploads[0]["data"], test_service.GCODE)

    def test_send_from_orca_temp_dir(self):
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.job_dir()))
        self.assertEqual(run_off_main(lambda: self.agent.start_send_gcode_to_sdcard(params, None, lambda: False, None)), 0)
        self.assertEqual(audit_guard.denials(), [])

    def test_denied_read_is_reported_plainly(self):   # C1: never "not a zip"
        self.connect()
        stages = []
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.ungranted_dir("job-")), ams_mapping="[0]")
        code = run_off_main(lambda: self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False))
        self.assertNotEqual(code, 0)
        self.assertIn("did not let kobracontrol read the sliced file", stages[-1][2])
        self.assertIn("Plugins > Permissions", stages[-1][2])
        self.assertEqual(self.fake.uploads, [])

    def write_slicer(self):
        tls = make_tls_files(tempfile.mkdtemp(prefix="pems-"))
        with open(os.path.join(self.slicer, "libcloud_mqtt.dylib"), "wb") as f:
            for part in (tls.server_cert, tls.client_key, tls.client_cert):
                with open(part, "rb") as src:
                    f.write(os.urandom(300) + src.read())

    @unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed")
    def test_find_certificate_page_command(self):   # C3
        self.write_slicer()
        published = []
        plugin._service.publish = published.append
        plugin._service.submit("f", "find_certificate", {})
        reply = wait(lambda: next((m for m in published if m.get("id") == "f"), None), 20)
        self.assertTrue(reply.get("result", {}).get("found"), reply)
        self.assertEqual(audit_guard.denials(), [])

    @unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed")
    def test_find_certificate_script(self):   # C3
        self.write_slicer()
        result = run_off_main(lambda: plugin.FindCertificate().execute())
        self.assertEqual(result.status, "success", result.message)
        self.assertEqual(audit_guard.denials(), [])

    def test_find_certificate_ungranted_path(self):   # C3
        outside = self.ungranted_dir("elsewhere-")
        published = []
        plugin._service.publish = published.append
        plugin._service.submit("g", "find_certificate", {"path": outside})
        reply = wait(lambda: next((m for m in published if m.get("id") == "g"), None), 20)
        self.assertIn(outside, reply["error"])
        self.assertIn("Plugins > Permissions", reply["error"])

    def test_connect_to_granted_host(self):
        page = plugin.KobraControlPage()
        page.posted = []
        run_off_main(lambda: page.on_message({"type": "hello", "id": 1}))
        reply = wait(lambda: next((m for m in page.posted if m.get("id") == 1), None))
        self.assertIn("result", reply)
        self.assertEqual(audit_guard.denials(), [])
