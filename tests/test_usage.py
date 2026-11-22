"""The print ledger (usage.py): jobs survive a restart, are never booked twice, and a cancelled print books nothing.
Files go to temporary folders; Spoolman is an in-memory fake."""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import peers  # noqa: E402
import spoolman as sm  # noqa: E402
import usage  # noqa: E402

PRINTER = "192.168.1.50"
NAME = "Anycubic Kobra X"
URL = "http://box:7912"


class FakeSpoolman:
    uses, fail_on, spools_list, unreachable = [], set(), [], False

    def __init__(self, url=""):
        self.url = url

    def connect(self):
        if FakeSpoolman.unreachable:
            raise sm.SpoolmanError("can't reach Spoolman")

    def spools(self):
        return FakeSpoolman.spools_list

    def use_weight(self, sid, grams):
        if sid in FakeSpoolman.fail_on:
            raise sm.SpoolmanError("timed out")
        FakeSpoolman.uses.append((sid, grams))


class Host(usage.UsageMixin):
    def __init__(self, path, target=None, bindings=None):
        self.lock = threading.RLock()
        self.target = target if target is not None else SimpleNamespace(
            ident=PRINTER, name=NAME, spoolman_url=URL, spoolman_report_usage=True)
        self.bindings = {0: 7, 1: 9} if bindings is None else bindings
        self.logs, self.notices = [], []
        self.ledger = usage.Ledger(usage.LedgerStore(path, log=self.logs.append))
        self.spoolman_factory = FakeSpoolman

    def log(self, text):
        self.logs.append(text)

    def _notice(self, text):
        self.notices.append(text)


def view(state, filename=""):
    return {"state": state, "filename": filename}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        FakeSpoolman.uses, FakeSpoolman.fail_on, FakeSpoolman.spools_list, FakeSpoolman.unreachable = [], set(), [], False
        self.folder = tempfile.mkdtemp(prefix="ledger-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.path = os.path.join(self.folder, "usage_ledger.json")

    def start(self, **kw):
        """A new OrcaSlicer session reading the same ledger file."""
        return Host(self.path, **kw)

    def remember(self, host, name="part.gcode"):
        return host.remember_job(name, {0: 0, 1: 1}, [{"index": 0, "weight": 2.0}, {"index": 1, "weight": 3.0}])

    def feed(self, host, *samples):
        for state, name in samples:
            host.track(PRINTER, view(state, name))

    def saved(self):
        return json.loads(Path(self.path).read_text(encoding="utf-8"))


class BookingTests(LedgerCase):
    def test_print_then_finish_books_each_bound_slot_once(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"), ("printing", "part.gcode"), ("paused", "part.gcode"),
                  ("printing", "part.gcode"), ("finished", ""), ("finished", ""))
        self.assertEqual(sorted(FakeSpoolman.uses), [(7, 2.0), (9, 3.0)])
        self.assertEqual(self.saved()["jobs"], [])
        self.assertIn("Spoolman updated with this print's filament use", host.notices)

    def test_terminal_state_with_the_file_name_still_shown_books_too(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "Part.GCODE"), ("finished", "part.gcode"))
        self.assertEqual(len(FakeSpoolman.uses), 2)

    def test_mapping_sums_filaments_on_one_slot_and_skips_unmapped_or_weightless(self):
        host = self.start()
        job = host.remember_job("p.gcode", {0: 2, 1: 2, 2: None},
                                [{"index": 0, "weight": 1.5}, {"index": 1, "weight": 2.5}, {"index": 2, "weight": 9},
                                 {"index": 3, "weight": 4}, {"index": 4}])
        self.assertEqual(job.per_slot, {2: 4.0})
        self.assertIsNone(host.remember_job("q.gcode", {}, []))

    def test_unbound_slot_is_reported_not_booked(self):
        host = self.start(bindings={0: 7})
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual(FakeSpoolman.uses, [(7, 2.0)])
        self.assertTrue(any("S2" in n and "No Spoolman spool" in n for n in host.notices))

    def test_bindings_are_read_from_spoolman_locations_when_not_known_at_send_time(self):
        FakeSpoolman.spools_list = [{"id": 31, "location": NAME + " S1", "filament": {"material": "PLA"}},
                                    {"id": 32, "location": NAME + " S2", "filament": {"material": "PLA"}}]
        host = self.start(bindings={})
        job = self.remember(host)
        self.assertIsNone(job.bindings)
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual(sorted(FakeSpoolman.uses), [(31, 2.0), (32, 3.0)])

    def test_cancelled_or_failed_print_books_nothing_and_leaves_no_job(self):
        for end in ("cancelled", "error"):
            with self.subTest(end=end):
                host = self.start()
                self.remember(host)
                self.feed(host, ("printing", "part.gcode"), (end, ""))
                self.assertEqual((FakeSpoolman.uses, host.ledger.pending(), host.ledger.unconfirmed), ([], [], []))
                self.assertTrue(any("cancelled or failed" in n for n in host.notices))

    def test_the_previous_prints_finished_state_does_not_book_a_new_job(self):
        host = self.start()
        self.feed(host, ("finished", ""))
        self.remember(host)
        self.feed(host, ("finished", ""), ("idle", ""))     # still showing the old print, then idle
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual(len(host.ledger.pending()), 1)
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual(len(FakeSpoolman.uses), 2)

    def test_finished_without_being_seen_printing_after_other_states_is_unconfirmed(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("idle", ""), ("finished", "part.gcode"))
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual(len(host.ledger.unconfirmed), 2)
        self.assertTrue(any("never saw it printing" in n for n in host.notices))

    def test_jobs_belong_to_their_printer_and_file(self):
        host = self.start()
        self.remember(host)
        host.track("192.168.1.99", view("printing", "part.gcode"))
        host.track("192.168.1.99", view("finished", ""))
        self.feed(host, ("printing", "other.gcode"), ("finished", ""))
        self.assertEqual(FakeSpoolman.uses, [])
        host.track("http://192.168.1.50/", view("printing", "part.gcode"))
        host.track(PRINTER, view("finished", ""))
        self.assertEqual(len(FakeSpoolman.uses), 2)

    def test_same_name_in_another_folder_is_another_job(self):
        self.assertEqual(usage.job_key("gcodes/Dir/Part.GCode"), "dir/part.gcode")
        self.assertNotEqual(usage.job_key("a/part.gcode"), usage.job_key("part.gcode"))

    def test_usage_reporting_off_remembers_nothing(self):
        host = self.start()
        host.target.spoolman_report_usage = False
        self.assertIsNone(self.remember(host))
        self.assertIsNone(host.remember_job("p.gcode", {0: 0}, [{"index": 0, "weight": 1}],
                                            options={"spoolman_report_usage": False}))
        self.assertEqual(host.ledger.pending(), [])

    def test_two_observers_book_a_job_once(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        barrier = threading.Barrier(4)

        def go():
            barrier.wait()
            host.track(PRINTER, view("finished", ""))
        threads = [threading.Thread(target=go) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(FakeSpoolman.uses), [(7, 2.0), (9, 3.0)])

    def test_a_job_that_never_finishes_expires(self):
        host = self.start()
        job = self.remember(host)
        outcomes = host.ledger.observe(PRINTER, "printing", "part.gcode", now=job.created + usage.JOB_TTL + 1)
        self.assertEqual([o for _, o in outcomes], ["expired"])

    def test_sent_again_replaces_the_earlier_copy(self):
        host = self.start()
        self.remember(host)
        self.remember(host)
        self.assertEqual(len(host.ledger.pending()), 1)
        self.assertTrue(any("sent again" in m for m in host.logs))


class MappingListTests(LedgerCase):
    def test_ams_box_mapping_list_and_usage_observe(self):
        host = self.start()
        slots = [{"global_index": 3, "box_id": 0, "index": 0}, {"global_index": 4, "box_id": 0, "index": 1}]
        host._view = lambda: {"mode": "ace_hub", "slots": slots}
        mapping = [{"paint_index": 0, "ams_index": 4}, {"paint_index": 1, "ams_index": 5}, {"paint_index": 2, "ams_index": 99}]
        job = host.remember_job("m.gcode", mapping, [{"index": 0, "weight": 2.0}, {"index": 1, "weight": 1.0},
                                                      {"index": 2, "weight": 7.0}])
        self.assertEqual(job.per_slot, {3: 2.0, 4: 1.0})
        host._usage_observe(view("printing", "m.gcode"))
        host._usage_observe(view("finished", ""))
        self.assertEqual(host.ledger.pending(), [])


class RetryTests(LedgerCase):
    def test_spoolman_unreachable_before_any_write_keeps_the_job_and_retries(self):
        host = self.start()
        FakeSpoolman.unreachable = True
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual(len(host.ledger.pending()), 1)
        FakeSpoolman.unreachable = False
        host.retry_due()
        self.assertEqual(FakeSpoolman.uses, [])                       # not yet due
        with mock.patch.object(usage.time, "time", return_value=time.time() + usage.RETRY_AFTER + 1):
            host.retry_due()
        self.assertEqual(sorted(FakeSpoolman.uses), [(7, 2.0), (9, 3.0)])
        self.assertEqual(self.saved()["jobs"], [])

    def test_timeout_is_unconfirmed_never_repeated_and_the_rest_retried(self):
        host = self.start()
        FakeSpoolman.fail_on = {7}
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual([(u["spool"], u["slot"], u["grams"]) for u in host.ledger.unconfirmed], [(7, 0, 2.0)])
        self.assertTrue(any("won't repeat" in n for n in host.notices))
        FakeSpoolman.fail_on = set()
        host = self.start()                                           # and after a restart
        with mock.patch.object(usage.time, "time", return_value=time.time() + usage.RETRY_AFTER + 1):
            host.retry_due()
        self.assertEqual(FakeSpoolman.uses, [(9, 3.0)])
        self.assertEqual(host.ledger.unconfirmed[0]["spool"], 7)

    def test_intent_not_saved_means_nothing_sent(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        with mock.patch.object(usage.LedgerStore, "save", side_effect=OSError("disk full")):
            self.feed(host, ("finished", ""))
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual(len(host.ledger.pending()), 1)
        self.assertTrue(any("disk full" in n for n in host.notices))
        with mock.patch.object(usage.time, "time", return_value=time.time() + usage.RETRY_AFTER + 1):
            host.retry_due()
        self.assertEqual(sorted(FakeSpoolman.uses), [(7, 2.0), (9, 3.0)])

    def test_an_unexpected_error_while_booking_is_reported_and_the_job_dropped(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        with mock.patch.object(FakeSpoolman, "connect", side_effect=RuntimeError("bug")):
            self.feed(host, ("finished", ""))
        self.assertEqual(host.ledger.pending(), [])
        self.assertTrue(any("not recorded: bug" in n for n in host.notices))


class RestartTests(LedgerCase):
    def test_job_is_on_disk_and_identifies_printer_spoolman_and_file(self):
        host = self.start()
        job = self.remember(host)
        saved = self.saved()["jobs"][0]
        self.assertEqual((saved["id"], saved["host"], saved["path"], saved["spoolman_url"], saved["per_slot"]),
                         (job.id, PRINTER, "part.gcode", URL, {"0": 2.0, "1": 3.0}))

    def test_printing_through_a_restart_is_booked_once(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        host = self.start()                                           # OrcaSlicer restarted mid-print
        self.feed(host, ("printing", "part.gcode"), ("finished", ""))
        self.assertEqual(sorted(FakeSpoolman.uses), [(7, 2.0), (9, 3.0)])
        self.assertEqual(self.saved()["jobs"], [])
        host = self.start()
        self.feed(host, ("finished", ""))
        self.assertEqual(len(FakeSpoolman.uses), 2)                   # nothing booked again after another restart

    def test_finished_while_closed_is_unconfirmed_not_booked(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        host = self.start()
        self.feed(host, ("finished", ""))                              # first sample after the restart
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual([u["error"] for u in host.ledger.unconfirmed],
                         ["printing before OrcaSlicer closed; how it ended wasn't seen"] * 2)
        self.assertTrue(any("before OrcaSlicer closed" in n for n in host.notices))
        self.assertEqual(self.saved()["unconfirmed"][0]["job"], host.ledger.unconfirmed[0]["job"])

    def test_cancel_after_restart_books_nothing(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        host = self.start()
        self.feed(host, ("cancelled", ""))
        self.assertEqual((FakeSpoolman.uses, host.ledger.unconfirmed, host.ledger.pending()), ([], [], []))

    def test_a_call_in_flight_at_a_crash_is_never_sent_again(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))

        def crash(sid, grams):
            raise SystemExit("OrcaSlicer died during the Spoolman call")
        with mock.patch.object(FakeSpoolman, "use_weight", side_effect=crash):
            with self.assertRaises(SystemExit):
                for job, _ in host.ledger.observe(PRINTER, "finished", ""):
                    host._book(job)
        self.assertEqual(self.saved()["jobs"][0]["sending"], {"0": 2.0})
        host = self.start()
        self.assertEqual([(u["spool"], u["grams"], u["error"]) for u in host.ledger.unconfirmed],
                         [(7, 2.0, "OrcaSlicer closed while this was being recorded")])
        self.feed(host, ("finished", ""))                              # slot 2 never sent; the end wasn't seen
        self.assertEqual(FakeSpoolman.uses, [])
        self.assertEqual(len(host.ledger.unconfirmed), 2)

    def test_unchanged_samples_do_not_rewrite_the_file(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        with mock.patch.object(usage.LedgerStore, "save") as save:
            for _ in range(5):
                host.track(PRINTER, view("printing", "part.gcode"))
                host.track("another-printer", view("idle"))
        save.assert_not_called()

    def test_unreadable_ledger_is_set_aside_not_overwritten(self):
        Path(self.path).write_text("{broken", encoding="utf-8")
        host = self.start()
        aside = [n for n in os.listdir(self.folder) if n.startswith("usage_ledger.json.bad-")]
        self.assertEqual(len(aside), 1)
        self.assertEqual(Path(self.folder, aside[0]).read_text(), "{broken")
        self.assertEqual(host.ledger.pending(), [])
        self.assertIn("kept as", host.ledger.restore_notice)
        Path(self.path).write_text(json.dumps({"version": 9, "jobs": []}), encoding="utf-8")
        self.assertIn("unknown format", self.start().ledger.restore_notice)

    def test_malformed_entries_are_skipped_and_reported(self):
        Path(self.path).write_text(json.dumps({"version": 1, "jobs": [{"host": "x"}, "bad"],
                                               "unconfirmed": ["x", {"spool": 1}]}))
        host = self.start()
        self.assertEqual(host.ledger.pending(), [])
        self.assertEqual(host.ledger.unconfirmed, [{"spool": 1, "id": "legacy:None", "at": None}])
        self.assertIn("2 unreadable job(s)", host.ledger.restore_notice)
        self.assertIn("1 unreadable unconfirmed entry", host.ledger.restore_notice)

    def test_slots_out_of_range_in_a_saved_job_are_dropped(self):
        Path(self.path).write_text(json.dumps({"version": 1, "jobs": [
            {"id": "j", "host": PRINTER, "path": "a.gcode", "per_slot": {"0": 1.0, "99": 5.0, "-1": 2.0},
             "created": time.time()}]}))
        self.assertEqual(self.start().ledger.pending()[0].per_slot, {0: 1.0})


class AcknowledgeTests(LedgerCase):
    def finished_while_closed(self):
        host = self.start()
        self.remember(host)
        self.feed(host, ("printing", "part.gcode"))
        host = self.start()
        self.feed(host, ("finished", ""))
        return host

    def test_acknowledging_is_local_audited_and_survives_a_restart(self):
        host = self.finished_while_closed()
        view_ = host.cmd_usage()
        self.assertEqual(len(view_["unconfirmed"]), 2)
        first = view_["unconfirmed"][0]
        for field in ("id", "at", "slot", "grams", "file", "printer", "spool", "job"):
            self.assertIn(field, first)
        after = host.cmd_usage_ack(first["id"])
        self.assertEqual(FakeSpoolman.uses, [])                       # never calls Spoolman
        self.assertEqual([u["id"] for u in after["unconfirmed"]], [view_["unconfirmed"][1]["id"]])
        self.assertEqual(after["acknowledged"][-1]["id"], first["id"])
        self.assertIn("acknowledged_at", after["acknowledged"][-1])
        self.assertEqual(self.saved()["acknowledged"][-1]["id"], first["id"])
        with self.assertRaises(ValueError):
            host.cmd_usage_ack(first["id"])
        host = self.start()
        self.assertEqual([u["id"] for u in host.ledger.unconfirmed], [view_["unconfirmed"][1]["id"]])
        self.assertEqual(host.ledger.acknowledged[-1]["id"], first["id"])

    def test_acknowledge_that_cannot_be_saved_changes_nothing(self):
        host = self.start()
        host.ledger.unconfirmed_use({"id": "u1", "at": 1.0, "spool": 7, "grams": 2.0, "slot": 0, "file": "a.gcode"})
        with mock.patch.object(usage.LedgerStore, "save", side_effect=OSError("disk full")):
            with self.assertRaises(ValueError):
                host.cmd_usage_ack("u1")
        self.assertEqual([u["id"] for u in host.ledger.unconfirmed], ["u1"])
        self.assertEqual(host.ledger.acknowledged, [])

    def test_cmd_usage_lists_pending_jobs(self):
        host = self.start()
        self.remember(host)
        self.assertEqual(host.cmd_usage()["pending"], [{"file": "part.gcode", "printer": PRINTER, "grams": {0: 2.0, 1: 3.0}}])


class SharedPrintTests(LedgerCase):
    """Finished prints go to <data folder>/kobracontrol/prints.json for Spooler's history, once each."""

    def shared(self):
        return json.loads(Path(self.folder, "kobracontrol", peers.PRINTS_FILE).read_text(encoding="utf-8"))

    def test_a_booked_print_is_shared_once_with_its_slots_and_spools(self):
        host = self.start(bindings={0: 7})
        host.peers = peers.SpoolerLink(self.folder)
        self.remember(host)
        host.track(PRINTER, {"state": "printing", "filename": "part.gcode", "model": "Kobra X"})
        host.track(PRINTER, {"state": "finished", "filename": "", "model": "Kobra X"})
        doc = self.shared()
        self.assertEqual((doc["schema"], doc["version"]), (peers.PRINTS_SCHEMA, peers.PRINTS_VERSION))
        [rec] = doc["prints"]
        self.assertEqual((rec["file"], rec["printer"], rec["model"], rec["spoolman"]), ("part.gcode", NAME, "Kobra X", URL))
        self.assertEqual(rec["slots"], [{"slot": 0, "grams": 2.0, "spool": 7}, {"slot": 1, "grams": 3.0, "spool": None}])
        job = usage.Job(PRINTER, "part.gcode", {1: 1.0}, job_id=rec["id"])
        host._share_print(job, {})   # a retry of the same job changes nothing
        self.assertEqual(self.shared()["prints"], [rec])

    def test_the_file_keeps_the_last_prints_only(self):
        link = peers.SpoolerLink(self.folder)
        for n in range(peers.PRINTS_MAX + 3):
            link.note_print({"id": str(n), "slots": []})
        ids = [p["id"] for p in self.shared()["prints"]]
        self.assertEqual((len(ids), ids[0], ids[-1]), (peers.PRINTS_MAX, "3", str(peers.PRINTS_MAX + 2)))


class IdentTests(unittest.TestCase):
    def test_printer_ident_has_one_spelling(self):
        for text in ("192.168.1.5", "http://192.168.1.5/", " HTTP://192.168.1.5/x ", "192.168.1.5/"):
            self.assertEqual(usage.printer_ident(text), "192.168.1.5")
        self.assertEqual(usage.printer_ident(None), "")


if __name__ == "__main__":
    unittest.main()
