import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import peers  # noqa: E402
import stockview  # noqa: E402
from test_peers import Root, spooler_presence, stock_doc  # noqa: E402

URL = "http://box:7912"


class Host(stockview.StockMixin):
    def __init__(self, link, target):
        self.peers, self.target = link, target
        self.lock = threading.RLock()
        self.bindings, self.spools, self.bound, self.reads = {}, [], [], 0

    def _snapshot(self):
        return (1, 2, self.target)

    _ctx = _snapshot

    def cmd_spools(self):
        self.reads += 1
        self.spools = [{"id": 7, "filament_id": 70}, {"id": 11, "filament_id": 110}]

    def cmd_bind_spool(self, slot, spool_id):
        self.bound.append((slot, spool_id))
        self.bindings[slot] = spool_id
        return {"bindings": {str(k): v for k, v in self.bindings.items()}}


class StockViewTests(unittest.TestCase):
    def setUp(self):
        self.root = Root(self)
        self.link = peers.SpoolerLink(self.root.path, log=lambda m: None)
        self.target = SimpleNamespace(spoolman_url=URL, spoolman_report_usage=True)
        self.host = Host(self.link, self.target)

    def publish(self, session="s1", origin=URL, spools=None):
        now = time.time()
        self.root.write(peers.PRESENCE_FILE, {**spooler_presence(session, now), "spoolman": {"origin": origin}})
        self.root.write(peers.STOCK_FILE, stock_doc(session, ts=now, url=origin, spools=spools))

    def key(self):
        return self.host.cmd_stock()["stock"]["key"]

    def test_without_spooler_and_without_a_link(self):
        view = self.host.cmd_stock()
        self.assertEqual((view["spooler"]["state"], view["stock"]["state"], view["stock"]["rows"]),
                         ("absent", "unavailable", []))
        with self.assertRaises(ValueError):
            self.host.cmd_stock_assign(1, 7, "s1:3")
        host = Host(None, self.target)
        self.assertEqual(host.cmd_stock()["spooler"]["state"], "absent")
        with self.assertRaises(ValueError):
            host.cmd_stock_assign(1, 7, "s1:3")
        self.assertEqual(self.host.bound, [])

    def test_own_spoolman_list_when_spooler_shares_none(self):
        """No Spooler list (absent, or a Spooler that publishes only for u1control): the Stock tab lists Kobra
        Control's own Spoolman read instead of waiting for ever, and links from it without Spooler."""
        self.host.bindings = {4: 11}
        own = self.host.own_stock(self.target)
        self.assertEqual(self.host.reads, 1)   # nothing read yet: Spoolman is read once here
        self.assertEqual((own["state"], own["source"], own["key"]), ("ok", "spoolman", "spoolman:" + URL))
        self.assertEqual([(r["id"], r["bound_slot"]) for r in own["rows"]], [(7, None), (11, 4)])
        self.host.own_stock(self.target)
        self.assertEqual(self.host.reads, 1)   # the spools already read are used
        self.assertEqual(self.host.cmd_stock_assign(2, 7, own["key"])["bindings"], {"2": 7, "4": 11})
        with self.assertRaises(ValueError):   # another Spoolman address than the list's
            self.host.cmd_stock_assign(2, 7, "spoolman:http://other:7912")
        self.assertIsNone(self.host.own_stock(SimpleNamespace(spoolman_url="")))

    def test_own_list_none_when_spoolman_fails(self):
        def fail():
            raise OSError("refused")
        self.host.cmd_spools = fail
        self.assertIsNone(self.host.own_stock(self.target))

    def test_view_lists_stock_origin_check_and_usage_owner(self):
        self.publish()
        self.host.bindings = {0: 7}
        view = self.host.cmd_stock(refresh=True)
        self.assertEqual((view["spooler"]["state"], [r["id"] for r in view["stock"]["rows"]]), ("active", [7, 11]))
        self.assertTrue(view["same_spoolman"])
        self.assertEqual((view["usage"], view["bindings"]), ("kobracontrol", {"0": 7}))
        self.assertEqual([r["bound_slot"] for r in view["stock"]["rows"]], [0, None])
        self.assertEqual(self.link.stock()[1]["rows"][0].get("bound_slot"), None)   # peers' own rows stay untouched
        self.assertEqual(self.link.stock_request, 1)
        self.assertNotIn("session", view["spooler"])
        self.target.spoolman_report_usage = False
        self.assertEqual(self.host.cmd_stock()["usage"], "off")
        self.target.spoolman_url = ""
        self.assertIsNone(self.host.cmd_stock()["same_spoolman"])
        self.host.target = None
        self.assertEqual(self.host.cmd_stock()["usage"], "unknown")

    def test_a_stale_presence_is_not_a_running_spooler(self):
        self.publish()
        self.root.write(peers.PRESENCE_FILE, {**spooler_presence("s1", time.time() - 3600)})
        view = self.host.cmd_stock()
        self.assertNotEqual(view["spooler"]["state"], "active")
        self.assertEqual(view["stock"]["rows"], [])

    def test_assign_binds_through_the_normal_bind(self):
        self.publish()
        self.assertEqual(self.host.cmd_stock_assign(2, 7, self.key())["bindings"], {"2": 7})
        self.assertEqual(self.host.bound, [(2, 7)])

    def test_assign_refuses_a_list_from_before_a_spooler_restart(self):
        self.publish(session="s1")
        key = self.key()
        self.publish(session="s2")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.host.cmd_stock_assign(1, 7, key)
        self.assertEqual((self.host.bound, self.host.reads), ([], 0))

    def test_assign_refuses_another_spoolman(self):
        self.publish(origin="http://other-box:7912")
        self.assertFalse(self.host.cmd_stock()["same_spoolman"])
        with self.assertRaisesRegex(ValueError, "isn't the one Spooler uses"):
            self.host.cmd_stock_assign(1, 7, self.key())
        self.assertEqual(self.host.bound, [])

    def test_assign_checks_the_spool_in_our_own_spoolman(self):
        self.publish(spools=[{"id": 7, "filament_id": 999}, {"id": 4242, "filament_id": 1}, {"id": 11, "filament_id": 110}])
        key = self.key()
        with self.assertRaisesRegex(ValueError, "another filament"):
            self.host.cmd_stock_assign(1, 7, key)
        with self.assertRaisesRegex(ValueError, "isn't in the Spoolman"):
            self.host.cmd_stock_assign(1, 4242, key)
        with self.assertRaisesRegex(ValueError, "no longer in Spooler's stock"):
            self.host.cmd_stock_assign(1, 5, key)
        self.assertEqual(self.host.cmd_stock_assign(1, 11, key)["bindings"], {"1": 11})
        self.assertEqual(self.host.bound, [(1, 11)])

    def test_bad_arguments(self):
        for args in ((1, 0, "k"), (1, True, "k"), (1, "7", "k"), (1, 7, ""), (1, 7, None), (-1, 7, "k"),
                     (True, 7, "k"), (None, 7, "k")):
            with self.assertRaises(ValueError, msg=args):
                self.host.cmd_stock_assign(*args)


if __name__ == "__main__":
    unittest.main()
