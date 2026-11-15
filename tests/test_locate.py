"""Finding the Kobra X without the user typing its address (locate.py), against FakeSsdp and FakeKobra on
127.0.0.1 only. Run: python3 -m unittest tests/test_locate.py -v"""

import json
import os
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import kobra  # noqa: E402
import locate  # noqa: E402
import service  # noqa: E402
from fake_kobra import FakeKobra, FakeSsdp  # noqa: E402
from test_service import FakeCamera, wait  # noqa: E402

BRIDGE = "10.25.16.41"   # the owner's case: the preset points to a Kobralink/Moonraker bridge, not the printer


def refused(ip):
    raise kobra.KobraError("printer not reachable at %s:18910 for /info ([Errno 61] Connection refused)" % ip,
                           code="unreachable")


class Search(unittest.TestCase):
    @staticmethod
    def targets(ssdp):
        return [line[4:] for p in ssdp.searches for line in p.split(b"\r\n") if line.startswith(b"ST: ")]

    def test_an_empty_datagram_is_the_kobra_x(self):
        """Measured on a Kobra X (2.0.2.8): it answers every M-SEARCH with one empty datagram."""
        with FakeSsdp() as ssdp:
            found = locate.search(timeout=1.0, addr=ssdp.addr, interfaces=[])
        self.assertEqual(found, [("127.0.0.1", {})])
        self.assertEqual(self.targets(ssdp), [b"ac:3dprinter:", b"ac:3dprinter:"])   # sent twice; no ssdp:all needed
        self.assertTrue(all(p.startswith(b"M-SEARCH * HTTP/1.1\r\n") for p in ssdp.searches))

    def test_ssdp_all_only_when_the_anycubic_search_finds_nothing(self):
        with FakeSsdp(only_st=b"ssdp:all") as ssdp:
            found = locate.search(timeout=0.6, addr=ssdp.addr, interfaces=[])
        self.assertEqual([ip for ip, _ in found], ["127.0.0.1"])
        self.assertEqual(self.targets(ssdp), [b"ac:3dprinter:"] * 2 + [b"ssdp:all"] * 2)

    def test_a_text_reply_naming_the_printer_is_also_accepted(self):
        with FakeSsdp(reply=FakeSsdp.printer_reply(18910)) as ssdp:
            found = locate.search(timeout=1.0, addr=ssdp.addr, interfaces=[])
        self.assertEqual(found[0][1]["MODELID"], "20030")

    def test_an_empty_reply_from_a_public_address_is_ignored(self):
        class Sock:
            replies = [(b"", ("8.8.8.8", 1900)), (b"", ("10.25.7.41", 1900))]
            sent = []

            def sendto(self, data, addr):
                self.sent.append(addr)

            def settimeout(self, t):
                pass

            def setsockopt(self, *a):
                pass

            def recvfrom(self, n):
                if not self.replies:
                    raise TimeoutError
                return self.replies.pop(0)
        with mock.patch.object(locate.time, "sleep"):
            found = locate._search_once(Sock(), "ac:3dprinter:", ("239.255.255.250", 1900), ["10.25.0.5", "10.25.9.9"], 1.0)
        self.assertEqual(found, [("10.25.7.41", {})])
        self.assertEqual(len(Sock.sent), 4)   # twice on each local address

    def test_other_devices_and_floods_are_ignored(self):
        with FakeSsdp(reply=b"HTTP/1.1 200 OK\r\nST: urn:schemas-upnp-org:device:MediaRenderer:1\r\n\r\n") as ssdp:
            self.assertEqual(locate.search(timeout=0.5, addr=ssdp.addr, interfaces=[]), [])   # a TV is never probed
        with FakeSsdp(count=500) as ssdp:   # one sender, many replies: one result
            started = time.monotonic()
            self.assertEqual(len(locate.search(timeout=1.0, addr=ssdp.addr, interfaces=[])), 1)
            self.assertLess(time.monotonic() - started, 1.8)

    def test_reply_size_is_capped(self):
        with FakeSsdp(reply=FakeSsdp.printer_reply() + b"X: " + b"Y" * 6000) as ssdp:
            found = locate.search(timeout=0.5, addr=ssdp.addr, interfaces=[])
        self.assertEqual(len(found), 1)
        self.assertLessEqual(sum(len(v) for v in found[0][1].values()), locate.MAX_REPLY)

    def test_silence_is_an_empty_answer(self):
        with FakeSsdp(reply=None) as ssdp:
            started = time.monotonic()
            self.assertEqual(locate.search(timeout=0.3, addr=ssdp.addr, interfaces=[]), [])
            self.assertLess(time.monotonic() - started, 2.0)

    def test_only_lan_addresses(self):
        for ip in ("10.25.7.41", "192.168.1.5", "172.16.0.9", "169.254.3.4", "127.0.0.1"):
            self.assertTrue(locate.lan_address(ip), ip)
        for ip in ("8.8.8.8", "239.255.255.250", "0.0.0.0", "printer.example", "::1", ""):
            self.assertFalse(locate.lan_address(ip), ip)


class Probe(unittest.TestCase):
    def test_kobra_x_answers_with_a_token(self):
        with FakeKobra() as fake:
            fake.info_answer = {"token": fake.token, "deviceName": "Workshop KX", "modelName": "Anycubic Kobra X",
                                "ctrlInfoUrl": "http://203.0.113.9/ctrl"}
            info = locate.probe(fake.host, fake.http_port)
            self.assertEqual(info, {"ip": "127.0.0.1", "name": "Workshop KX", "model": "Anycubic Kobra X"})
            fake.info_answer = {"result": "moonraker"}
            with self.assertRaises(kobra.KobraError):
                locate.probe(fake.host, fake.http_port)

    def test_refused_port_is_not_a_printer(self):
        closed = socket.create_server(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        with self.assertRaises(kobra.KobraError) as cm:
            locate.probe("127.0.0.1", port, timeout=1)
        self.assertIn("refused", str(cm.exception).lower())


class Locate(unittest.TestCase):
    def test_override_is_used_as_given(self):
        found = locate.locate("10.0.0.9", BRIDGE, probe=self.fail, search=self.fail)
        self.assertEqual((found.host, found.source), ("10.0.0.9", "override"))

    def test_bridge_in_preset_then_printer_found_on_the_network(self):
        def probe(ip):
            return refused(ip) if ip == BRIDGE else {"ip": ip, "name": "KX", "model": "Kobra X"}
        found = locate.locate("", BRIDGE, probe=probe, search=lambda: [("10.25.7.41", {})])
        self.assertEqual((found.host, found.source), ("10.25.7.41", "discovered"))
        self.assertIn("The printer preset points to 10.25.16.41, which is not a Kobra X", found.note)
        self.assertIn("found the Kobra X at 10.25.7.41", found.note)

    def test_remembered_address_first_without_search(self):
        found = locate.locate("", BRIDGE, remembered="10.25.7.41", probe=lambda ip: {"ip": ip},
                              search=self.fail)
        self.assertEqual((found.host, found.source), ("10.25.7.41", "remembered"))

    def test_preset_used_when_a_kobra_x_answers_there(self):
        found = locate.locate("", "10.25.7.41", probe=lambda ip: {"ip": ip}, search=self.fail)
        self.assertEqual((found.host, found.source), ("10.25.7.41", "preset"))

    def test_several_printers_are_offered(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=lambda ip: {"ip": ip, "name": ip[-1], "model": ""},
                          search=lambda: [("10.0.0.2", {}), ("10.0.0.3", {})])
        self.assertEqual([c["ip"] for c in cm.exception.candidates], ["10.0.0.2", "10.0.0.3"])

    def test_nothing_found_explains_the_bridge(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", BRIDGE, probe=refused, search=list)
        text = str(cm.exception)
        self.assertIn("something answers at 10.25.16.41 but it is not a Kobra X in LAN mode", text)
        self.assertIn("comes from the printer preset", text)
        self.assertIn("Settings > Printer address", text)
        self.assertIn("LAN mode is on", text)
        self.assertTrue(cm.exception.no_target)

    def test_a_candidate_that_is_not_a_kobra_x_is_dropped(self):
        def probe(ip):
            raise kobra.KobraError("%s answers /info without a LAN token" % ip, code="no_token")
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=probe, search=lambda: [("10.25.3.3", {})])
        self.assertEqual((cm.exception.candidates, cm.exception.pending), ([], []))
        self.assertIn("No Kobra X answered", str(cm.exception))

    def test_an_ungranted_candidate_is_not_probed_but_handed_to_the_page(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=self.fail, search=lambda: [("10.25.7.41", {})], allowed=lambda ip: False)
        self.assertEqual(cm.exception.pending, ["10.25.7.41"])
        self.assertIn("connects by itself", str(cm.exception))

    def test_a_new_address_waiting_for_permission(self):
        def probe(ip):
            raise kobra.KobraError("OrcaSlicer denied network access", code="denied")
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=probe, search=lambda: [("10.25.7.41", {})])
        self.assertIn("Allow Kobra Control to reach it", str(cm.exception))

    def fail(self, *a):
        raise AssertionError("must not be called")


class DiscoverScript(unittest.TestCase):
    """scripts/discover.py, the owner's read-only check on the real network, run here against FakeSsdp only."""

    def test_prints_replies_and_masks_secrets(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import discover
        lines = []
        with FakeSsdp() as ssdp, mock.patch.object(locate, "SSDP_ADDR", ssdp.addr):
            found = discover.listen(1.0, False, lines.append)
        self.assertEqual(found, ["127.0.0.1"])
        self.assertIn("reply from 127.0.0.1:%d: empty datagram [Kobra X signature]" % ssdp.addr[1], "\n".join(lines))
        lines.clear()
        with FakeSsdp(reply=FakeSsdp.printer_reply(18910)) as ssdp, mock.patch.object(locate, "SSDP_ADDR", ssdp.addr):
            discover.listen(1.0, False, lines.append)
        text = "\n".join(lines)
        self.assertIn("MODELID: 20030", text)
        self.assertIn("CN: FAKECN", text)   # 6 characters: short values are shown
        token = "T" * 32
        with mock.patch.object(kobra, "_http_json", return_value={"token": token, "deviceName": "KX"}):
            discover.confirm("127.0.0.1", lines.append)
        self.assertIn("a Kobra X in LAN mode", lines[-1])
        self.assertNotIn(token, lines[-1])


class ServiceLocates(unittest.TestCase):
    """The owner's case end to end: no address in Settings, the preset names the bridge, the printer answers SSDP."""

    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        self.fake.reply("info", "query", {})
        self.fake.reply("print", "query", {}, state="free")
        self.fake.reply("multiColorBox", "getInfo", {"multi_color_box": []})
        self.ssdp = FakeSsdp()
        self.addCleanup(self.ssdp.stop)
        self.folder = tempfile.mkdtemp()
        self.probed, self.lost = [], False

    def probe(self, ip):
        self.probed.append(ip)
        return refused(ip) if ip == BRIDGE or self.lost else locate.probe(ip, self.fake.http_port)

    def service(self, **kw):
        published = []
        svc = service.Service(published.append, lambda m: None, cert_dir=self.folder, tls=lambda: None,
                              http_port=self.fake.http_port, mqtt_port=self.fake.mqtt_port, camera_factory=FakeCamera,
                              addresses_path=os.path.join(self.folder, "addresses.json"), probe=self.probe,
                              search=lambda: locate.search(timeout=1.0, addr=self.ssdp.addr, interfaces=[]), **kw)
        self.addCleanup(svc.close)
        return svc, published

    def hello(self, svc, published, rid="h"):
        svc.set_target(service.Target("", preset_host=BRIDGE, preset_key="Anycubic Kobra X", preset_agent="moonraker"))
        svc.submit(rid, "connect", {})
        return wait(lambda: next((m for m in published if m.get("id") == rid), None), 20)

    def test_finds_connects_remembers(self):
        svc, published = self.service()
        reply = self.hello(svc, published)
        self.assertEqual(reply["result"]["address"], "127.0.0.1")
        self.assertEqual(reply["result"]["source"], "discovered")
        self.assertIn("10.25.16.41, which is not a Kobra X", reply["result"]["note"])
        self.assertTrue(svc.connections["127.0.0.1"].connected)
        self.assertNotIn(BRIDGE, svc.connections)   # never a connection loop for the bridge
        with open(os.path.join(self.folder, "addresses.json")) as f:
            self.assertEqual(json.load(f)["printers"], {"Anycubic Kobra X": "127.0.0.1"})
        svc.close()
        searches = len(self.ssdp.searches)
        svc2, published2 = self.service()
        reply = self.hello(svc2, published2, "h2")
        self.assertEqual(reply["result"]["source"], "remembered")
        self.assertEqual(len(self.ssdp.searches), searches)   # instant: no new search

    def test_nothing_found_is_a_calm_no_target_reply(self):
        self.ssdp.reply = None
        svc, published = self.service()
        reply = self.hello(svc, published)
        self.assertTrue(reply["no_target"])
        self.assertEqual(reply["candidates"], [])
        self.assertIn("not a Kobra X in LAN mode", reply["error"])
        self.assertEqual(svc.connections, {})

    def test_search_again_and_choose(self):
        self.ssdp.reply = None
        svc, published = self.service()
        self.hello(svc, published)
        svc.locate_error = locate.NotFound("2 found", [{"ip": "127.0.0.1", "name": "A", "model": ""},
                                                       {"ip": "10.0.0.3", "name": "B", "model": ""}])
        svc.submit("c", "choose_printer", {"host": "8.8.8.8"})
        self.assertIn("not among", wait(lambda: next((m for m in published if m.get("id") == "c"), None))["error"])
        svc.submit("c2", "choose_printer", {"host": "127.0.0.1"})
        wait(lambda: next((m for m in published if m.get("id") == "c2"), None))
        self.assertEqual(svc.target.host, "127.0.0.1")
        self.ssdp.reply = FakeSsdp.KOBRA_X
        svc.submit("s", "search_printer", {})
        reply = wait(lambda: next((m for m in published if m.get("id") == "s"), None), 10)
        self.assertEqual(reply["result"], {"address": "127.0.0.1", "source": "discovered"})

    def test_lost_address_is_searched_again_at_most_once_a_minute(self):
        svc, published = self.service()
        self.hello(svc, published)
        conn = svc.connections["127.0.0.1"]
        searches = len(self.ssdp.searches)
        self.lost = True   # the printer took a new DHCP address: the remembered one stops answering
        svc.located_at -= service.RELOCATE_EVERY
        conn.http_failed = True
        conn.state.connected = False
        for _ in range(5):
            svc._relocate_if_lost(conn)
        wait(lambda: len(self.ssdp.searches) > searches, 5)
        time.sleep(1.5)
        self.assertEqual(len(self.ssdp.searches) - searches, 2)   # one search: its two M-SEARCH packets

    def test_a_found_printer_not_yet_allowed_is_granted_on_the_ui_thread_then_connects(self):
        """In OrcaSlicer a refused attempt off the UI thread queues one more dialog per attempt, so a found but
        not yet granted address is not probed from the search thread: the page asks for it once (allow_hosts,
        handled on the UI thread, where OrcaSlicer's dialog shows at once and a Yes is saved), then it connects."""
        granted = set()
        svc, published = self.service(granted=granted)
        reply = self.hello(svc, published)
        self.assertEqual(reply["pending"], ["127.0.0.1"])
        self.assertNotIn("127.0.0.1", self.probed)   # not probed before it is allowed
        self.assertEqual(svc.allow(["127.0.0.1", "8.8.8.8", "10.9.9.9"]), {"allowed": ["127.0.0.1"], "refused": []})
        self.assertIn("127.0.0.1", granted)
        wait(lambda: svc.target.host == "127.0.0.1" and svc.connections["127.0.0.1"].connected, 15)

    def test_an_address_in_settings_is_never_replaced(self):
        svc, _ = self.service()
        svc.set_target(service.Target("127.0.0.1", preset_host=BRIDGE))
        conn = svc.connections["127.0.0.1"]
        conn.http_failed = True
        svc.located_at = 0.0
        svc._relocate_if_lost(conn)
        time.sleep(0.5)
        self.assertEqual(self.ssdp.searches, [])
        self.assertEqual(self.probed, [])


if __name__ == "__main__":
    unittest.main()
