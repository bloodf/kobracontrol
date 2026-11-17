"""What Kobra Control needs and cannot install itself, for Settings > Requirements. Free of the `orca` module.

    ffmpeg            the tab's camera (missing: the camera is not started at all)
    anycubic_slicer   only Find certificate reads it; the certificate is bundled (missing: that search is off)
    printer_agents    OrcaSlicer's "Use printer agents instead of print hosts": Print/Send and the Device tab
                      ("missing" here means "not detected": a plugin can't read the preference itself)
    spoolman          slot <-> spool links and usage booking (missing: those actions are off)

Each item is {"id", "state": "ok" | "missing" | "unknown", "details"}. The two file checks run on a thread of their
own, never at import or registration and never on OrcaSlicer's UI thread, and are kept until Check again or a
Settings save. Checker() itself does no I/O. The other two cost nothing and are read whenever the message is built."""

import os
import threading

import camera
import certs

OK, MISSING, UNKNOWN = "ok", "missing", "unknown"
FILE_CHECKS = ("ffmpeg", "anycubic_slicer")


def item(id_, state, details=""):
    return {"id": id_, "state": state, "details": details}


def check_ffmpeg(setting=""):
    path = camera.find_ffmpeg(setting)
    return item("ffmpeg", OK if path else MISSING, path or "")


def check_anycubic_slicer(locations=None):
    """Installed when one of its usual install paths exists: a stat only, nothing is read (no permission asked)."""
    refused = False
    for path in certs.default_locations() if locations is None else locations:
        try:
            os.stat(path)
            return item("anycubic_slicer", OK, path)
        except PermissionError:
            refused = True
        except (OSError, ValueError):
            pass
    return item("anycubic_slicer", UNKNOWN if refused else MISSING)


class Checker:
    """The cached file checks. ensure() starts a check on its own thread unless one is cached (or running) for the
    same ffmpeg setting; force (Check again) always does. on_done() runs on that thread once the results are in."""

    def __init__(self, on_done=lambda: None, log=print):
        self.on_done, self.log = on_done, log
        self._lock = threading.Lock()
        self._gen, self._done, self._setting, self._results = 0, 0, None, None

    def ensure(self, ffmpeg_setting="", force=False):
        with self._lock:
            if not force and self._setting == ffmpeg_setting:
                return
            # The last results stay until the new ones are in: a re-check never turns a running camera off and on.
            self._gen += 1
            gen, self._setting = self._gen, ffmpeg_setting
        threading.Thread(target=self._run, args=(gen, ffmpeg_setting), name="kobracontrol-requirements",
                         daemon=True).start()

    def _run(self, gen, setting):
        results = {}
        for id_, check in (("ffmpeg", lambda: check_ffmpeg(setting)), ("anycubic_slicer", check_anycubic_slicer)):
            try:
                results[id_] = check()
            except Exception as e:   # a check that fails says "unknown", never kills the thread
                self.log("kobracontrol: requirement %s not checked (%r)" % (id_, e))
                results[id_] = item(id_, UNKNOWN)
        with self._lock:
            if gen != self._gen:   # a newer check started meanwhile: its answer is the one that counts
                return
            self._results, self._done = results, gen
        self.on_done()

    def mark_missing(self, id_):
        """A requirement found gone while in use (ffmpeg removed mid-session): missing until Check again or a save."""
        with self._lock:   # also before the first check finished: the camera may have started on its own lookup
            self._results = {**(self._results or {}), id_: item(id_, MISSING)}
        self.on_done()

    @property
    def checking(self):
        with self._lock:
            return self._setting is not None and self._done != self._gen

    def items(self):
        """The file checks' items: the last results (kept while a re-check runs), "unknown" before the first."""
        with self._lock:
            results = self._results or {}
        return [results.get(id_) or item(id_, UNKNOWN) for id_ in FILE_CHECKS]

    def ffmpeg(self):
        """The ffmpeg the last check found, "" when it is missing, None before any answer (the camera then looks
        for ffmpeg itself, once). A re-check keeps the last answer until its own is in."""
        with self._lock:
            found = (self._results or {}).get("ffmpeg")
        if found is None or found["state"] == UNKNOWN:
            return None
        return found["details"] if found["state"] == OK else ""


def message(checker, agent_seen, spoolman_url):
    return {"type": "requirements", "checking": checker.checking,
            "items": checker.items() + [item("printer_agents", OK if agent_seen else MISSING),
                                        item("spoolman", OK if spoolman_url else MISSING, spoolman_url or "")]}
