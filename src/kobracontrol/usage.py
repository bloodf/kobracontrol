"""Filament use of the prints kobracontrol sent, waiting to be booked in Spoolman. Free of the `orca` module.

A job is identified by printer (normalized address) and file path, plus an id of its own. It is booked once its
printer reports that same file printing and then finished (`kobra.State.view()` states "printing"/"paused",
then "finished"; "cancelled" and "error" book nothing). The service feeds every status sample to
UsageMixin.track(); every decision is taken under one lock, so only one thread books a job. Spoolman's "use"
call adds weight: a call that fails may or may not have been applied, so it is never repeated by itself; it is
listed as unconfirmed instead.

Jobs are kept in a file in the plugin's storage folder (LedgerStore), rewritten whole after every change, so
closing OrcaSlicer no longer forgets them. A slot's use is saved as "sending" before its Spoolman call: one
still "sending" when the file is read again (OrcaSlicer closed or crashed during the call) may have been
applied, so it becomes unconfirmed, never sent again. A job that had been seen printing is only booked after
the restart if kobracontrol sees it printing again; seen finished, or another file, it is unconfirmed (it
can't tell that print from a later one).
"""

import json
import os
import threading
import time
import uuid

import ace
import settings
import spoolman as sm
from i18n import tr

JOB_TTL = 3 * 24 * 3600.0       # a job that never finishes is dropped after this long
RETRY_AFTER = 60.0              # slots not yet attempted (Spoolman unreachable before any write) retry after this
MAX_UNCONFIRMED = 20
MAX_ACKNOWLEDGED = 50           # entries the user marked as checked in Spoolman, kept for audit
MAX_JOBS = 200
LEDGER_VERSION = 1
ACTIVE = ("printing", "paused")
COMPLETE = "finished"
FAILED = ("cancelled", "error")
TERMINAL = (COMPLETE,) + FAILED


def job_key(filename):
    """Normalized printer path of a job: 'gcodes/Dir/Part.GCode' and 'dir/part.gcode' match; folders count."""
    path = str(filename or "").replace("\\", "/").strip().strip("/").lower()
    return path[len("gcodes/"):] if path.startswith("gcodes/") else path


def printer_ident(host):
    """One spelling per printer address: '192.168.1.5' and 'http://192.168.1.5/' are the same printer."""
    text = str(host or "").strip().lower()
    text = text.split("://", 1)[-1]
    return text.split("/", 1)[0]


class Job:
    def __init__(self, host, path, per_slot, bindings=None, printer_name="", spoolman_url="", report=True,
                 now=None, job_id=None):
        self.id = job_id or uuid.uuid4().hex
        self.host, self.path = host, job_key(path)
        self.per_slot = dict(per_slot)             # slot -> grams still to book
        self.bindings = dict(bindings) if bindings else None   # slot -> spool id when sent, if known
        self.printer_name, self.spoolman_url, self.report = printer_name, spoolman_url, report
        self.created = time.time() if now is None else now
        self.armed = False        # seen printing this file after it was registered
        self.saw_other = False    # seen any other state or file after it was registered
        self.retry_at = None      # set when part of the job waits for a new attempt
        self.restored = False     # read back from disk and not observed since
        self.sending = {}         # slot -> grams whose Spoolman call may be in flight
        self.booking = False      # taken out to be booked (still saved until that ends)

    @property
    def key(self):
        return (self.host, self.path)

    def to_dict(self):
        return {"id": self.id, "host": self.host, "path": self.path,
                "per_slot": {str(h): g for h, g in self.per_slot.items()},
                "bindings": None if self.bindings is None else {str(h): s for h, s in self.bindings.items()},
                "printer_name": self.printer_name, "spoolman_url": self.spoolman_url, "report": self.report,
                "created": self.created, "armed": self.armed, "saw_other": self.saw_other, "retry_at": self.retry_at,
                "sending": {str(h): g for h, g in self.sending.items()}, "booking": self.booking}

    @classmethod
    def from_dict(cls, d):
        """A job read back from disk; raises ValueError/TypeError/KeyError on a malformed entry."""
        slots = lambda m: {int(h): float(g) for h, g in (m or {}).items() if 0 <= int(h) < sm.MAX_SLOTS}  # noqa: E731
        bindings = d.get("bindings")
        job = cls(str(d["host"]), str(d["path"]), slots(d["per_slot"]),
                  {int(h): int(s) for h, s in bindings.items()} if isinstance(bindings, dict) else None,
                  str(d.get("printer_name") or ""), str(d.get("spoolman_url") or ""), bool(d.get("report", True)),
                  float(d["created"]), str(d["id"]))
        job.armed, job.saw_other = bool(d.get("armed")), bool(d.get("saw_other"))
        job.retry_at = float(d["retry_at"]) if d.get("retry_at") is not None else None
        job.sending = slots(d.get("sending"))
        job.booking = bool(d.get("booking"))
        job.restored = True
        return job


class LedgerStore:
    """The ledger file: {"version": 1, "jobs": [...], "unconfirmed": [...], "acknowledged": [...]}, replaced whole
    on every save. "acknowledged" (optional, older files have none) keeps unconfirmed entries the user marked as
    checked in Spoolman, with the time they did so: a local note only, nothing is sent to Spoolman for it."""

    def __init__(self, path, log=print):
        self.path, self.log = path, log

    def load(self):
        """(jobs, unconfirmed, notice, acknowledged). A file that can't be read is set aside, never overwritten."""
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return [], [], "", []
        except (OSError, ValueError) as e:
            return [], [], self._set_aside(tr("unreadable (%s)") % e), []
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            return [], [], self._set_aside(tr("of an unknown format")), []
        jobs, bad = [], 0
        for entry in data.get("jobs") if isinstance(data.get("jobs"), list) else []:
            try:
                jobs.append(Job.from_dict(entry))
            except (KeyError, TypeError, ValueError, AttributeError):
                bad += 1
        raw = data.get("unconfirmed") if isinstance(data.get("unconfirmed"), list) else []
        unconfirmed = [u for u in raw if isinstance(u, dict)]
        bad_entries = len(raw) - len(unconfirmed)
        acked = data.get("acknowledged") if isinstance(data.get("acknowledged"), list) else []
        acknowledged = [u for u in acked if isinstance(u, dict)][-MAX_ACKNOWLEDGED:]
        notes = []
        if bad:
            notes.append(tr("%d unreadable job(s) in %s were skipped") % (bad, self.path))
        if bad_entries:
            notes.append((tr("%d unreadable unconfirmed entry in %s were skipped; check Spoolman for prints that finished "
                             "meanwhile") if bad_entries == 1 else
                          tr("%d unreadable unconfirmed entries in %s were skipped; check Spoolman for prints that finished "
                             "meanwhile")) % (bad_entries, self.path))
        return jobs, unconfirmed[-MAX_UNCONFIRMED:], "; ".join(notes), acknowledged

    def _set_aside(self, why):
        aside = "%s.bad-%d" % (self.path, int(time.time()))
        try:
            os.replace(self.path, aside)
        except OSError as e:
            return tr("the print ledger %s is %s and could not be moved aside (%s); it was not used") % (self.path, why, e)
        return tr("the print ledger was %s; it was kept as %s and not used. Check Spoolman for prints that "
                  "finished meanwhile.") % (why, aside)

    def save(self, jobs, unconfirmed, acknowledged=()):
        """Raises OSError when the file can't be written."""
        folder = os.path.dirname(self.path) or "."
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, ".%s.%d.tmp" % (os.path.basename(self.path), threading.get_ident()))
        doc = {"version": LEDGER_VERSION, "jobs": [j.to_dict() for j in jobs], "unconfirmed": unconfirmed,
               "acknowledged": list(acknowledged)}
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise


class Ledger:
    def __init__(self, store=None):
        self.lock = threading.Lock()
        self.store = store
        self.jobs = {}
        self.unconfirmed = []     # [{"id", "at", "spool", "grams", "slot", "file", "error", "job", "printer", "spoolman"}]
        self.acknowledged = []    # the same entries plus "acknowledged_at", once the user checked them in Spoolman
        self.seen = {}            # host -> time.monotonic() of the last observation
        self.save_error = ""
        self.restore_notice = ""
        if store is not None:
            jobs, self.unconfirmed, self.restore_notice, self.acknowledged = store.load()
            for job in jobs:
                for slot, grams in sorted(job.sending.items()):   # closed or crashed during this call
                    self.unconfirmed.append(_unconfirmed(job, slot, job.per_slot.pop(slot, grams),
                                                         tr("OrcaSlicer closed while this was being recorded")))
                job.sending = {}
                key = ("retry", job.id) if job.retry_at is not None else ("restored", job.id) if job.booking else job.key
                job.booking = False   # read back mid-booking: waits again, and restored + armed decides it
                if job.per_slot:
                    self.jobs[key] = job
            self.unconfirmed = [_with_id(u) for u in self.unconfirmed[-MAX_UNCONFIRMED:]]
            self._save()

    def _save(self):   # caller holds self.lock (or is __init__)
        """Write the ledger; False when it couldn't be (the change stays in memory, and is reported)."""
        if self.store is None:
            return True
        try:
            self.store.save(list(self.jobs.values()), self.unconfirmed, self.acknowledged)
        except OSError as e:
            self.save_error = tr("can't save the print ledger (%s); pending prints won't survive a restart") % e
            return False
        self.save_error = ""
        return True

    def add(self, job):
        with self.lock:
            replaced = self.jobs.pop(job.key, None)
            self.jobs[job.key] = job
            if len(self.jobs) > MAX_JOBS:   # oldest first
                oldest = min(self.jobs, key=lambda k: self.jobs[k].created)
                self.jobs.pop(oldest)
            self._save()
        return replaced

    def pending(self):
        with self.lock:
            return list(self.jobs.values())

    def observe(self, host, state, filename, now=None):
        """Feed one print_stats sample of `host`. Returns [(job, outcome)] taken out of the ledger:
        "book" (printed and finished), "ambiguous" (finished but never seen printing, or seen printing before
        a restart and not since), "failed" (cancelled or error), "expired"."""
        now = time.time() if now is None else now
        path, out = job_key(filename), []
        with self.lock:
            self.seen[host] = time.monotonic()
            changed = False
            for key, job in list(self.jobs.items()):
                if job.host != host or job.retry_at is not None or job.booking:
                    continue
                before = (job.armed, job.saw_other, job.restored)
                outcome = _step(job, state, path, now)
                changed = changed or outcome is not None or before != (job.armed, job.saw_other, job.restored)
                if outcome:
                    del self.jobs[key]
                    if outcome == "book":   # stays saved until booked: a restart now leaves it unconfirmed
                        job.booking = True
                        self.jobs[("booking", job.id)] = job
                    out.append((job, outcome))
            if changed:   # a status sample every few seconds rewrites the file only when something changed
                self._save()
        return out

    def due(self, now=None):
        """Jobs whose remaining slots may be tried again (nothing was written for them)."""
        now = time.time() if now is None else now
        with self.lock:
            ready = [(k, j) for k, j in self.jobs.items() if j.retry_at is not None and j.retry_at <= now]
            for key, job in ready:
                del self.jobs[key]
                job.retry_at = None
                job.booking = True
                self.jobs[("booking", job.id)] = job
            self._save()
        return [j for _, j in ready]

    def retry_later(self, job, now=None):
        job.retry_at = (time.time() if now is None else now) + RETRY_AFTER
        with self.lock:
            self.jobs.pop(("booking", job.id), None)
            job.booking = False
            self.jobs[("retry", job.id)] = job   # never replaces a newer send of the same file
            self._save()

    def begin_use(self, job, slot, grams):
        """Save that `grams` of `slot` are about to be sent. False (send nothing) when that can't be saved."""
        with self.lock:
            job.sending[slot] = grams
            if self._save():
                return True
            job.sending.pop(slot, None)
            return False

    def end_use(self, job, slot, applied, error=""):
        """After the Spoolman call: applied, or listed as unconfirmed (it may have been)."""
        with self.lock:
            grams = job.sending.pop(slot, 0)
            if not applied:
                self.unconfirmed = (self.unconfirmed + [_unconfirmed(job, slot, grams, error)])[-MAX_UNCONFIRMED:]
            self._save()

    def end_booking(self, job):
        """Booking finished or stopped: forget it, unless it waits for a retry (retry_later keeps it)."""
        with self.lock:
            if self.jobs.get(("booking", job.id)) is job:
                del self.jobs[("booking", job.id)]
            job.booking = False
            self._save()

    def unconfirmed_use(self, entry):
        with self.lock:
            self.unconfirmed = (self.unconfirmed + [entry])[-MAX_UNCONFIRMED:]
            self._save()


    def acknowledge(self, entry_id, now=None):
        """The user checked this unconfirmed use in Spoolman themselves: move it to the acknowledged list with the
        time. Only a local note; nothing is sent to Spoolman. Raises ValueError for an unknown id."""
        with self.lock:
            entry = next((u for u in self.unconfirmed if u.get("id") == entry_id), None)
            if entry is None:
                raise ValueError(tr("That unconfirmed entry is no longer listed; nothing was changed."))
            done = {**entry, "acknowledged_at": time.time() if now is None else now}
            self.unconfirmed = [u for u in self.unconfirmed if u is not entry]
            self.acknowledged = (self.acknowledged + [done])[-MAX_ACKNOWLEDGED:]
            if not self._save():
                self.unconfirmed = self.unconfirmed + [entry]
                self.acknowledged = [u for u in self.acknowledged if u is not done]
                raise ValueError(self.save_error)
            return done


def _with_id(entry):
    """Entries from older files have no id: give them a stable one (job + slot), and no time (unknown)."""
    if entry.get("id"):
        return entry
    return {**entry, "id": "%s:%s" % (entry.get("job") or "legacy", entry.get("slot")), "at": entry.get("at")}


def _unconfirmed(job, slot, grams, error):
    return {"id": uuid.uuid4().hex, "at": time.time(), "spool": (job.bindings or {}).get(slot), "grams": grams,
            "slot": slot, "file": job.path, "error": error, "job": job.id, "printer": job.host,
            "printer_name": job.printer_name, "spoolman": job.spoolman_url}


def _step(job, state, path, now):
    """One status sample of the job's printer. Our printer view clears the file name once a print has ended, so
    a terminal state with no name belongs to the job that was seen printing (the printer runs one at a time)."""
    if now - job.created > JOB_TTL:
        return "expired"
    here = path == job.path or (job.armed and not path and state in TERMINAL)
    if job.restored:
        job.restored = False
        if job.armed and here and state in FAILED:
            return "failed"
        if job.armed and not (path == job.path and state in ACTIVE):
            return "restart"   # printing before the restart; how it ended wasn't seen
    if not here:
        job.saw_other = True
        return None
    if state in ACTIVE:
        job.armed = True
        return None
    if state == COMPLETE:
        if job.armed:
            return "book"
        return "ambiguous" if job.saw_other else None   # else: the previous print of this file, still shown
    if state in FAILED and job.armed:
        return "failed"
    job.saw_other = True
    return None


class UsageMixin:
    """Job tracking for service.Service: needs ledger (a Ledger), lock, target (.ident, .name, .spoolman_url,
    .spoolman_report_usage; None without a printer), bindings ({slot: spool id}), spoolman_factory(url) -> an
    object with connect(), spools() and use_weight(), log(text) and _notice(text); _view() when remember_job gets
    an ams_box_mapping list instead of a {filament index: slot} dict."""

    def remember_job(self, filename, mapping, filaments, host=None, options=None):
        """Called when a print is sent, before the printer starts it: per-slot grams to book once this printer
        reports the file printed. mapping: {project filament index: slot (`ace` global_index)}; filaments:
        [{"index", "weight" (grams)}]; host: the printer it goes to (default: the selected one); options:
        {"printer_name", "spoolman_url", "spoolman_report_usage"} (default: the selected target's)."""
        if not isinstance(mapping, dict):   # an ams_box_mapping list: ams_index back to the slot's global_index
            mapping = self._slots_of(mapping)
        per_slot = {}
        for f in filaments:
            slot = mapping.get(f["index"])
            if slot is not None and f.get("weight"):
                per_slot[slot] = per_slot.get(slot, 0) + f["weight"]
        with self.lock:
            target, bindings = self.target, dict(self.bindings)
        ident = printer_ident(host) if host else (target.ident if target else "")
        if not ident or not per_slot:
            return None
        same = target is not None and target.ident == ident
        opts = options or {}
        name = opts.get("printer_name") or (target.name if target else settings.DEFAULT_PRINTER_NAME)
        url = opts["spoolman_url"] if "spoolman_url" in opts else (target.spoolman_url if target else "")
        report = opts.get("spoolman_report_usage", target.spoolman_report_usage if target else True)
        if not report and getattr(target, "own_report_usage", False) and "spoolman_report_usage" not in opts:
            self.log("kobracontrol: filament use for %s is not booked here: Spooler books it in the same Spoolman"
                     % filename)
        if not report:
            return None   # nothing to book: usage reporting is off
        job = Job(ident, filename, per_slot, bindings if same and bindings else None, name, url, report)
        if self.ledger.add(job):
            self.log("kobracontrol: %s was sent again before the earlier copy finished; only the new one is tracked"
                     % job.path)
        if self.ledger.save_error:
            self.log("kobracontrol: " + self.ledger.save_error)
            self._notice("Kobra Control " + self.ledger.save_error + ".")
        return job

    def _slots_of(self, entries):
        """{paint_index: global_index} from `ace` ams_box_mapping entries, using the current slots and mode."""
        view = self._view()
        by_ams = {ace.slot_to_print_ams_index(sl, view["mode"]): sl["global_index"] for sl in view["slots"]}
        return {e["paint_index"]: by_ams[e["ams_index"]] for e in entries if e.get("ams_index") in by_ams}

    def _usage_observe(self, view):
        """track() for the selected printer, for a service that calls it on every state change."""
        target = self.target
        if target is not None:
            self.track(target.ident, view)

    def track(self, host, view):
        """One status sample of printer `host` (a `State.view()`): follow its jobs, book the finished ones.
        Call it on every status update, whether the page is open or not."""
        for job, outcome in self.ledger.observe(printer_ident(host), view.get("state"), view.get("filename")):
            self._settle(job, outcome)

    def retry_due(self):
        """Jobs whose Spoolman call waits for a new attempt (Spoolman was unreachable before anything was sent)."""
        for job in self.ledger.due():
            self._settle(job, "book")

    def _settle(self, job, outcome):
        if outcome == "book":
            try:
                self._book(job)
            except Exception as e:  # keep the caller alive; the job was taken out, so say so
                self.log("kobracontrol: booking %s failed: %r" % (job.path, e))
                self._notice(tr("Spoolman usage for %s not recorded: %s") % (job.path, e))
            finally:
                self.ledger.end_booking(job)
        elif outcome in ("ambiguous", "restart"):
            why = (tr("printing before OrcaSlicer closed; how it ended wasn't seen") if outcome == "restart"
                   else tr("finished without being seen printing"))
            for slot, grams in sorted(job.per_slot.items()):
                self.ledger.unconfirmed_use(_unconfirmed(job, slot, grams, why))
            if outcome == "restart":
                self._notice(tr("%s was printing before OrcaSlicer closed and kobracontrol didn't see how it ended, so "
                             "its filament use was not recorded. Check Spoolman.") % job.path)
            else:
                self._notice(tr("%s finished, but kobracontrol never saw it printing, so its filament use was not "
                             "recorded. Check Spoolman.") % job.path)
        elif outcome == "failed":
            self._notice(tr("%s was cancelled or failed; its filament use was not recorded.") % job.path)
        elif outcome == "expired":
            self._notice(tr("kobracontrol stopped waiting for %s to finish; its filament use was not recorded.") % job.path)

    def _book(self, job):
        """Book one finished job, one Spoolman call per slot, each saved as "sending" first. A failed call may
        have been applied, so it is listed as unconfirmed and never repeated; slots not tried yet wait for
        another attempt."""
        try:
            client = self.spoolman_factory(job.spoolman_url)
            client.connect()
            bindings = job.bindings
            if bindings is None:
                bindings = sm.bindings_from_locations([sm.spool_view(s) for s in client.spools()], job.printer_name)
        except (sm.SpoolmanError, OSError, ValueError) as e:
            self.ledger.retry_later(job)
            self._notice(tr("Spoolman usage for %s waits for a retry: %s") % (job.path, e))
            return
        job.bindings = bindings
        booked, unlinked = [], []
        for slot in sorted(job.per_slot):
            grams, sid = job.per_slot[slot], bindings.get(slot)
            if not sid:
                job.per_slot.pop(slot)
                unlinked.append("S%d" % (slot + 1))
                continue
            if not self.ledger.begin_use(job, slot, grams):
                self.ledger.retry_later(job)   # nothing sent for this slot; try again once the file can be saved
                self._notice(tr("Spoolman usage for %s waits: %s.") % (job.path, self.ledger.save_error))
                return
            job.per_slot.pop(slot)
            try:
                client.use_weight(sid, grams)
            except (sm.SpoolmanError, OSError, ValueError) as e:
                self.ledger.end_use(job, slot, False, str(e))
                self._notice(tr("Spoolman may not have recorded %s g on spool #%d (S%d): %s. Check spool #%d before "
                             "adding it by hand; kobracontrol won't repeat it.") % (round(grams, 2), sid, slot + 1, e, sid))
                if job.per_slot:
                    self.ledger.retry_later(job)
                return
            self.ledger.end_use(job, slot, True)
            booked.append(slot)
        if booked:
            self._notice(tr("Spoolman updated with this print's filament use"))
        if unlinked:
            self._notice(tr("No Spoolman spool was linked to %s; that filament use was not recorded.") % ", ".join(unlinked))

    def cmd_usage(self):
        """What the page shows about filament use: unconfirmed entries (with identity), the last acknowledged
        ones, and notices about the ledger file (set aside, unreadable entries, can't be saved)."""
        return {"pending": [{"file": j.path, "printer": j.host, "grams": j.per_slot} for j in self.ledger.pending()],
                "unconfirmed": list(self.ledger.unconfirmed), "acknowledged": list(self.ledger.acknowledged[-5:]),
                "acknowledged_total": len(self.ledger.acknowledged),
                "save_error": self.ledger.save_error, "restore_notice": self.ledger.restore_notice}

    def cmd_usage_ack(self, id):
        """Mark one unconfirmed use as checked by the user. Local and audited; never a Spoolman call."""
        self.ledger.acknowledge(str(id))
        return self.cmd_usage()
