"""OrcaSlicer's Print and Send for the printer agent: the plate's G-code out of the sliced .3mf, the upload,
and print/start with the trays the user chose. Mixed into service.Service, which provides connection(),
_data(conn), log and remember_job (usage.UsageMixin). Free of the `orca` module."""

import contextlib
import os
import re
import secrets
import time
import xml.etree.ElementTree as ET
import zipfile

import ace
import printsetup
import bridge
import connection
import gcode_check
import kobra
from i18n import lazy, tr

CONNECT_WAIT = 10.0             # s a print job waits for the session
GCODE_MAX = 1024 ** 3           # BAMBU_NETWORK_ERR_PRINT_LP_FILE_OVER_SIZE: 1 GB
SLICE_INFO_MAX = 8 * 1024 * 1024 # Metadata/slice_info.config read only up to this declared size
PENDING_TTL = 600.0             # s an Upload-and-Print from the bridge waits for Start in the tab
GONE = lazy("that print request is no longer waiting; nothing was started")


def remote_name(name):
    """A printer file name from a job name: safe characters only, ending in .gcode."""
    base = str(name or "")
    base = re.sub(r"(\.(gcode|3mf))+$", "", base, flags=re.I)   # PrintJob sends "<name>.gcode.3mf"
    base = re.sub(r"[^\w .()+-]", "_", base).strip(" .") or "kobracontrol"
    return base[:120] + ".gcode"


DENIED_READ = lazy("OrcaSlicer did not let kobracontrol read the sliced file %s. Allow kobracontrol to read %s in "
               "Plugins > Permissions, then print again.")


def _open_job_file(path):
    try:
        return open(path, "rb")
    except PermissionError:   # OrcaSlicer's audit hook: no read grant for this folder (never "not a zip")
        raise kobra.KobraError(tr(DENIED_READ) % (path, os.path.join(os.path.dirname(path), "*")), code="denied") from None
    except OSError as e:
        raise kobra.KobraError(tr("cannot read the sliced file %s (%s)") % (path, e.strerror or e)) from None


@contextlib.contextmanager
def plate_source(path, plate_index=1):
    """(readable binary file, size, {filament index: grams}) for a sliced .3mf (its Metadata/plate_<n>.gcode
    member, streamed straight from the archive) or a plain .gcode file. No temporary file is written: OrcaSlicer
    denies file creation outside the plugin's storage on a job thread. The member is chosen by its exact name and
    its declared size is checked before anything is read."""
    with _open_job_file(path) as raw:
        if not zipfile.is_zipfile(raw):
            raw.seek(0)
            size = os.fstat(raw.fileno()).st_size
            if size > GCODE_MAX:
                raise kobra.KobraError(tr("the G-code is larger than 1 GB"))
            yield raw, size, {}
            return
        plate = int(plate_index) if str(plate_index).isdigit() and int(plate_index) > 0 else 1
        with zipfile.ZipFile(raw) as z:
            try:
                info = z.getinfo("Metadata/plate_%d.gcode" % plate)
            except KeyError:
                raise kobra.KobraError(tr("the sliced file has no G-code for plate %d: slice it first") % plate) from None
            if info.file_size > GCODE_MAX:
                raise kobra.KobraError(tr("the G-code is larger than 1 GB"))
            weights = _plate_weights(z, plate)
            with z.open(info) as member:
                yield member, info.file_size, weights


def _plate_weights(z, plate):
    """{0-based project filament index: grams} from Metadata/slice_info.config, {} when absent."""
    try:
        info = z.getinfo("Metadata/slice_info.config")
        if info.file_size > SLICE_INFO_MAX:   # declared size checked before reading; larger counts as absent
            return {}
        root = ET.fromstring(z.read(info))
    except (KeyError, ET.ParseError, zipfile.BadZipFile, ValueError, RecursionError):
        return {}
    for p in root.iter("plate"):
        index = next((m.get("value") for m in p.iter("metadata") if m.get("key") == "index"), None)
        if index == str(plate):
            out = {}
            for f in p.iter("filament"):
                try:
                    out[int(f.get("id")) - 1] = float(f.get("used_g") or 0)
                except (TypeError, ValueError):
                    continue
            return out
    return {}


PRINT_OPTIONS = ("auto_leveling", "vibration_compensation", "flow_calibration", "timelapse")


def supported_task(view, task):
    """The print options, with the ones info/report `features` marks unsupported turned off. A printer that
    has not reported its features yet keeps the user's choice."""
    features = view.get("features") or {}
    task = dict(task or {})
    for option, feature in (("auto_leveling", "auto_leveling_support"),
                            ("vibration_compensation", "vibration_compensation_support"),
                            ("flow_calibration", "flow_calibration_support"),
                            ("timelapse", "camera_timelapse_support")):
        if features.get(feature) is False:
            task[option] = False
    return task


class JobsMixin:
    def ready(self, host, timeout=CONNECT_WAIT):
        """The connected Connection for `host`, waiting up to timeout; KobraError when it does not connect."""
        conn = self.connection(host)
        if not conn.connected:
            conn.retry()
            conn.wait_connected(timeout)
        if not conn.connected or conn.printer is None:
            cls = connection.NoCertificate if conn.no_certificate else kobra.KobraError
            raise cls(conn.error or tr("the printer at %s did not answer") % host)
        return conn

    def _upload(self, conn, filename, source, size, progress, cancelled):
        upload_url = conn.view()["upload_url"]
        if not upload_url:
            conn.printer.query_info()
            upload_url = conn.view()["upload_url"]
        if not upload_url:
            raise kobra.KobraError(tr("the printer has not announced its upload address yet; try again"))
        conn.printer.upload(filename, source, upload_url, size=size, progress=progress, cancelled=cancelled)

    def check_gcode(self, path, plate_index=1):
        """Translated warnings about the job's G-code (gcode_check.inspect), each logged. Read-only and never
        fails: a file that can't be read gives [] here and its error from the upload."""
        try:
            with plate_source(path, plate_index) as (source, size, _):
                found = gcode_check.inspect(source, size)
        except Exception as e:
            self.log("kobracontrol: G-code not checked: %s" % e)
            return []
        warnings = [tr(text) for text in found]
        for text in warnings:
            self.log("kobracontrol: G-code check: " + text)
        return warnings

    def send_file(self, host, path, name, plate_index=1, progress=None, cancelled=None):
        """Upload only (OrcaSlicer's Send): the plate's G-code goes to the printer's storage; returns its name."""
        return self._send(host, path, name, plate_index, progress, cancelled)[0]

    def _send(self, host, path, name, plate_index=1, progress=None, cancelled=None):
        """send_file -> (name, bytes sent)."""
        conn = self.ready(host)
        filename = remote_name(name or os.path.basename(path))
        self._forget_pending(filename)   # a waiting bridge print of that name would start this file instead
        with plate_source(path, plate_index) as (source, size, _):
            self._upload(conn, filename, source, size, progress, cancelled)
        return filename, size

    def print_job(self, host, path, plate_index=1, name="", tray_ids=(), filaments=(), task=None, progress=None,
                  cancelled=None, stage=None, auto_feed=None, notice=None):
        """OrcaSlicer's Print: upload the plate's G-code, then print/start with the chosen trays.
        tray_ids[i]: Bambu tray id for project filament i (-1 unused); filaments[i]: {"colour", "type"};
        task: {"auto_leveling", "vibration_compensation", "flow_calibration", "timelapse"}; stage(name) is told "upload"
        then "start". auto_feed: True/False sets every ACE's auto feed right before print/start, once the printer and
        slots were checked again (the print setup's choice), None leaves it; when that fails the print still starts and
        notice(text) says so."""
        conn = self.ready(host)
        mapping, used = self._job_mapping(conn, tray_ids, filaments)
        filename = remote_name(name or os.path.basename(path))
        self._forget_pending(filename)
        with plate_source(path, plate_index) as (source, size, weights):
            stage and stage("upload")
            self._upload(conn, filename, source, size, progress, cancelled)
        if cancelled and cancelled():
            raise kobra.Cancelled(tr("print cancelled; the file stays on the printer"))
        stage and stage("start")
        with conn.start_lock:   # the idle check and print/start of one job at a time (tab file prints too)
            mapping, used = self._job_mapping(conn, tray_ids, filaments)   # the slots may have changed meanwhile
            task = supported_task(conn.view(), task)
            if auto_feed is not None:
                self._set_auto_feed(host, auto_feed, notice)
            # raises when the printer ends the task right after starting it (kobra.start_print watches)
            conn.printer.start_print(kobra.print_file_payload(filename, size, mapping, task))
        self._remember(host, filename, used, weights)
        return filename

    def _set_auto_feed(self, host, on, notice=None):
        try:
            self.call(host, "assist", option="autoFeed", on=bool(on))
        except Exception as e:
            self.log("kobracontrol: ACE auto feed not changed (%s); the print goes on" % e)
            if notice:
                notice(tr("ACE auto feed was not changed (%s); the print starts anyway") % e)

    def _job_mapping(self, conn, tray_ids, filaments):
        """(ams_box_mapping, {filament index: global slot}); refuses unless the printer is idle and every chosen
        tray is usable and holds the filament's material family (printsetup.refuse_other_material). With no tray chosen at all, the loaded slots are used in order (Kobralink's auto mapping)."""
        data = self._data(conn)
        if not data["connected"]:
            raise kobra.KobraError(conn.error or tr("the printer is not connected"))
        if not data["can"]["print"]:
            raise kobra.KobraError(tr("the printer is %s; nothing was sent") % tr(data["state"]))
        trays = [int(t) for t in tray_ids or []]
        if not any(t >= 0 for t in trays):
            loaded, _ = ace.select_loaded_slots_for_print(data["slots"], data["mode"])
            return ace.build_auto_ams_box_mapping(loaded, data["mode"]), {s["global_index"]: s["global_index"] for s in loaded}
        printsetup.refuse_other_material(trays, list(filaments or []), data["slots"], data["mode"])
        mapping, problems = ace.mapping_from_trays(trays, list(filaments or []), data["slots"], data["mode"])
        if problems:
            raise kobra.KobraError("; ".join(problems) + tr("; nothing was sent"))
        used = {i: ace.slot_for_tray(t, data["slots"])["global_index"] for i, t in enumerate(trays) if t >= 0}
        return mapping, used

    def _remember(self, host, filename, used, weights):
        filaments = [{"index": i, "weight": g} for i, g in weights.items() if g]
        if not filaments:
            return
        try:
            self.remember_job(filename, used, filaments, host=host)
        except Exception as e:   # usage tracking must never fail a print that started
            self.log("kobracontrol: usage not tracked for %s: %r" % (filename, e))

    # Upload-and-Print bridge (bridge.py): the upload is stored on the printer at once; a print waits for Start in
    # the tab, so nothing starts without the user at the plugin. -----------------------------------------------------
    bridge_pending = None   # {"id", "name", "host", "task", "at"}

    def bridge_upload(self, path, filename, plate_index, start, task):
        """bridge.Bridge's on_upload: the file to the selected printer through Send's own path; with `start`, refused
        unless the printer is idle, then kept as the one pending print. Returns OrcaSlicer's answer."""
        with self.lock:
            target = self.target
        if target is None or not target.host:
            raise bridge.Refused(503, tr("no Kobra X selected in Kobra Control; nothing was sent"))
        name = remote_name(filename)
        try:
            data = self._data(self.ready(target.host))
            if start and not data["can"]["print"]:
                raise bridge.Refused(409, tr("the printer is %s; nothing was sent") % tr(data["state"]))
            if data["state"] in ("printing", "paused") and data.get("filename") == name:
                raise bridge.Refused(409, tr("%s is the file being printed; nothing was sent") % name)
            name, size = self._send(target.host, path, filename, plate_index)
        except kobra.KobraError as e:
            raise bridge.Refused(502, str(e)) from None
        if not start:
            return {"name": name}
        pending = {"id": secrets.token_hex(8), "name": name, "size": size, "host": target.host,
                   "task": {k: bool((task or {}).get(k)) for k in PRINT_OPTIONS}, "at": time.time()}
        with self.lock:
            self.bridge_pending = pending
        text = tr("%s is on the printer. Start the print in Kobra Control.") % name
        self._notice(text)
        return {"name": name, "pending": True, "message": text}

    def _forget_pending(self, name):
        with self.lock:
            if self.bridge_pending and self.bridge_pending["name"] == name:
                self.bridge_pending = None

    def bridge_pending_for(self, host):
        """The pending print for `host` as the page sees it, None when there is none (or it waited too long)."""
        with self.lock:
            p = self.bridge_pending
            if p and time.time() - p["at"] > PENDING_TTL:
                self.bridge_pending = p = None
        return {"id": p["id"], "name": p["name"], "at": p["at"]} if p and p["host"] == host else None

    def cmd_bridge_start(self, id):
        """The tab's Start: the pending file through the Files tab's print path (idle check and print/start)."""
        conn = self._conn()
        pending = self.bridge_pending
        if not pending or pending["id"] != id or self.bridge_pending_for(conn.host) is None:
            raise kobra.KobraError(tr(GONE))
        listed = next((f for f in self._printer().list_files() if f.get("filename") == pending["name"]), None)
        # listLocal "size" is the file's bytes (tests/kobra_captures.py FILE_LISTLOCAL); 0 means not reported
        reported = int(round(listed.get("size") or 0)) if listed else -1
        if listed is None or (reported and reported != pending["size"]):   # deleted or replaced meanwhile
            self._forget_pending(pending["name"])
            raise kobra.KobraError(tr("%s on the printer is not the file OrcaSlicer sent; nothing was started") % pending["name"])
        result = self.cmd_file_print(pending["name"], **pending["task"])
        with self.lock:
            if self.bridge_pending is pending:
                self.bridge_pending = None
        return result

    def cmd_bridge_cancel(self, id):
        """The tab's Cancel: forget the pending print; the file stays on the printer."""
        with self.lock:
            if self.bridge_pending and self.bridge_pending["id"] == id:
                self.bridge_pending = None
        return {"cancelled": True}
