"""plugin.py with a fake `orca` module, against FakeKobra on 127.0.0.1. Run: python3 -m unittest tests/test_plugin.py -v"""

import json
import os
import sys
import shutil
import tempfile
import threading
import time
import types
import unittest
import zipfile
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
import i18n  # noqa: E402
import kobra  # noqa: E402
import plugin  # noqa: E402
import service  # noqa: E402

pa = orca.printer_agent


def isolate(test):
    """Module state a test may change: the grants, the refused addresses, queue_on_main and the last preset hints."""
    saved = (set(plugin._granted), set(plugin._refused), plugin._queue_on_main, plugin._last_hints)

    def restore():
        plugin._granted.clear()
        plugin._granted.update(saved[0])
        plugin._refused.clear()
        plugin._refused.update(saved[1])
        plugin._queue_on_main, plugin._last_hints = saved[2], saved[3]
    test.addCleanup(restore)


class FakeSvc:
    """Just enough of Service for the page's hello / save_settings: records the order of the calls."""

    def __init__(self, refuse=False):
        self.calls, self.refuse, self.target = [], refuse, None

    def _ask_orcaslicer(self, host):
        self.calls.append(("ask", host))
        if self.refuse:
            raise PermissionError("denied")

    def set_target(self, target, retry=False):
        self.calls.append(("set_target", target.preset_host))

    def touch(self, **kw):
        pass

    def submit(self, *a):
        pass


class Base(unittest.TestCase):
    state = "free"

    def setUp(self):
        isolate(self)
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        self.addCleanup(i18n.set_language, "en")   # a test that picks a language must not leave it to the next
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
        msg = wait(lambda: next((m for m in self.events["message"] if m.get("print", {}).get("ams", {}).get("ams")), None))
        self.wait_state(kobra.normalise(self.state))
        return msg

    def wait_state(self, state, timeout=15):
        """Until the plugin's view of the fake printer is `state` with every connect query answered: a print or a
        refusal then depends on what the printer said, never on how fast this machine is."""
        def ready():
            view = plugin._service.view_for(self.fake.host) if plugin._service else None
            return view if view and view["connected"] and view["state"] == state and view["multi_color_box"] else None
        return wait(ready, timeout)

    def sent(self, type_, action):
        return [r["msg"] for r in self.fake.requests if isinstance(r["msg"], dict)
                and (r["msg"].get("type"), r["msg"].get("action")) == (type_, action)]


class Registration(unittest.TestCase):
    def setUp(self):
        isolate(self)
        plugin._granted.clear()
        plugin._refused.clear()

    def test_capabilities_and_permissions(self):
        orca.registered.clear()
        orca.permissions.clear()
        plugin._storage_dir, plugin._store = tempfile.mkdtemp(), None
        plugin.KobraControl().register_capabilities()
        self.assertEqual(orca.registered, [plugin.KobraAgent, plugin.KobraControlPage, plugin.CheckConnection,
                                           plugin.FindCertificate])
        perms = orca.permissions[-1]
        self.assertTrue(perms["threading"])
        # Not the preset's 127.0.0.1: plugins load while OrcaSlicer's UI thread still loads the presets
        self.assertEqual(perms["network"], ["http://239.255.255.250"])   # the SSDP group only
        self.assertEqual(perms["fs_read"], plugin.job_read_grants())   # no Anycubic Slicer Next folder by default
        self.assertNotIn("fs_readwrite", perms)   # L7: the plugin writes no downloads

    def test_register_capabilities_reads_no_preset(self):
        """Plugins load on a thread of their own while OrcaSlicer's UI thread loads the presets: reading them then
        races it. Only the plugin's own storage folder and files are read."""
        touched = []

        class Host:
            plugin = orca.host.plugin

            def __getattr__(self, name):
                touched.append(name)
                raise AssertionError("orca.host.%s read at load" % name)
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, plugin.ADDRESSES_FILE), "w", encoding="utf-8") as f:
            json.dump({"printers": {"Anycubic Kobra X 0.4 nozzle": {"ip": "192.168.1.30"}}}, f)
        plugin._storage_dir, plugin._store = folder, None
        orca.permissions.clear()
        with mock.patch.object(orca, "host", Host()):
            plugin.KobraControl().register_capabilities()
        self.assertEqual(touched, [])
        self.assertEqual(orca.permissions[-1]["network"], ["http://192.168.1.30", "http://239.255.255.250"])

    def test_preset_address_is_granted_on_the_ui_thread(self):
        """connect_printer and the page's hello ask OrcaSlicer about the preset's address (the audited event) once;
        a refusal is logged, nothing raised."""
        svc = FakeSvc()
        plugin.grant_on_ui_thread(svc, "192.168.1.77")
        plugin.grant_on_ui_thread(svc, "192.168.1.77")
        plugin.grant_on_ui_thread(svc, "printer.example.com")   # not a numeric LAN address: no lookup on the UI thread
        self.assertEqual(svc.calls, [("ask", "192.168.1.77")])
        self.assertIn("192.168.1.77", plugin._granted)
        plugin.grant_on_ui_thread(FakeSvc(refuse=True), "192.168.1.78")
        self.assertNotIn("192.168.1.78", plugin._granted)

    def page_with(self, svc):
        page = plugin.KobraControlPage()
        page.posted = []
        page.post_message = page.posted.append
        self.enterContext(mock.patch.object(plugin, "service", lambda publish=None: svc))
        return page

    def test_hello_and_save_ask_before_the_target_is_set(self):
        """The preset's address must be granted before set_target starts locating and connecting on worker threads."""
        svc = FakeSvc()
        page = self.page_with(svc)
        page.on_message({"type": "hello", "id": 1})
        self.assertEqual(svc.calls, [("ask", "127.0.0.1"), ("set_target", "127.0.0.1")])
        plugin._granted.discard("127.0.0.1")
        svc.calls.clear()
        page.on_message({"type": "save_settings", "id": 2, "settings": {}})
        self.assertEqual(svc.calls, [("ask", "127.0.0.1"), ("set_target", "127.0.0.1")])

    def test_refused_address_is_asked_again_only_on_a_user_action(self):
        """A No in OrcaSlicer's dialog is not followed by another dialog on every hello or selection change; Save
        and connecting the Device tab ask again."""
        svc = FakeSvc(refuse=True)
        page = self.page_with(svc)
        page.on_message({"type": "hello", "id": 1})
        page.on_message({"type": "hello", "id": 2})
        self.assertEqual([c for c in svc.calls if c[0] == "ask"], [("ask", "127.0.0.1")])
        page.on_message({"type": "save_settings", "id": 3, "settings": {}})
        self.assertEqual([c for c in svc.calls if c[0] == "ask"], [("ask", "127.0.0.1")] * 2)
        svc.refuse = False
        plugin.grant_on_ui_thread(svc, "127.0.0.1", user=True)   # connect_printer
        self.assertIn("127.0.0.1", plugin._granted)
        self.assertNotIn("127.0.0.1", plugin._refused)

    def test_check_script_reads_presets_on_the_ui_thread(self):
        """Check Kobra X connection runs on a script worker: it has the UI thread read the preset (queue_on_main)
        and ask about its address there, and never reads presets itself."""
        ui = []

        def queue(task):   # OrcaSlicer runs it later on the UI thread
            t = threading.Thread(target=task, name="ui")
            ui.append(t)
            t.start()
        readers = []
        real = plugin.preset_hints

        def hints():
            readers.append(threading.current_thread().name)
            return real()
        svc = FakeSvc()
        self.enterContext(mock.patch.object(plugin, "preset_hints", hints))
        plugin._queue_on_main = queue
        self.assertEqual(run_off_main(lambda: plugin.preset_hints_from_worker(svc))[0], "127.0.0.1")
        self.assertEqual(readers, ["ui"])
        self.assertEqual(svc.calls, [("ask", "127.0.0.1")])
        plugin._queue_on_main = None   # no queue: the hints the tab last read, presets untouched
        plugin._last_hints = ("192.168.1.9", "KX", "")
        self.assertEqual(run_off_main(lambda: plugin.preset_hints_from_worker(svc)), ("192.168.1.9", "KX", ""))
        self.assertEqual(readers, ["ui"])

        late = []
        plugin._queue_on_main = late.append   # a UI thread that does not answer in time
        with mock.patch.object(plugin, "UI_WAIT", 0.05):
            self.assertEqual(run_off_main(lambda: plugin.preset_hints_from_worker(svc)), ("192.168.1.9", "KX", ""))
        late[0]()   # the UI thread gets to it after the script gave up: no preset read, no dialog
        self.assertEqual(readers, ["ui"])
        self.assertEqual(svc.calls, [("ask", "127.0.0.1")])

    def test_raising_queued_callback_is_caught(self):
        """A callback queued to OrcaSlicer's UI thread that raises must not escape: OnExceptionInMainLoop would end
        OrcaSlicer."""
        agent, queued, logged = plugin.KobraAgent(), [], []
        agent.set_queue_on_main_fn(queued.append)

        def boom(*args):
            raise RuntimeError("host gone")
        agent.set_on_printer_connected_fn(boom)
        agent._emit("printer_connected", "dev")
        with mock.patch.object(plugin, "log", logged.append):
            queued[0]()   # what OrcaSlicer's CallAfter runs later: must return normally
        self.assertEqual(len(logged), 1)
        self.assertIn("printer_connected", logged[0])
        self.assertIn("host gone", logged[0])

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

    def test_orca_print_options(self):
        """OrcaSlicer's Print dialog never sends vibration compensation (SelectMachine.cpp passes false): the Kobra
        Control setting is the default. Its Flow Dynamics Calibration and Timelapse start "on" for a printer it has no
        saved choice for, so with the default settings (both off, untested on the printer) neither is sent."""
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]", task_flow_cali=True,
                                task_record_timelapse=True)
        self.assertEqual(self.agent.start_local_print(params, None, lambda: False), 0)
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["vibration_compensation"], task["flow_calibration"], task["timelapse"]["status"]), (1, 0, 0))

    def test_orca_print_options_opted_in(self):
        self.connect()
        plugin.get_store().update({"flow_calibration": True, "timelapse": True})
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]", task_flow_cali=True,
                                task_record_timelapse=True)
        self.assertEqual(self.agent.start_local_print(params, None, lambda: False), 0)
        task = wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]
        self.assertEqual((task["flow_calibration"], task["timelapse"]), (1, {"status": 1, "count": 0, "type": 64}))

    def test_job_task(self):
        params = pa.PrintParams(task_bed_leveling=True, task_record_timelapse=True, task_flow_cali=True)
        self.assertEqual(plugin.job_task(params, {"vibration_compensation": True}),
                         {"auto_leveling": True, "vibration_compensation": True, "flow_calibration": False, "timelapse": False})
        self.assertEqual(plugin.job_task(params, plugin.settings.DEFAULTS),   # defaults: the untested options stay off
                         {"auto_leveling": True, "vibration_compensation": True, "flow_calibration": False, "timelapse": False})
        both = {"flow_calibration": True, "timelapse": True}
        self.assertEqual({k: plugin.job_task(params, both)[k] for k in both}, both)
        self.assertEqual({k: plugin.job_task(pa.PrintParams(), both)[k] for k in both}, {k: False for k in both})   # dialog off

    def test_job_task_auto_leveling_needs_dialog_and_setting(self):
        on, off = pa.PrintParams(task_bed_leveling=True), pa.PrintParams(task_bed_leveling=False)
        self.assertTrue(plugin.job_task(on, plugin.settings.DEFAULTS)["auto_leveling"])     # default: unchanged
        self.assertFalse(plugin.job_task(on, {"auto_leveling": False})["auto_leveling"])     # setting off wins
        self.assertFalse(plugin.job_task(off, {"auto_leveling": True})["auto_leveling"])     # dialog off wins

    def test_orca_print_without_auto_leveling_setting(self):
        self.connect()
        plugin.get_store().update({"auto_leveling": False})
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]", task_bed_leveling=True)
        self.assertEqual(self.agent.start_local_print(params, None, lambda: False), 0)
        self.assertEqual(wait(lambda: self.sent("print", "start"))[0]["data"]["task_settings"]["auto_leveling"], 0)
        self.assertFalse(plugin.job_task(params, {})["vibration_compensation"])
        self.assertFalse(plugin.job_task(params, {"vibration_compensation": False})["vibration_compensation"])
        self.assertTrue(plugin.job_task(pa.PrintParams(task_vibration_cali=True), {"vibration_compensation": False})["vibration_compensation"])

    def test_status_shows_flow_dynamics_calibration(self):
        msg = self.connect()["print"]
        self.assertEqual(msg["home_flag"] >> 16 & 1, 1)

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
        self.assertEqual(set(config["located"]), {"address", "source", "preset_host", "preset_agent", "spoolman_url",
                                                  "spoolman_source"})

    def test_allow_hosts_is_answered_on_the_calling_thread(self):
        page = self.page()
        page.on_message({"type": "allow_hosts", "id": 9, "hosts": ["8.8.8.8"]})   # not a pending LAN printer
        self.assertEqual(page.posted[-1], {"type": "reply", "id": 9, "result": {"allowed": [], "refused": []}})

    def test_moonraker_preset_is_a_hint_parsed_to_its_bare_host(self):
        """The owner's preset: printer_agent moonraker, print_host http://10.25.16.41:7125 (Kobralink)."""
        preset = orca.host.preset_bundle().current_printer_preset()
        old = type(preset).config_value
        values = {"printer_model": "Anycubic Kobra X", "printer_agent": "moonraker", "print_host": "http://10.25.16.41:7125"}
        type(preset).config_value = lambda self, key: values.get(key)
        try:
            self.assertEqual(plugin.preset_hints()[0::2], ("10.25.16.41", "moonraker"))
            target = plugin._target()
            self.assertEqual((target.host, target.preset_host, target.preset_agent), ("", "10.25.16.41", "moonraker"))
        finally:
            type(preset).config_value = old

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
            page.on_message({"type": "hello", "id": 2})   # no Kobra X preset: the network search finds none
            reply = wait(lambda: next((m for m in page.posted if m.get("id") == 2), None), 15)
            self.assertTrue(reply["no_target"])
            self.assertIn("No Kobra X answered the network search", reply["error"])
            plugin.get_store().update({"host": "http://127.0.0.1:1234"})
            self.assertEqual(plugin._target().host, "127.0.0.1")   # the host setting overrides the preset
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

    def test_time_lapse_commands(self):
        """The page lists the videos and deletes one by name: {type: cmd, cmd: videos | video_delete, args, gen}."""
        name = "benchy-20261116215053_8.mp4"
        video = {"createTime": 1794838471, "duration": 6, "fileKey": "f" * 32, "fileSize": 109048, "file_image": "b_6.jpg",
                 "filename": name, "main_file_name": "benchy"}
        self.fake.reply("file", "listVideo", {"records": [video]})
        self.fake.reply("file", "deleteVideo", None, state="success")
        page = self.page()
        page.on_message({"type": "hello", "id": 1})
        wait(lambda: any(m.get("id") == 1 for m in page.posted))
        gen = plugin._service.generation

        def answer(rid, cmd, args, gen=gen):
            page.on_message({"type": "cmd", "id": rid, "cmd": cmd, "args": args, "gen": gen})
            return wait(lambda: next((m for m in page.posted if m.get("type") == "reply" and m.get("id") == rid), None))
        self.assertEqual(answer(2, "videos", {}), {"type": "reply", "id": 2, "result": {"videos": [
            {"filename": name, "name": "benchy", "created": 1794838471, "duration": 6, "size": 109048, "empty": False}]}})
        self.assertEqual(answer(3, "video_delete", {"name": name}), {"type": "reply", "id": 3, "result": {"deleted": name}})
        self.assertEqual([m["data"] for m in self.sent("file", "deleteVideo")], [{"path": "/", "filename": name}])
        self.assertEqual(set(answer(4, "video_delete", {"name": "../benchy.mp4"})), {"type", "id", "error"})
        # a delete asked for the printer that was selected before is dropped
        self.assertIn("selected printer changed", answer(5, "video_delete", {"name": name}, gen + 1)["error"])
        self.assertEqual(len(self.sent("file", "deleteVideo")), 1)


class Language(Base):
    """The plugin's own texts (Print dialog progress, errors, script results) follow Settings, then OrcaSlicer."""

    def host_language(self, code):
        if not hasattr(orca.host, "app_language"):
            self.addCleanup(delattr, orca.host, "app_language")
        orca.host.app_language = code

    def test_follows_orcaslicer_then_the_settings_choice(self):
        self.host_language("de_DE")
        plugin.sync_language()
        self.assertEqual(i18n.language(), "de")
        self.assertEqual(plugin.tr("Print started"), i18n.CATALOGUES["de"]["Print started"])
        self.host_language("zh_TW")
        plugin.sync_language()
        self.assertEqual(i18n.language(), "zh-CN")
        plugin.get_store().update({"ui_language": "es"})
        self.addCleanup(plugin.get_store().update, {"ui_language": "auto"})
        plugin.sync_language()
        self.assertEqual(i18n.language(), "es")

    def test_unknown_language_reads_english(self):
        self.host_language("ja_JP")
        plugin.sync_language()
        self.assertEqual(i18n.language(), "en")
        self.assertEqual(plugin.tr("Print started"), "Print started")

    def test_agent_texts_in_the_host_language(self):
        self.host_language("es_ES")
        self.connect()   # connect_printer reads the language: OrcaSlicer runs the agent before any page
        self.assertEqual(i18n.language(), "es")
        self.assertEqual(self.agent.get_agent_info().description,
                         i18n.CATALOGUES["es"]["Anycubic Kobra X over the LAN (MQTT), by kobracontrol"])


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


class GcodeChecks(Base):
    """Read-only G-code checks: a warning in the Print dialog's last line and an OrcaSlicer notification, never a
    refusal, and the file goes to the printer as it is."""

    def gcode_3mf(self, name):
        with open(os.path.join(ROOT, "tests", "fixtures", "gcode", name), "rb") as f:
            gcode = f.read()
        path = os.path.join(self.tmp, "job.gcode.3mf")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Metadata/plate_1.gcode", gcode)
        return path, gcode

    def setUp(self):
        super().setUp()
        orca.notifications.clear()

    def test_print_warns_without_config_block_and_sends_the_file_unchanged(self):
        self.connect()
        stages = []
        path, gcode = self.gcode_3mf("no_config_block.gcode")
        params = pa.PrintParams(project_name="cube", filename=path, plate_index=1, ams_mapping="[0]",
                                ams_mapping_info=json.dumps([{"ams": 0, "sourceColor": "#FF0000", "filamentType": "PLA"}]))
        self.assertEqual(self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False), 0)
        self.assertEqual(self.fake.uploads[0]["data"], gcode)
        self.assertEqual(stages[-1][:2], (plugin.STAGE_FINISHED, 100))
        self.assertTrue(stages[-1][2].startswith("Print started "))
        self.assertIn("Skip G-code config block", stages[-1][2])
        self.assertEqual(len(orca.notifications), 1)
        self.assertIn("Skip G-code config block", orca.notifications[0])

    def test_good_file_prints_without_warning(self):
        self.connect()
        stages = []
        path, _ = self.gcode_3mf("good.gcode")
        params = pa.PrintParams(project_name="cube", filename=path, plate_index=1, ams_mapping="[0]",
                                ams_mapping_info=json.dumps([{"ams": 0, "sourceColor": "#FF0000", "filamentType": "PLA"}]))
        self.assertEqual(self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False), 0)
        self.assertEqual(stages[-1][2], "Print started")
        self.assertEqual(orca.notifications, [])

    def test_send_warns_without_thumbnail(self):
        self.connect()
        stages = []
        path, gcode = self.gcode_3mf("no_thumbnail.gcode")
        params = pa.PrintParams(project_name="cube", filename=path, plate_index=1)
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, lambda *a: stages.append(a), lambda: False, None), 0)
        self.assertEqual(self.fake.uploads[0]["data"], gcode)
        self.assertIn("G-code thumbnails", stages[-1][2])
        self.assertIn("G-code thumbnails", orca.notifications[0])

    def bundle(self, name="Anycubic Kobra X 0.4 nozzle", **values):
        preset = types.SimpleNamespace(name=name, config_value=lambda k: {
            "printer_model": "Anycubic Kobra X", "print_host": "http://127.0.0.1:18910", **values}.get(k))
        return types.SimpleNamespace(current_printer_preset=lambda: preset, full_config_value=lambda k: None)

    def test_connection_check_names_the_preset_setting(self):
        bundle = self.bundle(gcode_skip_config_block="1", thumbnails="300x300/JPG")
        with mock.patch.object(orca.host, "preset_bundle", lambda: bundle):
            result = plugin.CheckConnection().execute()
        self.assertEqual(result.status, "success")
        self.assertIn("KX at 127.0.0.1", result.message)
        self.assertIn("Skip G-code config block is on in this printer preset", result.message)
        self.assertIn("(G-code thumbnails: 300x300/JPG)", result.message)

    def test_connection_check_quiet_for_a_good_preset_or_another_printer(self):
        for bundle in (self.bundle(gcode_skip_config_block="0", thumbnails="32x32/PNG, 300x300/PNG"),
                       self.bundle("Other printer", printer_model="Other", gcode_skip_config_block="1")):
            with mock.patch.object(orca.host, "preset_bundle", lambda: bundle):
                self.assertEqual(plugin.preset_gcode_warnings(), [])


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
        # the preset's printer is no longer declared at load: model the Yes OrcaSlicer saved for it on the UI thread
        audit_guard.enable({**self.perms, "network_socket": ["127.0.0.1"]}, self.tmp)
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
        root = plugin.slicer_temp_root()
        os.makedirs(root, exist_ok=True)
        folder = tempfile.mkdtemp(prefix="kobracontrol-test-", dir=root)   # unique: overlapping runs never share it
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_slicer_temp_root(self):
        if os.name != "nt":
            self.assertEqual(plugin.slicer_temp_root(), os.path.join(tempfile.gettempdir(), "orcaslicer_%d" % os.getuid()))
        self.assertIn(os.path.realpath(plugin.slicer_temp_root()) + "/*", self.perms["fs_read"])

    def test_print_from_orca_temp_dir(self):   # C1 + C2
        self.connect()   # waits until the printer is known to be idle (state, not time)
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.job_dir()), ams_mapping="[0]")
        stages = []
        code = run_off_main(lambda: self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False))
        self.assertEqual((code, audit_guard.denials()), (0, []), stages[-1:])
        self.assertEqual(self.fake.uploads[0]["data"], test_service.GCODE)
        self.assertEqual(len(self.sent("print", "start")), 1)

    def test_connect_waits_for_the_printer_state(self):
        """The helper every print test relies on: it returns only once the printer reported idle."""
        self.fake.replies[("info", "query")]["data"]["project"] = None
        delay = threading.Event()
        real = self.fake.replies[("info", "query")]

        def slow(msg):   # the first info answer comes late, as on a loaded machine
            delay.wait(1.0)
            return real
        self.fake.replies[("info", "query")] = slow
        self.connect()
        self.assertEqual(plugin._service.view_for(self.fake.host)["state"], "idle")

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

    def grant_slicer(self):
        """What the user's Yes in OrcaSlicer's prompt amounts to: a read grant for the slicer's folder."""
        audit_guard.enable({**self.perms, "fs_read": self.perms["fs_read"] + [os.path.realpath(self.slicer) + "/*"]},
                           self.tmp)

    @unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed")
    def test_find_certificate_page_command(self):   # C3
        self.slicer = self.ungranted_dir("anycubic-")   # on Windows the system temp folder is granted (job folder)
        self.write_slicer()
        published = []
        plugin._service.publish = published.append
        plugin._service.submit("f", "find_certificate", {})   # nothing granted at load: refused, and says so
        reply = wait(lambda: next((m for m in published if m.get("id") == "f"), None), 20)
        self.assertIn("OrcaSlicer did not let kobracontrol read", reply.get("error", ""))
        self.grant_slicer()
        plugin._service.submit("f2", "find_certificate", {})
        reply = wait(lambda: next((m for m in published if m.get("id") == "f2"), None), 20)
        self.assertTrue(reply.get("result", {}).get("found"), reply)
        self.assertEqual(audit_guard.denials(), [])

    @unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed")
    def test_find_certificate_script(self):   # C3
        self.write_slicer()
        self.grant_slicer()
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
