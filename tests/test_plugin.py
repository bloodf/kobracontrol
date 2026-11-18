"""plugin.py with a fake `orca` module, against FakeKobra on 127.0.0.1. Run: python3 -m unittest tests/test_plugin.py -v"""

import json
import re
import types
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
real_read_json = plugin.spooler_bridge.read_json


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
        # Tests of the print path outside ShowDialog print without the print setup window (its default answer is Cancel).
        plugin.get_store().update({"print_dialog": False})
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
        self.assertEqual((tray["tray_type"], tray["tray_info_idx"]), ("PLA", "OFDSrzZ8"))   # Generic PLA @System
        self.assertEqual(msg["ams"]["ams"][0]["tray"][1]["tray_info_idx"], "OFYPdQJh")   # Generic PETG @System

    def test_linked_slot_reports_its_spooler_preset_id(self):
        """OrcaSlicer's sync from AMS matches presets on tray_info_idx: a slot linked to a Spoolman spool carries the
        SPL id of the spool's standalone Spooler preset (from profiles.json); the others the Generic id of their
        material. The links come from Spoolman at connect, without the tab."""
        name = "_local/spooler/Acme PLA Red @Anycubic Kobra X"
        mine = {"name": name, "bundle_id": "spooler", "vendor": "Acme", "colour": "#FF0000"}
        profiles = {"version": 1, "filaments": {"9": {"Anycubic Kobra X": name}}, "ids": {name: "SPL0123456789"}}
        spool = {"id": 5, "filament_id": 9, "vendor": "Acme", "material": "PLA", "colour": "#FE0101"}
        targets = []

        def links_for(target):
            targets.append(target.name)
            return [spool], {0: 5}
        with mock.patch.object(plugin, "filament_catalog", return_value=([mine], "Anycubic Kobra X")), \
                mock.patch.object(plugin.spooler_bridge, "read_json", return_value=profiles), \
                mock.patch.object(plugin._service, "links_for", side_effect=links_for):
            self.connect()
            wait(lambda: self.agent._links[1])
            self.events["message"].clear()
            self.agent._dirty.set()
            msg = wait(lambda: next((m for m in self.events["message"] if m.get("print", {}).get("ams", {}).get("ams")), None))
        self.assertTrue(targets)
        trays = msg["print"]["ams"]["ams"][0]["tray"]
        self.assertEqual((trays[0]["tray_type"], trays[0]["tray_info_idx"]), ("PLA", "SPL0123456789"))
        self.assertEqual(trays[1]["tray_info_idx"], "OFYPdQJh")   # PETG, not linked: Generic PETG
        svc = plugin._service
        with svc.lock:   # the tab showing this printer wins: its links are up to date
            svc.target = service.Target(self.fake.host)
            svc.spools, svc.bindings = [spool], {1: 5}
        self.assertEqual(list(self.agent._bound_spools()), [1])
        with svc.lock:   # another printer in the tab: the agent's own links
            svc.target = service.Target("10.9.9.9")
        self.assertEqual(list(self.agent._bound_spools()), [0])

    def linked_trays(self, users, spool, users_error=None):
        """Connect with slot 0 linked to `spool`, the user presets `users` and Spooler's preset for the spool; the
        trays of the next status push."""
        name = "_local/spooler/Acme PLA Red @Anycubic Kobra X"
        mine = {"name": name, "bundle_id": "spooler", "vendor": "Acme", "colour": "#FF0000"}
        profiles = {"version": 1, "filaments": {"9": {"Anycubic Kobra X": name}}, "ids": {name: "SPL0123456789"}}
        spool = {"id": 5, "filament_id": 9, "vendor": "Acme", "material": "PLA", "colour": "#FE0101", **spool}
        with mock.patch.object(plugin, "filament_catalog", return_value=([mine], "Anycubic Kobra X")), \
                mock.patch.object(plugin, "user_presets", return_value=users, side_effect=users_error), \
                mock.patch.object(plugin.spooler_bridge, "read_json", wraps=lambda folder, file: (
                    profiles if file == plugin.spooler_bridge.PROFILES_FILE else real_read_json(folder, file))), \
                mock.patch.object(plugin._service, "links_for", return_value=([spool], {0: 5})):
            self.connect()
            wait(lambda: self.agent._links[1])
            self.events["message"].clear()
            self.agent._dirty.set()
            msg = wait(lambda: next((m for m in self.events["message"] if m.get("print", {}).get("ams", {}).get("ams")), None))
        return msg["print"]["ams"]["ams"][0]["tray"]

    def user_preset(self, name, inherits="", filament_id="P1234567"):
        path = os.path.join(self.tmp, name + ".json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": name, "inherits": inherits, "filament_id": filament_id}, f)
        return {"name": name, "compatible": True, "file": path, "inherits": inherits}

    def test_slot_linked_to_a_standalone_user_preset_reports_its_id(self):
        """orca_filament_preset names a standalone user preset: its own filament_id, so sync from AMS loads it."""
        trays = self.linked_trays([self.user_preset("My PLA")], {"orca_preset": "my pla"})
        self.assertEqual(trays[0]["tray_info_idx"], "P1234567")
        self.assertEqual(trays[1]["tray_info_idx"], "OFYPdQJh")   # not linked: Generic PETG
        self.assertEqual([m for m in self.published if m.get("type") == "notice"], [])

    def test_slot_linked_to_an_inheriting_user_preset_keeps_the_usual_id(self):
        """A preset that inherits carries its parent's id and sync would load the parent: the Spooler id stays."""
        trays = self.linked_trays([self.user_preset("My PLA", inherits="Generic PLA @System", filament_id="OFDSrzZ8")],
                                  {"orca_preset": "My PLA"})
        self.assertEqual(trays[0]["tray_info_idx"], "SPL0123456789")

    def test_unknown_linked_preset_keeps_the_usual_id_and_says_so_once(self):
        plugin._preset_notices.clear()
        self.addCleanup(plugin._preset_notices.clear)
        trays = self.linked_trays([self.user_preset("My PLA") | {"compatible": False}], {"orca_preset": "My PLA"})
        self.assertEqual(trays[0]["tray_info_idx"], "SPL0123456789")
        self.agent._dirty.set()
        time.sleep(1.2)   # more pushes, the same name: no second notice
        notices = [m["text"] for m in self.published if m.get("type") == "notice"]
        self.assertEqual(len(notices), 1)
        self.assertIn('"My PLA"', notices[0])

    def test_ambiguous_linked_preset_says_so(self):
        plugin._preset_notices.clear()
        self.addCleanup(plugin._preset_notices.clear)
        trays = self.linked_trays([self.user_preset("My PLA"), self.user_preset("my pla")], {"orca_preset": "MY PLA"})
        self.assertEqual(trays[0]["tray_info_idx"], "SPL0123456789")
        notices = [m["text"] for m in self.published if m.get("type") == "notice"]
        self.assertEqual(len(notices), 1)
        self.assertIn("several", notices[0])

    def test_unreadable_user_presets_keep_the_usual_ids(self):
        plugin._user_presets_failed = False
        self.addCleanup(setattr, plugin, "_user_presets_failed", False)
        trays = self.linked_trays([], {"orca_preset": "My PLA"}, users_error=RuntimeError("boom"))
        self.assertEqual((trays[0]["tray_info_idx"], trays[1]["tray_info_idx"]), ("SPL0123456789", "OFYPdQJh"))

    def test_a_fixed_link_that_breaks_again_warns_again(self):
        plugin._preset_notices.clear()
        self.addCleanup(plugin._preset_notices.clear)
        spool = {"orca_preset": "My PLA"}
        self.agent._user_presets = []
        self.agent._linked_id(spool)
        self.agent._user_presets = [self.user_preset("My PLA")]
        self.assertEqual(self.agent._linked_id(spool), "P1234567")
        self.agent._user_presets = []
        self.agent._linked_id(spool)
        self.assertEqual(len([m for m in self.published if m.get("type") == "notice"]), 2)

    def test_missing_or_bad_preset_file_keeps_the_usual_id_and_logs_once(self):
        preset = self.user_preset("My PLA")
        self.agent._user_presets = [preset]
        spool = {"orca_preset": "My PLA"}
        logged = []
        with mock.patch.object(plugin, "log", side_effect=logged.append):
            self.assertEqual(self.agent._linked_id(spool), "P1234567")
            os.remove(preset["file"])   # gone between refreshes
            self.assertEqual([self.agent._linked_id(spool) for _ in range(3)], ["", "", ""])
            self.assertEqual(len(logged), 1)
            with open(preset["file"], "w", encoding="utf-8") as f:
                f.write("{not json")
            self.assertEqual([self.agent._linked_id(spool) for _ in range(3)], ["", "", ""])
            self.assertEqual(len(logged), 2)

    def test_preset_file_read_once_per_version(self):
        preset = self.user_preset("My PLA")
        self.agent._user_presets = [preset]
        spool = {"orca_preset": "My PLA"}
        with mock.patch.object(plugin.spooler_bridge, "standalone_id", wraps=plugin.spooler_bridge.standalone_id) as read:
            self.assertEqual([self.agent._linked_id(spool) for _ in range(3)], ["P1234567"] * 3)
            self.assertEqual(read.call_count, 1)
            with open(preset["file"], "w", encoding="utf-8") as f:
                json.dump({"name": "My PLA", "filament_id": "P7654321"}, f)
            os.utime(preset["file"], (time.time() + 5, time.time() + 5))
            self.assertEqual(self.agent._linked_id(spool), "P7654321")
            self.assertEqual(read.call_count, 2)

    def test_unreadable_user_presets_leave_the_catalog_working(self):
        """user_presets() raising must not stop the Spooler catalog: no linked presets, logged once."""
        plugin._user_presets_failed = False
        self.addCleanup(setattr, plugin, "_user_presets_failed", False)
        logged = []
        with mock.patch.object(plugin, "user_presets", side_effect=RuntimeError("boom")), \
                mock.patch.object(plugin, "filament_catalog", return_value=([{"name": "x"}], "Anycubic Kobra X")), \
                mock.patch.object(plugin, "log", side_effect=logged.append), \
                mock.patch.object(plugin._service, "links_for", return_value=([], {})):
            self.agent._refresh_catalog({})
            self.agent._refresh_catalog({})
        self.assertEqual(self.agent._catalog[0], [{"name": "x"}])
        self.assertEqual(self.agent._user_presets, [])
        self.assertEqual(len([m for m in logged if "own filament presets" in m]), 1)

    def test_user_presets_are_read_only_through_queue_on_main(self):
        """Presets are read on the UI thread only: the push thread queues the catalog read, never does it itself."""
        threads = []

        def users():
            threads.append(threading.current_thread())
            return []
        with mock.patch.object(plugin, "user_presets", side_effect=users), \
                mock.patch.object(plugin, "filament_catalog", return_value=([], "Anycubic Kobra X")):
            queued = []
            self.agent.set_queue_on_main_fn(queued.append)
            self.agent._catalog_at = 0.0
            self.agent._preferred()
            self.assertEqual(threads, [])
            self.assertEqual(len(queued), 1)
            with mock.patch.object(plugin, "filament_catalog", side_effect=RuntimeError("boom")):
                queued[0]()   # nothing escapes a queued call
        self.assertIsNone(self.agent._user_presets)

    def test_user_presets_lists_own_compatible_and_incompatible_presets(self):
        meta = {"Generic PLA @System": {}, "_local/spooler/X": {"is_user": True},
                "My PLA": {"is_user": True, "file": "/u/My PLA.json", "inherits": '"Generic PLA @System"'},
                "My PETG": {"is_user": True, "is_compatible": False}}
        names = list(meta)
        fake = fake_orca.install_orca(filament_names=names, filament_meta=meta)
        sys.modules["orca"] = orca
        with mock.patch.object(plugin.orca.host, "preset_bundle", fake.host.preset_bundle):
            found = plugin.user_presets()
        self.assertEqual(found, [{"name": "My PLA", "compatible": True, "file": "/u/My PLA.json",
                                  "inherits": "Generic PLA @System"},
                                 {"name": "My PETG", "compatible": False, "file": "", "inherits": ""}])

    def test_links_for_reads_spoolman_without_touching_the_tab(self):
        svc = plugin._service
        target = service.Target("", name="Anycubic Kobra X", spoolman_url="http://sm")
        raw = [{"id": 5, "location": "Anycubic Kobra X S2", "filament": {"id": 9, "material": "PLA"}}]
        fake = mock.Mock(spools=lambda: raw)
        with mock.patch.object(svc, "_spoolman", return_value=fake):
            spools, bindings = svc.links_for(target)
        self.assertEqual(([s["id"] for s in spools], bindings), ([5], {1: 5}))
        self.assertEqual((svc.spools, svc.bindings), ([], {}))
        self.assertEqual(svc.links_for(service.Target("", spoolman_url="")), ([], {}))

    def test_filament_catalog_reads_compatible_spooler_presets(self):
        presets = {"Generic PLA @System": dict(is_system=True),
                   "_local/spooler/Y @Other": dict(bundle_id="spooler", is_compatible=False),
                   "_local/spooler/X @Anycubic Kobra X": dict(bundle_id="spooler", filament_vendor='"SUNLU"',
                                                              default_filament_colour='"#112233"'),
                   "My own PLA": dict()}

        class P:
            def __init__(self, name):
                meta = presets[name]
                self.name, self.bundle_id = name, meta.get("bundle_id", "")
                self.is_system, self.is_compatible = meta.get("is_system", False), meta.get("is_compatible", True)

            def config_value(self, key):
                return presets[self.name].get(key)

        names = list(presets)
        printer = mock.Mock(config_value=lambda k: {"printer_model": "Anycubic Kobra X"}.get(k))
        printer.name = "Anycubic Kobra X 0.4 nozzle"
        bundle = mock.Mock(current_printer_preset=lambda: printer,
                           filaments=mock.Mock(size=lambda: len(names), preset=lambda i: P(names[i])))
        with mock.patch.object(orca.host, "preset_bundle", return_value=bundle):
            found, label = plugin.filament_catalog()
        self.assertEqual(found, [{"name": "_local/spooler/X @Anycubic Kobra X", "bundle_id": "spooler",
                                  "vendor": "SUNLU", "colour": "#112233"}])
        self.assertEqual(label, "Anycubic Kobra X")

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


class ShowDialog:
    """Kobra Control's own print dialog after OrcaSlicer's Print (plugin.ask_print)."""

    def setUp(self):
        super().setUp()
        plugin.get_store().update({"print_dialog": True})

    def test_unpatched_window_cancels(self):
        """The fake window's default answer is Cancel: a test that forgets to answer can't print by accident."""
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        self.assertEqual(self.agent.start_local_print(params, None, lambda: False), plugin.ERR_CANCELED)
        self.assertEqual(self.fake.uploads, [])

    def show(self, answer, params=None, cancel=lambda: False):
        """Print with the dialog answering `answer` (a callable gets the page data); returns (code, page data, stages)."""
        seen, stages = {}, []

        def create_window(html, title="", width=0, height=0, on_message=None, on_close=None, on_submit=None, style=None):
            text = re.search(r'id="kobra-boot">(.*?)</script>', html, re.S).group(1)
            seen["boot"] = json.loads(text)
            seen["title"] = title
            data = seen["boot"]["data"]
            return fake_orca.FakeWindow(on_message, on_submit, answer(data) if callable(answer) else answer)

        params = params or pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]",
                                          ams_mapping_info='[{"sourceColor": "#FF0000FF", "filamentType": "PLA"}]',
                                          task_bed_leveling=True)
        with mock.patch.object(orca.host.ui, "create_window", create_window):
            code = self.agent.start_local_print(params, lambda *a: stages.append(a), cancel)
        return code, seen.get("boot", {}).get("data"), stages


class PrintDialog(ShowDialog, Base):
    def test_dialog_shows_the_job_slots_and_options(self):
        self.connect()
        code, data, stages = self.show({})
        self.assertEqual(code, 0)
        self.assertEqual(data["printer"]["host"], self.fake.host)
        self.assertEqual([(f["index"], f["type"], f["colour"]) for f in data["filaments"]], [(0, "PLA", "#FF0000")])
        self.assertEqual([s["type"] for s in data["slots"]], ["PLA", "PETG", "", "PLA"])
        self.assertEqual(data["trays"], {"0": data["slots"][0]["tray"]})
        self.assertEqual({o["key"]: o["lock"] for o in data["options"]}["timelapse"], "setting")
        self.assertIs(data["auto_feed"], True)
        self.assertEqual(stages[0][0], plugin.STAGE_CREATE)
        wait(lambda: self.sent("print", "start"))

    def test_chosen_slot_and_options_are_sent(self):
        self.connect()
        code, _, _ = self.show(lambda d: {"trays": {"0": d["slots"][3]["tray"]},
                                          "options": {"auto_leveling": False, "vibration_compensation": False},
                                          "remember": True})
        self.assertEqual(code, 0)
        start = wait(lambda: self.sent("print", "start"))[0]["data"]
        self.assertEqual([m["ams_index"] for m in start["ams_settings"]["ams_box_mapping"]], [3])
        self.assertEqual((start["task_settings"]["auto_leveling"], start["task_settings"]["vibration_compensation"]), (0, 0))
        memory = plugin.get_store().effective()["print_memory"][self.fake.host]
        self.assertEqual(memory["auto_leveling"], False)   # the next dialog starts from it (test_printsetup)

    def test_refused_send_remembers_nothing(self):
        self.connect()
        code, _, _ = self.show(lambda d: {"trays": {"0": d["slots"][2]["tray"]}, "options": {"auto_leveling": False},
                                          "remember": False, "auto_feed": False})
        self.assertEqual(code, plugin.ERR_LP_PUBLISH)
        self.assertEqual(plugin.get_store().effective()["print_memory"], {})
        self.assertTrue(plugin.get_store().effective()["remember_print_options"])
        self.assertEqual(self.sent("multiColorBox", "setAutoFeed"), [])   # nothing reached the printer

    def test_cancel_sends_nothing(self):
        self.connect()
        before = len(self.fake.requests)
        code, _, _ = self.show({"cancelled": True, "auto_feed": False})
        self.assertEqual(code, plugin.ERR_CANCELED)
        self.assertEqual((self.fake.uploads, self.sent("print", "start"), self.sent("multiColorBox", "setAutoFeed")), ([], [], []))
        writes = [r["msg"] for r in self.fake.requests[before:] if isinstance(r["msg"], dict)
                  and (r["msg"].get("type"), r["msg"].get("action")) not in test_service.READ_ONLY]
        self.assertEqual(writes, [])
        self.assertEqual(plugin.get_store().effective()["print_memory"], {})

    def silent(self, open_for, ready=True):
        """A window that never answers: ready (or not), open for `open_for` checks of is_open()."""
        calls, closed = [0], []

        def create_window(html, on_message=None, on_submit=None, **kw):
            if ready:
                on_message({"ready": True})

            def is_open():
                calls[0] += 1
                return calls[0] <= open_for
            return types.SimpleNamespace(is_open=is_open, post=lambda d: None, close=lambda: closed.append(1))
        return create_window, closed

    def print_with(self, create_window):
        stages = []
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        with mock.patch.object(orca.host.ui, "create_window", create_window):
            code = self.agent.start_local_print(params, lambda *a: stages.append(a), lambda: False)
        return code, stages

    def test_window_closed_by_the_system_sends_nothing(self):
        self.connect()
        create_window, _ = self.silent(open_for=1)
        self.assertEqual(self.print_with(create_window)[0], plugin.ERR_CANCELED)
        self.assertEqual(self.fake.uploads, [])

    def test_window_that_never_shows_times_out(self):
        self.connect()
        create_window, closed = self.silent(open_for=10 ** 6, ready=False)
        with mock.patch.object(plugin, "DIALOG_READY", 0.3):
            code, stages = self.print_with(create_window)
        self.assertEqual((code, closed, self.fake.uploads), (plugin.ERR_LP_PUBLISH, [1], []))
        self.assertIn("didn't open", stages[-1][2])

    def test_window_left_open_times_out(self):
        self.connect()
        create_window, closed = self.silent(open_for=10 ** 6)
        with mock.patch.object(plugin, "DIALOG_TIMEOUT", 0.3):
            code, stages = self.print_with(create_window)
        self.assertEqual((code, closed, self.fake.uploads), (plugin.ERR_LP_PUBLISH, [1], []))
        self.assertIn("timed out", stages[-1][2])

    def test_unload_closes_an_open_window(self):
        self.connect()
        create_window, closed = self.silent(open_for=10 ** 6)

        def unload_while_open(*a, **kw):
            w = create_window(*a, **kw)
            threading.Timer(0.3, self.agent.on_unload).start()
            return w
        self.assertEqual((self.print_with(unload_while_open)[0], closed), (plugin.ERR_CANCELED, [1]))
        self.assertEqual(plugin._open_dialogs, set())

    def test_refresh_after_a_failed_read_unlocks_start(self):
        """A read fails (the window shows the printer offline), the next one succeeds with the same slots: the
        window is told the printer can print again."""
        self.connect()
        posted, real, calls = [], plugin.service().print_snapshot, [0]

        def flaky(host):
            calls[0] += 1
            if calls[0] == 2:
                raise kobra.KobraError("no answer")
            return real(host)

        def create_window(html, on_message=None, on_submit=None, **kw):
            on_message({"ready": True})
            w = types.SimpleNamespace(is_open=lambda: True, close=lambda: None, post=posted.append)

            def answer():
                wait(lambda: any(p.get("can_print") for p in posted[1:]) if posted else False, 10)
                on_submit({"cancelled": True})
            threading.Thread(target=answer, daemon=True).start()
            return w
        with mock.patch.object(plugin, "DIALOG_REFRESH", 0.1), mock.patch.object(plugin.service(), "print_snapshot", flaky):
            self.assertEqual(self.print_with(create_window)[0], plugin.ERR_CANCELED)
        self.assertEqual((posted[0]["state"], posted[0]["can_print"]), ("offline", False))
        self.assertTrue(posted[1]["can_print"])

    def test_job_cancelled_in_orcaslicer_closes_the_dialog(self):
        self.connect()
        windows, created = [], []

        def create_window(html, on_message=None, on_submit=None, **kw):
            created.append(1)
            w = types.SimpleNamespace(open=True, is_open=lambda: True, post=lambda d: None)
            w.close = lambda: windows.append("closed")
            on_message({"ready": True})
            return w
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        with mock.patch.object(orca.host.ui, "create_window", create_window):
            code = self.agent.start_local_print(params, None, lambda: bool(created))
        self.assertEqual((code, windows, self.fake.uploads), (plugin.ERR_CANCELED, ["closed"], []))

    def test_other_material_refused(self):
        self.connect()
        petg = lambda d: {"trays": {"0": d["slots"][1]["tray"]}, "acknowledged": ["material:0:%d" % d["slots"][1]["tray"]]}
        code, _, stages = self.show(petg)
        self.assertEqual(code, plugin.ERR_LP_PUBLISH)
        self.assertIn("another material", stages[-1][2])
        self.assertEqual(self.sent("print", "start"), [])
        self.assertEqual(self.fake.uploads, [])

    def test_same_family_variant_needs_use_anyway(self):
        self.connect()
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]",
                                ams_mapping_info='[{"sourceColor": "#FF0000FF", "filamentType": "PLA Silk"}]')
        code, _, stages = self.show({}, params)
        self.assertEqual(code, plugin.ERR_LP_PUBLISH)
        self.assertIn("not confirmed", stages[-1][2])
        code, _, _ = self.show(lambda d: {"acknowledged": ["variant:0:%d" % d["slots"][0]["tray"]]}, params)
        self.assertEqual(code, 0)

    def test_task_name_from_the_dialog_names_the_file(self):
        self.connect()
        self.assertEqual(self.show({"name": "Desk tidy v2"})[0], 0)
        self.assertEqual(self.fake.uploads[0]["filename"], "Desk tidy v2.gcode")

    def test_settings_link_reaches_the_tab(self):
        self.connect()
        windows = []

        def create_window(html, on_message=None, on_submit=None, **kw):
            on_message({"ready": True})
            on_message({"open_settings": True})
            w = fake_orca.FakeWindow(lambda m: None, on_submit, {"cancelled": True})
            windows.append(w)
            return w
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]")
        with mock.patch.object(orca.host.ui, "create_window", create_window):
            self.assertEqual(self.agent.start_local_print(params, None, lambda: False), plugin.ERR_CANCELED)
        self.assertIn({"type": "show_tab", "tab": "settings"}, self.published)

    def test_setting_off_still_refuses_another_material(self):
        self.connect()
        plugin.get_store().update({"print_dialog": False})
        params = pa.PrintParams(project_name="cube", filename=make_3mf(self.tmp), ams_mapping="[0]",
                                ams_mapping_info='[{"sourceColor": "#FF0000FF", "filamentType": "PETG"}]')
        code, data, stages = self.show({}, params)
        self.assertEqual((code, data, self.fake.uploads), (plugin.ERR_LP_PUBLISH, None, []))
        self.assertIn("another material", stages[-1][2])
        self.assertEqual(self.sent("print", "start"), [])

    def test_empty_slot_refused(self):
        self.connect()
        code, _, stages = self.show(lambda d: {"trays": {"0": d["slots"][2]["tray"]}})
        self.assertEqual(code, plugin.ERR_LP_PUBLISH)
        self.assertEqual(self.fake.uploads, [])

    def test_auto_feed_change_is_applied_before_the_print(self):
        self.connect()
        self.assertEqual(self.show({"auto_feed": False})[0], 0)
        self.assertEqual(wait(lambda: self.sent("multiColorBox", "setAutoFeed"))[0]["data"]["multi_color_box"][0]["auto_feed"], 0)

    def test_setting_off_skips_the_dialog(self):
        self.connect()
        plugin.get_store().update({"print_dialog": False})
        code, data, _ = self.show({"cancelled": True})
        self.assertEqual((code, data), (0, None))


class PrintDialogWhilePrinting(ShowDialog, Base):
    state = "printing"

    def test_busy_printer_shown_and_refused(self):
        """The dialog says the printer is busy (Print stays off there); an answer anyway is refused, nothing sent."""
        self.connect()
        code, data, stages = self.show({})
        self.assertEqual((data["printer"]["state"], data["printer"]["can_print"]), ("printing", False))
        self.assertEqual((code, self.fake.uploads), (plugin.ERR_LP_PUBLISH, []))
        self.assertIn("printing", stages[-1][2])
        self.assertEqual(plugin.get_store().effective()["print_memory"], {})


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

    def test_check_again_sends_the_config_and_every_requirement(self):
        """Settings' "Check again" re-reads the certificate and Spooler (config) and checks ffmpeg on its own thread."""
        page = self.page()
        with mock.patch.object(service.requirements, "check_ffmpeg", return_value=service.requirements.item("ffmpeg", "ok", "/opt/bin/ffmpeg")), \
                mock.patch.object(service.requirements, "check_anycubic_slicer", return_value=service.requirements.item("anycubic_slicer", "missing")):
            page.on_message({"type": "check_requirements"})
            msg = wait(lambda: [m for m in page.posted if m.get("type") == "requirements" and not m["checking"]])[-1]
        config = next(m for m in page.posted if m["type"] == "config")
        self.assertNotIn("ffmpeg", config)   # never looked up on the UI thread
        items = {i["id"]: i for i in msg["items"]}
        self.assertEqual(items["ffmpeg"]["details"], "/opt/bin/ffmpeg")
        self.assertEqual(items["certificate"], {"id": "certificate", "state": "ok", "details": "bundled"})
        self.assertEqual(items["spooler"]["id"], "spooler")

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


class Requirements(Base):
    """Settings > Requirements: checked lazily after the page opens, cached, Check again, printer agent detection."""

    def setUp(self):
        super().setUp()
        self.runs = []
        for name, fn in (("check_ffmpeg", lambda s: self.runs.append(s) or service.requirements.item("ffmpeg", "missing")),
                         ("check_anycubic_slicer", lambda: service.requirements.item("anycubic_slicer", "missing"))):
            p = mock.patch.object(service.requirements, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(setattr, plugin, "_agent_seen", False)
        plugin._agent_seen = False   # Base made a KobraAgent; these tests start from "not detected"

    def page(self):
        page = plugin.KobraControlPage()
        page.posted = []
        return page

    def done(self, page, n=1):
        return wait(lambda: [m for m in page.posted if m.get("type") == "requirements" and not m["checking"]][n - 1:])[-1]

    def test_hello_checks_once_then_check_again_checks_again(self):
        page = self.page()
        page.on_message({"type": "hello", "id": 1})
        msg = self.done(page)
        self.assertEqual({i["id"]: i["state"] for i in msg["items"]},
                         {"ffmpeg": "missing", "anycubic_slicer": "missing", "printer_agents": "missing", "spoolman": "missing",
                          "certificate": "ok", "spooler": "missing"})
        page.on_message({"type": "hello", "id": 2})                 # cached
        self.assertEqual(self.runs, [""])
        page.on_message({"type": "check_requirements"})
        wait(lambda: len(self.runs) == 2)
        page.on_message({"type": "save_settings", "id": 3, "settings": {"printer_name": "Bench"}})   # any save checks again
        wait(lambda: len(self.runs) == 3)
        page.on_message({"type": "save_settings", "id": 4, "settings": {"ffmpeg_path": "/opt/ffmpeg"}})
        wait(lambda: len(self.runs) == 4)
        self.assertEqual(self.runs, ["", "", "", "/opt/ffmpeg"])

    def test_agent_detected_when_orca_made_one(self):
        plugin.KobraAgent()
        page = self.page()
        page.on_message({"type": "check_requirements"})
        items = {i["id"]: i["state"] for i in self.done(page)["items"]}
        self.assertEqual(items["printer_agents"], "ok")

    def test_agent_detected_from_the_selected_printer(self):
        for selected, want in (({"agent": "kobracontrol", "connection": "lan"}, True),
                               (type("Sel", (), {"agent": "kobracontrol"})(), True),
                               ({"agent": "moonraker"}, False), (None, False)):
            plugin._agent_seen = False
            with mock.patch.object(orca.host, "selected_printer", create=True, return_value=selected):
                self.assertEqual(plugin.note_agent(), want, selected)
        plugin._agent_seen = False
        with mock.patch.object(orca.host, "selected_printer", create=True, side_effect=RuntimeError("not on this host")):
            self.assertFalse(plugin.note_agent())
        self.assertFalse(hasattr(orca.host, "selected_printer"))   # a host without the call: "not detected"
        self.assertFalse(plugin.note_agent())

    def test_nothing_checked_at_registration(self):
        plugin._storage_dir, plugin._store = tempfile.mkdtemp(), None
        plugin.KobraControl().register_capabilities()
        plugin.KobraControlPage(), plugin.KobraAgent(), plugin.CheckConnection()   # nor on capability construction
        plugin.service()   # nor when the service starts: only a page asking checks
        time.sleep(0.2)
        self.assertEqual(self.runs, [])


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
        self.host_language("pl_PL")
        plugin.sync_language()
        self.assertEqual(i18n.language(), "pl")
        self.assertEqual(plugin.tr("Print started"), i18n.CATALOGUES["pl"]["Print started"])
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
    """Read-only G-code checks: an OrcaSlicer notification and a pointer to it in the Print dialog's last line,
    never a refusal, and the file goes to the printer as it is."""

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
        self.assertEqual(stages[-1][2], "Print started G-code warning: see the notification.")
        wait(lambda: orca.notifications)
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
        time.sleep(0.1)
        self.assertEqual(orca.notifications, [])

    def test_send_warns_without_thumbnail(self):
        self.connect()
        stages = []
        path, gcode = self.gcode_3mf("no_thumbnail.gcode")
        params = pa.PrintParams(project_name="cube", filename=path, plate_index=1)
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, lambda *a: stages.append(a), lambda: False, None), 0)
        self.assertEqual(self.fake.uploads[0]["data"], gcode)
        self.assertEqual(stages[-1][2], "File uploaded G-code warning: see the notification.")
        self.assertIn("G-code thumbnails", wait(lambda: orca.notifications)[0])

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

    def test_preset_read_goes_through_the_ui_thread(self):
        """The script's worker never reads the preset: queue_on_main runs the read on the UI thread; without a queue
        or an answer in time the check is skipped and the preset left alone."""
        readers = []
        bundle = self.bundle(gcode_skip_config_block="1", thumbnails="300x300/PNG")

        def read():
            readers.append(threading.current_thread().name)
            return bundle

        def queue(task):   # OrcaSlicer runs it later on the UI thread
            threading.Thread(target=task, name="ui").start()
        self.enterContext(mock.patch.object(orca.host, "preset_bundle", read))
        plugin._queue_on_main = queue
        found = run_off_main(plugin.preset_gcode_warnings)
        self.assertEqual(len(found), 1)
        self.assertIn("Skip G-code config block", found[0])
        self.assertEqual(readers, ["ui"])

        plugin._queue_on_main = None
        self.assertEqual(run_off_main(plugin.preset_gcode_warnings), [])
        late = []
        plugin._queue_on_main = late.append   # a UI thread that does not answer in time
        with mock.patch.object(plugin, "UI_WAIT", 0.05):
            self.assertEqual(run_off_main(plugin.preset_gcode_warnings), [])
        late[0]()   # it gets to it after the worker gave up: no read
        self.assertEqual(readers, ["ui"])

    def test_cancel_after_the_check_sends_nothing(self):
        self.connect()
        path, _ = self.gcode_3mf("good.gcode")
        params = pa.PrintParams(project_name="cube", filename=path, plate_index=1)
        calls = []
        self.assertEqual(self.agent.start_send_gcode_to_sdcard(params, None, lambda: calls.append(1) or True, None),
                         plugin.ERR_CANCELED)
        self.assertEqual(self.fake.uploads, [])




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


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AddOns(Base):
    """Settings switch the upload bridge on and off; it is off by default."""

    def setUp(self):
        super().setUp()
        self.addCleanup(plugin.stop_bridge)
        self.page = plugin.KobraControlPage()
        self.page.posted = []

    def config(self):
        return [m for m in self.page.posted if m.get("type") == "config"][-1]

    def save(self, **values):
        self.page.on_message({"type": "save_settings", "id": 5, "settings": values})
        return self.config()

    def test_off_by_default(self):
        self.page.on_load()
        self.addCleanup(self.page.on_unload)
        self.assertIsNone(plugin._bridge)
        self.page.on_message({"type": "hello", "id": 1})
        state = self.config()["bridge"]
        self.assertEqual((state["enabled"], state["running"], state["host"], state["key"]), (False, False, "127.0.0.1", ""))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, plugin.bridge.KEY_FILE)))   # no key made while off

    def test_bridge_switch_starts_and_stops_the_server(self):
        port = free_port()
        state = self.save(bridge_enabled=True, bridge_port=port)["bridge"]
        self.assertEqual((state["running"], state["port"], state["error"]), (True, port, ""))
        self.assertEqual(plugin._bridge.server.server_address, ("127.0.0.1", port))
        key_file = os.path.join(self.tmp, plugin.bridge.KEY_FILE)
        if os.name == "posix":
            self.assertEqual(os.stat(key_file).st_mode & 0o777, 0o600)
        self.assertNotIn(state["key"], json.dumps(plugin.get_store().raw()))   # not in settings.json
        running = plugin._bridge
        self.assertFalse(self.save(bridge_enabled=False)["bridge"]["running"])
        wait(lambda: running.server is None)

    def test_new_key_replaces_the_old_one(self):
        self.page.on_message({"type": "hello", "id": 1})
        old = self.config()["bridge"]["key"]
        self.page.on_message({"type": "bridge_new_key", "id": 6})
        self.assertNotEqual(self.config()["bridge"]["key"], old)
        self.assertEqual(plugin.bridge_key(), self.config()["bridge"]["key"])

    def test_port_in_use_is_reported(self):
        import socket
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            state = self.save(bridge_enabled=True, bridge_port=busy.getsockname()[1])["bridge"]
        self.assertFalse(state["running"])
        self.assertIn("could not be opened", state["error"])

    def test_quick_restart_binds_again_from_a_worker(self):
        """Off and on while the old bridge still holds the port: the UI thread never waits; a worker binds once the
        old one has let go and the page gets a new config."""
        port = free_port()
        self.save(bridge_enabled=True, bridge_port=port)
        old = plugin._bridge
        release = threading.Event()
        real_stop = old.stop
        old.stop = lambda: (release.wait(5), real_stop())   # an upload in progress keeps the port a little longer
        self.save(bridge_enabled=False)
        started = time.monotonic()
        state = self.save(bridge_enabled=True, bridge_port=port)["bridge"]
        self.assertLess(time.monotonic() - started, 0.5)   # the UI thread did not join the stopping thread
        self.assertFalse(state["running"])
        self.assertIn("waiting for the previous bridge", state["error"])
        posted = len(self.page.posted)
        release.set()
        # other threads (the Requirements check a save starts) post too: wait for the worker's own config, the one
        # that says the bridge runs, rather than for any new message
        wait(lambda: plugin._bridge is not None, 20)
        running = wait(lambda: next((m for m in self.page.posted[posted:] if m.get("type") == "config"
                                     and m["bridge"]["running"]), None), 20)
        self.assertEqual(running["bridge"]["error"], "")

    def test_unload_stops_the_bridge(self):
        self.save(bridge_enabled=True, bridge_port=free_port())
        running = plugin._bridge
        self.page.on_load()
        self.page.on_unload()
        self.assertIsNone(plugin._bridge)
        wait(lambda: running.server is None)

    def test_load_asks_for_loopback_only_when_on(self):
        with mock.patch.object(plugin, "known_hosts", return_value=["192.168.1.5"]):
            orca.permissions.clear()
            plugin.KobraControl().register_capabilities()
            self.assertNotIn("http://127.0.0.1", orca.permissions[-1]["network"])
            plugin.get_store().update({"bridge_enabled": True})
            plugin.KobraControl().register_capabilities()
            self.assertIn("http://127.0.0.1", orca.permissions[-1]["network"])

    def test_upload_with_no_target_reads_presets_on_the_ui_thread(self):
        """The bridge's thread never reads presets itself: with no printer selected yet it has the UI thread do it
        (queue_on_main), as the Check script does."""
        readers, real = [], plugin.preset_hints

        def hints():
            readers.append(threading.current_thread().name)
            return real()

        def queue(task):
            threading.Thread(target=task, name="ui").start()
        self.enterContext(mock.patch.object(plugin, "preset_hints", hints))
        self.addCleanup(setattr, plugin, "_queue_on_main", plugin._queue_on_main)
        plugin._queue_on_main = queue
        self.fake.reply("file", "listLocal", {"records": []}, code=200)
        path = os.path.join(self.tmp, "up.part")
        with open(path, "wb") as f:
            f.write(b"G90\nM83\nG1 X1\n")
        plugin._service.target = None
        result = run_off_main(lambda: plugin._bridge_upload(path, "cube.gcode", 1, False))
        self.assertEqual(result, {"name": "cube.gcode"})
        self.assertTrue(readers)
        self.assertEqual(set(readers), {"ui"})
        self.assertEqual(self.fake.uploads[-1]["filename"], "cube.gcode")


if __name__ == "__main__":
    unittest.main()
