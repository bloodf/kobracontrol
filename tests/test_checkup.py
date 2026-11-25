"""Check everything (checkup.py, service.cmd_checkup): one read-only list of every connection and permission.
Run: python3 -m unittest tests/test_checkup.py -v"""

import os
import sys
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import checkup  # noqa: E402
import connection  # noqa: E402
import kobra  # noqa: E402
import locate  # noqa: E402
import service  # noqa: E402
import spoolman as sm  # noqa: E402
from test_service import READ_ONLY, Base, wait  # noqa: E402


def by_id(results):
    return {r["id"]: r for r in results}


class Svc:
    """Just what the checks read from a Service."""

    def __init__(self, host="10.0.0.5", spoolman_url="", connect=None, conn=None, tls=None, spoolman=None, account=None,
                 printers=None, agent_seen=True):
        self.target = service.Target(host, spoolman_url=spoolman_url) if host is not None else None
        self._connect, self.connections = connect, {host: conn} if conn else {}
        self.tls = tls or (lambda: None)
        self._spoolman_fn, self.cloud, self._printers = spoolman, account, printers
        self.agent_seen = agent_seen
        self.host_requirements = ({"id": "certificate", "state": "ok", "details": "bundled"},)

    def cmd_connect(self):
        return self._connect()

    def _spoolman(self, target):
        return self._spoolman_fn()

    def cmd_cloud_printers(self):
        return self._printers()


def conn(http_failed=False, no_certificate=False, held=False, denied=False):
    return types.SimpleNamespace(http_failed=http_failed, no_certificate=no_certificate, held=held, denied=denied)


def raises(error):
    def fn():
        raise error
    return fn


class Checks(unittest.TestCase):
    def test_all_pass_in_order(self):
        svc = Svc(spoolman_url="http://box:7912", spoolman=lambda: None, account=types.SimpleNamespace(signed_in=True),
                  printers=lambda: [{}, {}],
                  connect=lambda: {"address": "10.0.0.5", "model": "Kobra X", "firmware": "2.1.0"})
        out = checkup.run(svc)
        self.assertEqual([r["id"] for r in out], list(checkup.ORDER))
        self.assertEqual({r["state"] for r in out}, {checkup.PASS})
        got = by_id(out)
        self.assertEqual(got["login"]["detail"], "Kobra X · 2.1.0")
        self.assertEqual(got["spoolman"]["detail"], "http://box:7912")
        self.assertEqual(got["cloud"]["detail"], "2")
        self.assertEqual(got["certificate"]["detail"], "bundled")

    def test_not_configured(self):
        got = by_id(checkup.run(Svc(host=None, agent_seen=False)))
        self.assertEqual((got["printer"]["state"], got["printer"]["reason"]), (checkup.OFF, "no_printer"))
        self.assertEqual(got["spoolman"]["state"], checkup.OFF)
        self.assertEqual(got["cloud"]["state"], checkup.OFF)
        self.assertEqual((got["printer_agents"]["state"], got["printer_agents"]["reason"]), (checkup.FAIL, "not_seen"))

    def test_cloud_printer_skips_the_lan_checks(self):
        svc = Svc(host="cloud:12", connect=raises(AssertionError("the LAN is not tried")),
                  account=types.SimpleNamespace(signed_in=False))
        got = by_id(checkup.run(svc))
        self.assertEqual((got["printer"]["state"], got["printer"]["reason"]), (checkup.OFF, "cloud"))
        self.assertEqual((got["cloud"]["state"], got["cloud"]["reason"]), (checkup.FAIL, "signed_out"))

    def test_printer_not_found(self):
        got = by_id(checkup.run(Svc(connect=raises(locate.NotFound("no printer answered")))))
        self.assertEqual((got["printer"]["state"], got["printer"]["reason"]), (checkup.FAIL, "not_found"))
        self.assertEqual((got["login"]["state"], got["login"]["reason"]), (checkup.FAIL, "needs_printer"))

    def test_printer_permission_offers_the_dialog(self):
        got = by_id(checkup.run(Svc(connect=raises(kobra.KobraError("not allowed")), conn=conn(http_failed=True, denied=True))))
        self.assertEqual((got["printer"]["reason"], got["printer"]["action"]), ("denied", "allow_printer"))

    def test_unreachable_versus_login(self):
        got = by_id(checkup.run(Svc(connect=raises(kobra.KobraError("timed out")), conn=conn(http_failed=True))))
        self.assertEqual((got["printer"]["state"], got["printer"]["reason"]), (checkup.FAIL, "unreachable"))
        got = by_id(checkup.run(Svc(connect=raises(kobra.KobraError("no answer on MQTT")), conn=conn())))
        self.assertEqual(got["printer"]["state"], checkup.PASS)
        self.assertEqual((got["login"]["state"], got["login"]["reason"], got["login"]["detail"]), (checkup.FAIL, "login", "no answer on MQTT"))
        got = by_id(checkup.run(Svc(connect=raises(kobra.KobraError("held")), conn=conn(held=True))))
        self.assertEqual(got["login"]["reason"], "held")
        got = by_id(checkup.run(Svc(connect=raises(connection.NoCertificate("none")), conn=conn(no_certificate=True))))
        self.assertEqual(got["login"]["reason"], "no_certificate")

    def test_certificate_that_does_not_load(self):
        got = by_id(checkup.run(Svc(connect=lambda: {}, tls=raises(connection.NoCertificate("does not load")))))
        self.assertEqual((got["certificate"]["state"], got["certificate"]["reason"]), (checkup.FAIL, "no_certificate"))

    def test_spoolman_permission_is_told_apart_from_unreachable(self):
        def refused():   # what spoolman.Spoolman.call raises when OrcaSlicer's audit refuses the request
            try:
                raise PermissionError("audit permission required")
            except OSError as e:
                raise sm.SpoolmanError("can't reach Spoolman at http://box:7912 (%s)" % e) from None
        got = by_id(checkup.run(Svc(connect=lambda: {}, spoolman_url="http://box:7912", spoolman=refused)))
        self.assertEqual((got["spoolman"]["state"], got["spoolman"]["reason"], got["spoolman"]["action"]),
                         (checkup.FAIL, "denied", "allow_spoolman"))
        got = by_id(checkup.run(Svc(connect=lambda: {}, spoolman_url="http://box:7912",
                                    spoolman=raises(sm.SpoolmanError("can't reach Spoolman (refused)")))))
        self.assertEqual((got["spoolman"]["reason"], got["spoolman"]["action"]), ("unreachable", ""))

    def test_a_check_that_breaks_is_a_failure_not_the_end(self):
        def broken(svc):
            raise RuntimeError("boom")
        logs = []
        out = checkup.run(Svc(connect=lambda: {}), checks=(broken, checkup.printer_agents_check), log=logs.append)
        self.assertEqual([(r["state"], r["reason"]) for r in out], [(checkup.PASS, ""), (checkup.FAIL, "error")])
        self.assertTrue(logs)


class ConnectionDenied(unittest.TestCase):
    def test_a_refused_attempt_is_flagged(self):
        def fetch(host, port):
            raise kobra.KobraError("denied", code="denied")
        c = connection.Connection("10.0.0.5", lambda: None, lambda m: None, fetch=fetch).start()
        self.addCleanup(c.stop)
        wait(lambda: c.failures)
        self.assertTrue(c.denied)


class AgainstFakePrinter(Base):
    def test_checkup_reaches_the_printer_with_read_only_queries_only(self):
        time.sleep(0.3)
        reply = self.run_cmd("checkup")
        got = by_id(reply["result"])
        self.assertEqual(got["printer"]["state"], checkup.PASS)
        self.assertEqual(got["login"]["state"], checkup.PASS)
        self.assertEqual(got["spoolman"]["state"], checkup.PASS)
        self.assertEqual(self.kinds(), READ_ONLY)   # nothing paused, stopped, moved, heated or fed


if __name__ == "__main__":
    unittest.main()
