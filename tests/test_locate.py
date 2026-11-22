"""Finding the Kobra X without the user typing its address (locate.py), against FakeSsdp and FakeKobra on
127.0.0.1 only. Run: python3 -m unittest tests/test_locate.py -v"""

import json
import os
import socket
import sys
import tempfile
import threading
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
        with FakeSsdp(count=500) as ssdp:   # one sender, many replies: one result, the reply count is capped
            self.assertEqual(len(locate.search(timeout=1.0, addr=ssdp.addr, interfaces=[])), 1)

    def test_reply_size_is_capped(self):
        with FakeSsdp(reply=FakeSsdp.printer_reply() + b"X: " + b"Y" * 6000) as ssdp:
            found = locate.search(timeout=0.5, addr=ssdp.addr, interfaces=[])
        self.assertEqual(len(found), 1)
        self.assertLessEqual(sum(len(v) for v in found[0][1].values()), locate.MAX_REPLY)

    def test_silence_is_an_empty_answer(self):
        with FakeSsdp(reply=None) as ssdp:
            self.assertEqual(locate.search(timeout=0.3, addr=ssdp.addr, interfaces=[]), [])

    def test_only_answers_from_the_searched_port_count(self):
        """MEDIUM-2: the real printer answered from its port 1900; a datagram from another port is not an answer."""
        class Sock:
            replies = [(b"", ("10.25.7.41", 5353)), (b"", ("10.25.7.42", 1900))]

            def sendto(self, data, addr):
                pass

            def settimeout(self, t):
                pass

            def setsockopt(self, *a):
                pass

            def recvfrom(self, n):
                if not self.replies:
                    raise TimeoutError
                return self.replies.pop(0)
        with mock.patch.object(locate.time, "sleep"):
            found = locate._search_once(Sock(), "ac:3dprinter:", ("239.255.255.250", 1900), [], 1.0)
        self.assertEqual(found, [("10.25.7.42", {})])

    def test_a_bad_datagram_does_not_end_the_search(self):
        """Windows raises on recvfrom for an oversized datagram (WinError 10040) or an ICMP port unreachable
        (WinError 10054): one bad reply, the search goes on."""
        class Sock:
            replies = [OSError(10040, "message too long"), ConnectionResetError(10054, "reset"), (b"", ("10.25.7.41", 1900))]

            def sendto(self, data, addr):
                pass

            def settimeout(self, t):
                pass

            def setsockopt(self, *a):
                pass

            def recvfrom(self, n):
                if not self.replies:
                    raise TimeoutError
                item = self.replies.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        with mock.patch.object(locate.time, "sleep"):
            found = locate._search_once(Sock(), "ac:3dprinter:", ("239.255.255.250", 1900), [], 1.0)
        self.assertEqual(found, [("10.25.7.41", {})])

    def test_candidates_per_search_are_capped(self):
        class Sock:
            replies = [(b"", ("10.25.0.%d" % i, 1900)) for i in range(1, 20)]

            def sendto(self, data, addr):
                pass

            def settimeout(self, t):
                pass

            def setsockopt(self, *a):
                pass

            def recvfrom(self, n):
                if not self.replies:
                    raise TimeoutError
                return self.replies.pop(0)
        with mock.patch.object(locate.time, "sleep"):
            found = locate._search_once(Sock(), "ac:3dprinter:", ("239.255.255.250", 1900), [], 1.0)
        self.assertEqual(len(found), locate.MAX_CANDIDATES)
        self.assertEqual(locate.MAX_CANDIDATES, 4)

    def test_only_lan_addresses(self):
        for ip in ("10.25.7.41", "192.168.1.5", "172.16.0.9", "169.254.3.4", "127.0.0.1"):
            self.assertTrue(locate.lan_address(ip), ip)
        for ip in ("8.8.8.8", "239.255.255.250", "0.0.0.0", "printer.example", "::1", ""):
            self.assertFalse(locate.lan_address(ip), ip)


class Probe(unittest.TestCase):
    def test_kobra_x_answers_with_a_token_and_its_identity(self):
        with FakeKobra() as fake:
            fake.info_answer = {"token": fake.token, "deviceName": "Workshop KX", "modelName": "Anycubic Kobra X",
                                "cn": "SERIAL-A", "usn": "uuid:x", "ctrlInfoUrl": "http://203.0.113.9/ctrl"}
            info = locate.probe(fake.host, fake.http_port)
            self.assertEqual(info, {"ip": "127.0.0.1", "name": "Workshop KX", "model": "Anycubic Kobra X", "id": "SERIAL-A"})
            fake.info_answer = {"result": "moonraker"}
            with self.assertRaises(kobra.KobraError):
                locate.probe(fake.host, fake.http_port)

    def test_refused_port_is_not_a_printer(self):
        closed = socket.create_server(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        with self.assertRaises(kobra.KobraError) as cm:
            locate.probe("127.0.0.1", port, timeout=10)   # Windows retries a refused connect for about 2 s
        self.assertIn("refused", str(cm.exception).lower())


def kx(ip, ident, name="KX"):
    return {"ip": ip, "name": name, "model": "Anycubic Kobra X", "id": ident}


class Locate(unittest.TestCase):
    A = {"ip": "10.0.0.2", "id": "SERIAL-A", "fp": "aa" * 32}

    def never(self, *a):
        raise AssertionError("must not be called")

    def test_override_is_used_as_given(self):
        found = locate.locate("10.0.0.9", BRIDGE, probe=self.never, search=self.never)
        self.assertEqual((found.host, found.source), ("10.0.0.9", "override"))

    def test_the_one_printer_found_is_offered_never_used_by_itself(self):
        """GUI test 2026-11-20: a lone Kobra X on the network was connected to and remembered without a click."""
        def probe(ip):
            return refused(ip) if ip == BRIDGE else kx(ip, "SERIAL-B", "Workshop KX")
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", BRIDGE, probe=probe, search=lambda: [("10.0.0.41", {})])
        text = str(cm.exception)
        self.assertIn("The printer preset points to 10.25.16.41, which is not an Anycubic printer", text)
        self.assertIn("Found Workshop KX (Anycubic Kobra X) at 10.0.0.41 on the network. Use it?", text)
        self.assertEqual([(c["ip"], c["needs_allow"], c["different"]) for c in cm.exception.candidates],
                         [("10.0.0.41", False, False)])
        self.assertEqual(cm.exception.pending, [])

    def test_remembered_printer_at_its_address_without_search(self):
        found = locate.locate("", BRIDGE, self.A, probe=lambda ip: kx(ip, "SERIAL-A"), search=self.never)
        self.assertEqual((found.host, found.source, found.expect_fp), ("10.0.0.2", "remembered", "aa" * 32))

    def test_remembered_printer_found_again_at_a_new_address(self):
        def probe(ip):
            return refused(ip) if ip == "10.0.0.2" else kx(ip, "SERIAL-A")
        found = locate.locate("", "", self.A, probe=probe, search=lambda: [("10.0.0.9", {})])
        self.assertEqual((found.host, found.expect_fp), ("10.0.0.9", "aa" * 32))   # the pin still has to match

    def test_another_printer_is_never_adopted_even_when_it_is_the_only_one(self):
        """HIGH-1: A is remembered and gone; only B answers. B is offered, not used."""
        def probe(ip):
            return refused(ip) if ip == "10.0.0.2" else kx(ip, "SERIAL-B")
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", self.A, probe=probe, search=lambda: [("10.0.0.3", {})])
        self.assertIn("A different Anycubic printer answered at 10.0.0.3. Use it?", str(cm.exception))
        self.assertEqual([(c["ip"], c["different"]) for c in cm.exception.candidates], [("10.0.0.3", True)])
        self.assertEqual(cm.exception.pending, [])

    def test_another_printer_at_the_remembered_address_is_offered_too(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", self.A, probe=lambda ip: kx(ip, "SERIAL-B"), search=list)
        self.assertEqual([c["ip"] for c in cm.exception.candidates], ["10.0.0.2"])

    def test_remembered_printer_offline_keeps_its_address(self):
        found = locate.locate("", "", self.A, probe=refused, search=list)
        self.assertEqual((found.host, found.source), ("10.0.0.2", "remembered"))

    def test_preset_used_when_a_kobra_x_answers_there(self):
        found = locate.locate("", "10.25.7.41", probe=lambda ip: kx(ip, "S"), search=self.never)
        self.assertEqual((found.host, found.source, found.expect_fp), ("10.25.7.41", "preset", ""))

    def test_several_printers_are_offered(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=lambda ip: kx(ip, ip), search=lambda: [("10.0.0.2", {}), ("10.0.0.3", {})])
        self.assertEqual([c["ip"] for c in cm.exception.candidates], ["10.0.0.2", "10.0.0.3"])

    def test_nothing_found_explains_the_bridge(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", BRIDGE, probe=refused, search=list)
        text = str(cm.exception)
        self.assertIn("something answers at 10.25.16.41 but it is not an Anycubic printer in LAN mode", text)
        self.assertIn("comes from the printer preset", text)
        self.assertIn("Settings > Printer address", text)
        self.assertIn("LAN mode is on", text)
        self.assertTrue(cm.exception.no_target)

    def test_a_candidate_that_is_not_a_kobra_x_is_dropped_and_remembered(self):
        def probe(ip):
            raise kobra.KobraError("%s answers /info without a LAN token" % ip, code="no_token")
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=probe, search=lambda: [("10.25.3.3", {})])
        self.assertEqual((cm.exception.candidates, cm.exception.pending, cm.exception.rejected), ([], [], ["10.25.3.3"]))
        self.assertIn("No Anycubic printer answered", str(cm.exception))
        with self.assertRaises(locate.NotFound):   # skipped this session: not probed again
            locate.locate("", "", probe=self.never, search=lambda: [("10.25.3.3", {})], skip={"10.25.3.3"})

    def test_one_ungranted_candidate_waits_for_the_users_click(self):
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=self.never, search=lambda: [("10.0.0.41", {})], allowed=lambda ip: False)
        self.assertEqual(cm.exception.pending, [])
        self.assertEqual([c["needs_allow"] for c in cm.exception.candidates], [True])
        self.assertIn("Allow and use", str(cm.exception))

    def test_ungranted_preset_address_is_not_probed(self):
        """The preset's address is no longer declared at load: until it is allowed it is offered, not probed from
        this worker thread (each refused attempt there queues another OrcaSlicer dialog)."""
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "10.0.0.41", probe=self.never, search=lambda: [("10.0.0.41", {})],
                          allowed=lambda ip: False)
        self.assertEqual([c["ip"] for c in cm.exception.candidates], ["10.0.0.41"])

    def test_several_ungranted_candidates_are_never_asked_about_by_themselves(self):
        """MEDIUM-2: spoofed empty replies must not each raise an OrcaSlicer dialog: the user picks."""
        replies = [("10.25.%d.1" % i, {}) for i in range(3)]
        with self.assertRaises(locate.NotFound) as cm:
            locate.locate("", "", probe=self.never, search=lambda: replies, allowed=lambda ip: False)
        self.assertEqual(cm.exception.pending, [])
        self.assertEqual([c["needs_allow"] for c in cm.exception.candidates], [True] * 3)


class AddressBook(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "addresses.json")
        self.book = locate.Addresses(self.path)

    def test_one_printer_is_not_recorded_for_two_presets(self):
        self.book.put("Kobra left", "10.0.0.2", "SERIAL-A", "aa" * 32)
        self.book.put("Kobra right", "10.0.0.3", "SERIAL-B", "bb" * 32)
        with self.assertRaises(ValueError):
            self.book.put("Kobra left", "10.0.0.3", "SERIAL-A", "aa" * 32)   # B's address for A's preset
        self.assertEqual(self.book.get("Kobra left")["ip"], "10.0.0.2")
        self.book.put("Kobra copy", "10.0.0.2", "SERIAL-A", "aa" * 32)   # the same printer for another preset is fine

    def test_bad_entries_read_as_nothing(self):
        with open(self.path, "w") as f:
            json.dump({"printers": {"a": {"ip": "8.8.8.8"}, "b": "10.0.0.2", "c": {"ip": "10.0.0.4", "fp": "XYZ"},
                                    "d": {"ip": "10.0.0.5", "id": 7}, "e": {"ip": "10.0.0.6", "id": "S", "fp": ""}}}, f)
        self.assertEqual(self.book.hosts(), ["10.0.0.6"])
        with open(self.path, "w") as f:
            f.write('{"printers": {"x": {"ip": "10.0.0.7"}}, "pad": "%s"}' % ("y" * locate.Addresses.MAX_BYTES))
        self.assertEqual(self.book.hosts(), [])


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
        self.fake.info_answer = {"token": self.fake.token, "cn": "SERIAL-A", "deviceName": "Workshop KX",
                                 "modelName": "Anycubic Kobra X"}
        self.fake.reply("info", "query", {})
        self.fake.reply("print", "query", {}, state="free")
        self.fake.reply("multiColorBox", "getInfo", {"multi_color_box": []})
        self.ssdp = FakeSsdp()
        self.addCleanup(self.ssdp.stop)
        self.folder = tempfile.mkdtemp()
        self.book = locate.Addresses(os.path.join(self.folder, "addresses.json"))
        self.probed, self.lost = [], False

    def probe(self, ip):
        self.probed.append(ip)
        return refused(ip) if ip == BRIDGE or self.lost else locate.probe(ip, self.fake.http_port)

    def service(self, **kw):
        published = []
        options = {"probe": self.probe, "search": lambda: locate.search(timeout=1.0, addr=self.ssdp.addr, interfaces=[]),
                   **kw}
        svc = service.Service(published.append, lambda m: None, cert_dir=self.folder, tls=lambda: None,
                              http_port=self.fake.http_port, mqtt_port=self.fake.mqtt_port, camera_factory=FakeCamera,
                              addresses_path=os.path.join(self.folder, "addresses.json"), **options)
        self.addCleanup(svc.close)
        return svc, published

    def reply(self, published, rid, timeout=20):
        return wait(lambda: next((m for m in published if m.get("id") == rid), None), timeout)

    def hello(self, svc, published, rid="h", key="Anycubic Kobra X", agent="kobracontrol", choose=True):
        """The tab's hello. choose: when the printer is offered, the user picks it (the only way a printer found on
        the network gets used), and the reply of the next hello is returned."""
        svc.set_target(service.Target("", preset_host=BRIDGE, preset_key=key, preset_agent=agent))
        svc.submit(rid, "connect", {})
        reply = self.reply(published, rid)
        if choose and reply.get("candidates"):
            svc.submit(rid + "-pick", "choose_printer", {"host": reply["candidates"][0]["ip"]})
            self.reply(published, rid + "-pick")
            svc.submit(rid + "-again", "connect", {})
            reply = self.reply(published, rid + "-again")
        return reply

    def test_a_found_printer_is_used_and_remembered_only_once_chosen(self):
        """GUI test 2026-11-20: opening a tab must not connect to, or remember, a printer the user did not choose."""
        svc, published = self.service()
        reply = self.hello(svc, published, choose=False)
        self.assertTrue(reply["no_target"])
        self.assertIn("10.25.16.41, which is not an Anycubic printer", reply["error"])
        self.assertIn("Found Workshop KX (Anycubic Kobra X) at 127.0.0.1 on the network. Use it?", reply["error"])
        self.assertEqual([(c["ip"], c["needs_allow"]) for c in reply["candidates"]], [("127.0.0.1", False)])
        svc.submit("h-again", "connect", {})   # another tab (Settings) says hello: still only offered
        self.assertTrue(self.reply(published, "h-again")["no_target"])
        self.assertEqual(svc.connections, {})
        self.assertIsNone(self.book.get("Anycubic Kobra X"))
        self.assertFalse(os.path.exists(os.path.join(self.folder, "printers.json")))
        reply = self.hello(svc, published, "h2")
        self.assertEqual((reply["result"]["address"], reply["result"]["source"]), ("127.0.0.1", "chosen"))
        self.assertTrue(svc.connections["127.0.0.1"].connected)
        self.assertNotIn(BRIDGE, svc.connections)   # never a connection loop for the bridge
        wait(lambda: self.book.get("Anycubic Kobra X"))   # recorded at the first connect: address, identity, pin
        self.assertEqual(self.book.get("Anycubic Kobra X"), {"ip": "127.0.0.1", "id": "SERIAL-A", "fp": ""})
        svc.close()
        searches = len(self.ssdp.searches)
        svc2, published2 = self.service()
        reply = self.hello(svc2, published2, "h3", choose=False)
        self.assertEqual(reply["result"]["source"], "remembered")
        self.assertEqual(len(self.ssdp.searches), searches)   # instant: no new search

    def test_never_remembered_under_another_agents_preset(self):
        """GUI test 2026-11-20: with a Snapmaker U1 preset selected (printer agent u1control), the Kobra X's address
        was written under that preset. A printer chosen there is used, never remembered, and an address recorded
        there earlier is not used."""
        self.book.put("Snapmaker U1 (0.4 nozzle)", "127.0.0.1", "SERIAL-A", "")   # left by an earlier version
        svc, published = self.service()
        reply = self.hello(svc, published, key="Snapmaker U1 (0.4 nozzle)", agent="u1control", choose=False)
        self.assertTrue(reply["no_target"])   # the old record is not used: the printer is only offered
        self.assertEqual(svc.connections, {})
        self.book.put("Snapmaker U1 (0.4 nozzle)", "10.0.0.2", "SERIAL-OTHER", "")
        reply = self.hello(svc, published, "h2", key="Snapmaker U1 (0.4 nozzle)", agent="u1control")
        self.assertEqual(reply["result"]["source"], "chosen")
        wait(lambda: svc.connections["127.0.0.1"].connected, 15)
        time.sleep(0.5)   # the record thread would have run by now
        self.assertEqual(self.book.get("Snapmaker U1 (0.4 nozzle)")["ip"], "10.0.0.2")
        self.assertEqual(self.book.hosts(), ["10.0.0.2"])

    def test_nothing_found_is_a_calm_no_target_reply(self):
        self.ssdp.reply = None
        svc, published = self.service()
        reply = self.hello(svc, published)
        self.assertTrue(reply["no_target"])
        self.assertEqual(reply["candidates"], [])
        self.assertIn("not an Anycubic printer in LAN mode", reply["error"])
        self.assertEqual(svc.connections, {})

    def test_choose_and_search_again(self):
        self.ssdp.reply = None
        svc, published = self.service()
        self.hello(svc, published)
        svc.locate_error = locate.NotFound("2 found", [{"ip": "127.0.0.1", "name": "A", "model": ""},
                                                       {"ip": "10.0.0.3", "name": "B", "model": ""}])
        svc.submit("c", "choose_printer", {"host": "8.8.8.8"})
        self.assertIn("not among", wait(lambda: next((m for m in published if m.get("id") == "c"), None))["error"])
        svc.submit("c2", "choose_printer", {"host": "127.0.0.1"})
        wait(lambda: next((m for m in published if m.get("id") == "c2"), None))
        self.assertEqual((svc.target.host, svc.target.source), ("127.0.0.1", "chosen"))
        svc.submit("s", "search_printer", {})
        reply = wait(lambda: next((m for m in published if m.get("id") == "s"), None), 10)
        self.assertEqual(reply.get("result", reply)["address"], "127.0.0.1")

    def test_a_different_printer_is_offered_never_adopted(self):
        """HIGH-1: A remembered for the preset and gone; the only Kobra X answering is B. Nothing switches to B and
        the address book still says A."""
        self.book.put("Kobra left", "10.0.0.2", "SERIAL-OTHER", "")
        svc, published = self.service(probe=lambda ip: refused(ip) if ip != "127.0.0.1" else self.probe(ip))
        reply = self.hello(svc, published, key="Kobra left", choose=False)
        self.assertIn("A different Anycubic printer answered at 127.0.0.1. Use it?", reply["error"])
        self.assertEqual([(c["ip"], c["different"]) for c in reply["candidates"]], [("127.0.0.1", True)])
        self.assertEqual(svc.target.host, "")
        self.assertNotIn("127.0.0.1", svc.connections)
        self.assertEqual(self.book.get("Kobra left")["ip"], "10.0.0.2")

    def test_a_certificate_that_does_not_match_the_pin_is_refused(self):
        """HIGH-1 / MEDIUM-4: the remembered identity answers /info, but the session presents another certificate."""
        self.book.put("Anycubic Kobra X", "127.0.0.1", "SERIAL-A", "ab" * 32)
        svc, published = self.service()
        self.hello(svc, published, choose=False)
        wait(lambda: getattr(svc.locate_error, "candidates", None), 15)
        self.assertIn("its certificate is not the one", str(svc.locate_error))
        self.assertEqual(svc.target.host, "")
        wait(lambda: "127.0.0.1" not in svc.connections)
        self.assertEqual(self.book.get("Anycubic Kobra X")["fp"], "ab" * 32)   # the known printer stays remembered
        wait(lambda: {"type": "selection_changed"} in published, 15)   # published after the release

    def test_a_switch_of_address_is_a_printer_switch(self):
        """HIGH-1: a new address bumps the generation and resets the per-printer state; a command queued for the old
        generation is refused as stale and never reaches the new address."""
        svc, published = self.service()
        self.hello(svc, published)
        gen = svc.generation
        svc.bindings, svc._units = {0: 7}, {"x": 1}
        with svc.lock:   # the worker reaches its generation check only after the address has changed
            svc.submit("q", "set_fan", {"pct": 40}, gen=gen)
            svc._use_address(gen, locate.Found("127.0.0.9", "discovered", identity="SERIAL-A"))
        reply = wait(lambda: next((m for m in published if m.get("id") == "q"), None))
        self.assertEqual(reply["error"], service.STALE)
        self.assertEqual(svc.generation, gen + 1)
        self.assertEqual((svc.bindings, svc._units), ({}, {}))
        self.assertIn({"type": "selection_changed"}, published)
        wait(lambda: "127.0.0.1" not in svc.connections)

    def test_no_relocation_while_printing_or_tracking(self):
        svc, published = self.service()
        self.hello(svc, published)
        conn = svc.connections["127.0.0.1"]
        svc._last_state["127.0.0.1"] = "printing"
        svc.located_at -= service.RELOCATE_EVERY
        conn.http_failed = True
        with mock.patch.object(svc, "_start_locate") as start:   # the only way a search starts: asserted on calls
            svc._relocate_if_lost(conn)
            self.assertTrue(any("was printing when it stopped answering" in m.get("text", "") for m in published))
            svc._last_state["127.0.0.1"] = "idle"
            svc.located_at -= service.RELOCATE_EVERY
            with mock.patch.object(svc, "_tracking", return_value=True):
                svc._relocate_if_lost(conn)
            start.assert_not_called()
            svc.located_at -= service.RELOCATE_EVERY
            svc._relocate_if_lost(conn)   # idle and nothing tracked: now it may search
            start.assert_called_once()

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
        wait(lambda: not svc._locating.locked() and len(self.ssdp.searches) > searches, 10)
        svc._join_locators(10)
        self.assertEqual(len(self.ssdp.searches) - searches, 2)   # one search: its two ac:3dprinter: packets

    def test_a_found_printer_not_yet_allowed_is_asked_about_only_on_the_users_click(self):
        granted = set()
        svc, published = self.service(granted=granted)
        reply = self.hello(svc, published, choose=False)
        self.assertEqual(reply["pending"], [])
        self.assertEqual([c["needs_allow"] for c in reply["candidates"]], [True])
        self.assertNotIn("127.0.0.1", self.probed)   # not probed before it is allowed
        dialogs = []
        with mock.patch.object(svc, "_ask_orcaslicer", dialogs.append):
            self.assertEqual(svc.allow(["127.0.0.1"]), {"allowed": [], "refused": []})   # not a click: nothing
            self.assertEqual(dialogs, [])
            self.assertEqual(svc.allow(["127.0.0.1", "10.9.9.9"], user=True), {"allowed": ["127.0.0.1"], "refused": []})
        self.assertEqual(dialogs, ["127.0.0.1"])
        self.assertIn("127.0.0.1", granted)
        wait(lambda: svc.target.host == "127.0.0.1" and svc.connections["127.0.0.1"].connected, 15)
        self.assertEqual(svc.target.source, "chosen")

    def test_a_refused_permission_is_not_asked_again_until_search_again(self):
        svc, published = self.service(granted=set())
        self.hello(svc, published, choose=False)
        with mock.patch.object(svc, "_ask_orcaslicer", side_effect=PermissionError):
            self.assertEqual(svc.allow(["127.0.0.1"], user=True)["refused"], ["127.0.0.1"])
        self.assertIn("127.0.0.1", svc._rejected)
        svc.submit("s", "search_printer", {})
        wait(lambda: next((m for m in published if m.get("id") == "s"), None), 10)
        self.assertEqual(svc._rejected, set())

    def test_a_lost_printer_with_another_answering_keeps_the_offer_on_hello(self):
        """N1: the known printer stops answering and another Kobra X answers: hello carries the offer while the known
        address is down, and choosing it switches with a new generation."""
        svc, published = self.service()
        self.hello(svc, published)
        gen = svc.generation
        conn = svc.connections["127.0.0.1"]
        self.fake.stop()   # A is gone
        wait(lambda: not conn.connected, 15)
        svc.locate_error = locate.NotFound("A different Anycubic printer answered at 10.0.0.3. Use it?",
                                           [{"ip": "10.0.0.3", "name": "B", "model": "", "needs_allow": False,
                                             "different": True}])
        for rid in ("h2", "h3"):
            svc.submit(rid, "connect", {})
            reply = wait(lambda r=rid: next((m for m in published if m.get("id") == r), None), 20)
            self.assertTrue(reply["no_target"])
            self.assertEqual([c["ip"] for c in reply["candidates"]], ["10.0.0.3"])
            self.assertIn("Use it?", reply["error"])
        with mock.patch.object(svc, "probe", lambda ip: {"ip": ip, "name": "B", "model": "", "id": "SERIAL-B"}):
            svc.submit("c", "choose_printer", {"host": "10.0.0.3"})
            reply = wait(lambda: next((m for m in published if m.get("id") == "c"), None), 15)
        self.assertEqual(reply["result"], {"address": "10.0.0.3"})
        self.assertEqual((svc.target.host, svc.generation), ("10.0.0.3", gen + 1))

    def test_the_record_keeps_the_values_of_the_moment_it_connected(self):
        """N3: the record thread gets the identity at connect time, not the target's later state."""
        svc, published = self.service()
        recorded = []
        with mock.patch.object(svc, "_record", lambda *a: recorded.append(a)):
            self.hello(svc, published)
            wait(lambda: recorded)
        self.assertEqual(recorded[0][:3], ("Anycubic Kobra X", "127.0.0.1", "SERIAL-A"))

    def test_searches_with_new_spoofed_addresses_raise_no_dialog_by_themselves(self):
        """M-A: OrcaSlicer's dialog comes only from the user's click: lone candidates are only offered."""
        self.ssdp.reply = None
        addresses = iter(["10.25.0.11", "10.25.0.12", "10.25.0.13"])
        # probe: nothing is ever contacted (these stand for spoofed LAN addresses); dialogs: recorded where the
        # plugin raises them, not by patching the socket module (which the probe's own lookups would also hit).
        svc, published = self.service(granted=set(), search=lambda: [(next(addresses), {})], probe=refused)
        dialogs = []
        with mock.patch.object(svc, "_ask_orcaslicer", dialogs.append):
            for i in range(3):
                svc.set_target(service.Target("", preset_host="", preset_key="P%d" % i))
                svc.submit("h%d" % i, "connect", {})
                reply = wait(lambda: next((m for m in published if m.get("id") == "h%d" % i), None), 20)
                for _ in range(2):   # the page asking again for the same address, or a repeated message
                    svc.allow(reply["pending"] or [c["ip"] for c in reply["candidates"]])
                svc._join_locators(10)
        self.assertEqual(dialogs, [])

    def test_no_dialog_by_itself_when_a_printer_is_remembered_for_the_preset(self):
        self.book.put("Anycubic Kobra X", "10.0.0.2", "SERIAL-OTHER", "")
        svc, published = self.service(granted=set(), probe=refused)
        reply = self.hello(svc, published, choose=False)
        self.assertEqual(reply["pending"], [])
        self.assertEqual([c["needs_allow"] for c in reply["candidates"]], [True])

    def test_the_pin_follows_the_printer_to_a_new_address(self):
        """M-B: the certificate pin is kept per printer identity: a known identity at a new address must show the
        pinned certificate."""
        self.book.put("Anycubic Kobra X", "10.0.0.2", "SERIAL-A", "")   # remembered at an earlier address
        svc, published = self.service(probe=lambda ip: refused(ip) if ip == "10.0.0.2" else self.probe(ip))
        svc.pins.check("id:SERIAL-A", "cd" * 32)   # pinned there
        self.hello(svc, published, choose=False)
        wait(lambda: getattr(svc.locate_error, "candidates", None), 15)
        self.assertIn("its certificate is not the one", str(svc.locate_error))

    def test_an_address_in_settings_is_never_replaced(self):
        svc, _ = self.service()
        svc.set_target(service.Target("127.0.0.1", preset_host=BRIDGE))
        conn = svc.connections["127.0.0.1"]
        conn.http_failed = True
        svc.located_at = 0.0
        with mock.patch.object(svc, "_start_locate") as start:
            svc._relocate_if_lost(conn)
        start.assert_not_called()
        self.assertEqual(self.ssdp.searches, [])
        self.assertEqual(self.probed, [])

    def test_close_during_a_slow_search_leaves_nothing_running(self):
        """HIGH-2: a locate thread that finishes after close() must not create a connection."""
        release = threading.Event()

        def slow_search():
            release.wait(5)
            return [("127.0.0.1", {})]
        svc, published = self.service(search=slow_search)
        svc.set_target(service.Target("", preset_host=BRIDGE, preset_key="Anycubic Kobra X"))
        wait(lambda: svc._locating.locked())
        locators = list(svc._locators)
        closer = threading.Thread(target=svc.close)
        closer.start()
        wait(lambda: svc.closed)
        release.set()   # the search ends only after close() has begun
        closer.join(30)
        for t in locators:   # every locate thread has finished: nothing more can happen after these asserts
            t.join(30)
            self.assertFalse(t.is_alive())
        self.assertEqual(svc.connections, {})
        self.assertFalse([t for t in threading.enumerate() if t.name == "kobracontrol-link" and t.is_alive()
                          and getattr(t, "_target", None) and getattr(t._target, "__self__", None) is not None
                          and t._target.__self__.host == "127.0.0.1" and not t._target.__self__._stop.is_set()])
        svc.close()   # idempotent


if __name__ == "__main__":
    unittest.main()
