"""Test double: a fake `orca` module (from u1control tests/fakes.py), plus `orca.printer_agent` modelled on
OrcaSlicer v2.5.0 PrinterAgentPluginCapability.cpp (enums, AgentInfo, param classes) and the wiki's
printer_agent.md (the base class and its host callbacks)."""

import json
import sys
import tempfile
import types


class _Fields:
    _defaults = {}

    def __init__(self, **kw):
        for key, value in {**self._defaults, **kw}.items():
            setattr(self, key, value)


class AgentInfo(_Fields):
    def __init__(self, id="", name="", version="", description=""):
        self.id, self.name, self.version, self.description = id, name, version, description


class PrinterConnectionParams(_Fields):
    _defaults = {"dev_id": "", "host": "", "port": "", "username": "", "password": "", "use_ssl": False, "ca_file": ""}


class PrintParams(_Fields):
    _defaults = {"dev_id": "", "task_name": "", "project_name": "", "preset_name": "", "filename": "",
                 "config_filename": "", "plate_index": 1, "dst_file": "", "dev_ip": "", "dev_name": "",
                 "ams_mapping": "", "ams_mapping2": "", "ams_mapping_info": "", "connection_type": "lan",
                 "password": "", "username": "", "task_bed_leveling": False, "task_flow_cali": False,
                 "task_vibration_cali": False, "task_layer_inspect": False, "task_record_timelapse": False,
                 "task_use_ams": True, "task_bed_type": "", "auto_bed_leveling": 0}


class DetectResult(_Fields):
    _defaults = {k: "" for k in ("result_msg", "command", "dev_id", "model_id", "dev_name", "version", "bind_state",
                                 "connect_type")}


class _Enum:
    def __init__(self, name, *members):
        self._name = name
        for i, m in enumerate(members):
            setattr(self, m, "%s.%s" % (name, m))


def printer_agent_module():
    class PrinterAgentBase:
        def __init__(self):
            pass

        def get_type(self):
            return "printer-connection"

    return types.SimpleNamespace(
        PrinterAgentBase=PrinterAgentBase, AgentInfo=AgentInfo, PrinterConnectionParams=PrinterConnectionParams,
        PrintParams=PrintParams, DetectResult=DetectResult,
        FilamentSyncMode=_Enum("FilamentSyncMode", "None_", "Subscription", "Pull"),
        CameraStreamMode=_Enum("CameraStreamMode", "None_", "HTTP", "HTTPS", "HTTP_SNAPSHOT", "RTSP"))


class FakeWindow:
    def __init__(self, on_message, on_submit, answer):
        self.on_message, self.on_submit, self.answer, self.open, self.posted = on_message, on_submit, answer, True, []
        on_message({"ready": True})
        on_submit(answer)

    def is_open(self):
        return self.open

    def close(self):
        self.open = False

    def post(self, data):
        self.posted.append(data)


def install_orca(answer=None, preset=None, filament_names=(), filament_meta=None, bundle_ids=(), storage=None):
    """Register a fake `orca` module. answer: what the print setup window submits; by default Cancel
    ({"cancelled": True}), so a test prints through the window only when it says what to answer ({}: Start print)."""
    orca = types.ModuleType("orca")
    orca.windows = []

    class Base:
        _stored = None

        def get_config(self):
            return json.dumps(self._stored if self._stored is not None else self.get_default_config())

        def save_config(self, text):
            self._stored = json.loads(text)
            return True

        def get_default_config(self):
            return {}

        def post_message(self, data):
            self.posted = getattr(self, "posted", []) + [data]

    class Result:
        def __init__(self, status, message=""):
            self.status, self.message = status, message

    orca.ExecutionResult = types.SimpleNamespace(
        success=lambda message="", data="": Result("success", message),
        skipped=lambda message="": Result("skipped", message),
        failure=lambda status, message, data="": Result("failure", message))
    orca.PluginResult = types.SimpleNamespace(FatalError="fatal", RecoverableError="recoverable")
    orca.LifecycleEvent = types.SimpleNamespace(DeviceSelected=1, PresetSelected=2, ProjectOpened=3)
    orca.printer_agent = printer_agent_module()
    orca.permissions = []
    orca.slicing = types.SimpleNamespace(SlicingPipelineCapabilityBase=Base,
                                         Step=types.SimpleNamespace(psGCodePostProcess="post", psSkirtBrim="brim"))
    orca.pages = types.SimpleNamespace(PagesPluginCapabilityBase=Base)
    orca.script = types.SimpleNamespace(ScriptPluginCapabilityBase=Base)
    orca.base = object
    orca.registered = []
    orca.plugin = lambda cls: cls
    orca.register_capability = orca.registered.append
    orca.request_permissions = lambda **kw: orca.permissions.append(kw)

    def create_window(html, title="", width=0, height=0, on_message=None, on_close=None, on_submit=None, style=None):
        w = FakeWindow(on_message, on_submit, answer if answer is not None else {"cancelled": True})
        w.html = html
        orca.windows.append(w)
        return w

    preset = preset or {}
    filament_meta = filament_meta or {}
    names = list(filament_names)

    class FPreset:
        def __init__(self, name):
            self.name = name
            self.bundle_id = filament_meta.get(name, {}).get("bundle_id", "")
            self.filament_id = filament_meta.get(name, {}).get("filament_id", "")
            self.is_compatible = filament_meta.get(name, {}).get("is_compatible", True)
            self.file = filament_meta.get(name, {}).get("file", "")

        def is_user(self):
            return filament_meta.get(self.name, {}).get("is_user", False)

        def config_value(self, key):
            return filament_meta.get(self.name, {}).get(key)

    class Preset:
        name = preset.get("name", "Anycubic Kobra X (0.4 nozzle)")
        file = ""

        def config_value(self, key):
            return preset.get(key)

    bundle = types.SimpleNamespace(current_printer_preset=lambda: Preset(),
                                   current_process_preset=lambda: Preset(),
                                   full_config_value=lambda k: preset.get(k),
                                   filaments=types.SimpleNamespace(preset_names=lambda: list(filament_names),
                                                                   size=lambda: len(names), preset=lambda i: FPreset(names[i])))
    orca.filament_calls = []
    orca.process_calls, orca.notifications = [], []

    class Tx:
        def __init__(self, slot, name):
            self.slot, self.name, self.values = slot, name, {}

        def set(self, key, value):
            self.values[key] = value

        def commit(self):
            orca.filament_calls.append((self.slot, self.name, self.values))

    def begin_update(slot, name):
        if slot == 99:
            raise RuntimeError("no such slot")
        return Tx(slot, name)

    class ProcessTx(Tx):
        def commit(self):
            orca.process_calls.append((self.name, self.values))
            preset["slicing_pipeline_plugin"] = self.values.get("slicing_pipeline_plugin")

    store_dir = storage or tempfile.mkdtemp()
    orca.host = types.SimpleNamespace(
        preset=types.SimpleNamespace(filament=types.SimpleNamespace(begin_update=begin_update),
                                     process=types.SimpleNamespace(begin_update=lambda name: ProcessTx(0, name)),
                                     bundles=types.SimpleNamespace(list_ids=lambda: list(bundle_ids))),
        ui=types.SimpleNamespace(create_window=create_window, WINDOW_MODAL=1, message=lambda *a, **k: "yes",
                                 NotificationLevel=types.SimpleNamespace(RegularNotificationLevel=1),
                                 push_notification=lambda level, text, **k: orca.notifications.append(text)),
        preset_bundle=lambda: bundle, plugin=types.SimpleNamespace(storage=lambda: store_dir))
    sys.modules["orca"] = orca
    return orca


def load_wheel(path):
    """Import the built wheel as package `kobracontrol` (zipimport) with a fresh module set; returns its namespace.
    Call after install_orca()."""
    import importlib
    for name in [n for n in sys.modules if n == "kobracontrol" or n.startswith("kobracontrol.")]:
        del sys.modules[name]
    sys.path[:] = [p for p in sys.path if not p.endswith(".whl")]
    sys.path.insert(0, str(path))
    sys.path_importer_cache.pop(str(path), None)
    importlib.invalidate_caches()
    return vars(importlib.import_module("kobracontrol"))
