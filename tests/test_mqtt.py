"""MQTT 3.1.1 client against the fake broker: framing, CONNACK codes, SUBACK, keepalive, callbacks, close."""

import os
import shutil
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol"), os.path.join(ROOT, "tests")]

import mqtt  # noqa: E402
from fake_kobra import FakeKobra, make_tls_files  # noqa: E402

SIZES = (0, 127, 128, 16383, 16384, 200000)


def wait_for(cond, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FramingTests(unittest.TestCase):
    def test_remaining_length_vectors(self):
        vectors = {0: "00", 127: "7f", 128: "8001", 16383: "ff7f", 16384: "808001", 200000: "c09a0c",
                   2097151: "ffff7f", 2097152: "80808001", 268435455: "ffffff7f"}
        for n, hexa in vectors.items():
            self.assertEqual(mqtt.encode_length(n).hex(), hexa, n)
            self.assertEqual(mqtt.decode_length(bytes.fromhex(hexa), 0), (n, len(hexa) // 2))

    def test_length_out_of_range(self):
        with self.assertRaises(ValueError):
            mqtt.encode_length(268435456)

    def test_incomplete_and_malformed_length(self):
        self.assertIsNone(mqtt.decode_length(b"\x80\x80", 0))
        with self.assertRaises(mqtt.MqttError):
            mqtt.decode_length(b"\xff\xff\xff\xff\x01", 0)

    def test_packet_above_cap_is_refused(self):
        """M3: a declared length above MAX_PACKET is an error before any byte of it is buffered."""
        buf = bytearray(b"\x30" + mqtt.encode_length(mqtt.MAX_PACKET + 1))
        with self.assertRaisesRegex(mqtt.MqttError, "too large"):
            mqtt.split_packets(buf)
        ok = bytearray(mqtt.packet(0x30, b"\x00\x01t" + b"x" * (mqtt.MAX_PACKET - 3)))
        self.assertEqual(len(mqtt.split_packets(ok)[0][2]), mqtt.MAX_PACKET)

    def test_oversized_connack_is_refused(self):
        c = mqtt.Client("h", 1, "x", timeout=1)
        sock = mock.Mock()
        sock.recv.return_value = b"\x20" + mqtt.encode_length(mqtt.MAX_PACKET + 1)
        with self.assertRaisesRegex(mqtt.MqttError, "too large"):
            c._await_connack(sock)

    def test_split_packets_byte_by_byte(self):
        wire = mqtt.packet(0x30, b"\x00\x01t" + b"x" * 300) + mqtt.packet(0xD0, b"")
        buf, out = bytearray(), []
        for b in wire:
            buf.append(b)
            out += mqtt.split_packets(buf)
        self.assertEqual([(p[0], len(p[2])) for p in out], [(3, 303), (13, 0)])
        self.assertEqual(buf, b"")

    def test_parse_publish_skips_packet_id_for_qos1(self):
        self.assertEqual(mqtt.parse_publish(2, b"\x00\x01t\x00\x07hi"), ("t", b"hi"))
        self.assertEqual(mqtt.parse_publish(0, b"\x00\x01thi"), ("t", b"hi"))


class TcpKeepaliveTests(unittest.TestCase):
    """Ported from KX-Bridge tests/test_tcp_keepalive.py."""

    def test_sets_short_keepalive_options(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(s.close)
        mqtt.enable_tcp_keepalive(s)
        self.assertNotEqual(s.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE), 0)
        idle = getattr(socket, "TCP_KEEPIDLE", getattr(socket, "TCP_KEEPALIVE", None))
        for opt, limit in ((idle, 10), (getattr(socket, "TCP_KEEPINTVL", None), 5),
                           (getattr(socket, "TCP_KEEPCNT", None), 5)):
            if opt is not None:
                self.assertLessEqual(s.getsockopt(socket.IPPROTO_TCP, opt), limit)
        if hasattr(socket, "TCP_USER_TIMEOUT"):
            self.assertTrue(0 < s.getsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT) <= 20000)

    def test_unsupported_platform_does_not_raise(self):
        s = mock.Mock()
        s.setsockopt.side_effect = OSError("unsupported")
        mqtt.enable_tcp_keepalive(s)


class OfflineUnitTests(unittest.TestCase):
    """Reader/writer edge cases driven without a broker."""

    def make(self):
        closes, messages = [], []
        c = mqtt.Client("h", 1, "x", on_close=closes.append, on_message=lambda t, p: messages.append(p))
        c._sock, c._open = mock.Mock(), True
        c._last_in = c._last_out = time.monotonic()
        return c, closes, messages

    def test_failed_write_marks_session_dead(self):
        c, _, _ = self.make()
        c._sock.sendall.side_effect = OSError("broken pipe")
        with self.assertRaises(mqtt.MqttError):
            c.publish("a", b"x")
        self.assertFalse(c.connected)
        c._sock.shutdown.assert_called_once()

    def test_unexpected_reader_error_closes_session(self):
        """M1: any exception in the reader ends in a closed session with on_close, not a dead thread."""
        c, closes, _ = self.make()
        c._recv = mock.Mock(side_effect=RuntimeError("boom"))
        with self.assertLogs(mqtt.log, "ERROR"):
            c._run()
        self.assertFalse(c.connected)
        self.assertEqual(len(closes), 1)
        self.assertIn("boom", closes[0])

    def test_brief_empty_reads_are_tolerated_then_eof(self):
        c, closes, messages = self.make()
        pkt = mqtt.packet(0x30, b"\x00\x01t" + b"hi")
        reads = [b"", b"", None, pkt] + [b""] * mqtt.EMPTY_READS_EOF
        c._recv = mock.Mock(side_effect=reads)
        c._run()
        self.assertEqual(messages, [b"hi"])
        self.assertEqual(len(closes), 1)
        self.assertIn("closed by the printer", closes[0])
        self.assertGreater(c.last_rx, 0)


class BrokerCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKobra().start()
        self.addCleanup(self.fake.stop)
        self.messages, self.closes = [], []

    def client(self, password=None, connect=True, **kw):
        c = mqtt.Client(self.fake.host, self.fake.mqtt_port, "kobracontrol_test", username=self.fake.username,
                        password=self.fake.password if password is None else password, timeout=3,
                        on_message=lambda t, p: self.messages.append((t, p)), on_close=self.closes.append, **kw)
        self.addCleanup(c.close)
        if connect:
            c.connect()
            c.subscribe("anycubic/#")
        return c


class ConnectTests(BrokerCase):
    def test_connect_subscribe(self):
        c = self.client()
        self.assertTrue(c.connected)
        self.assertEqual(self.fake.client_ids, ["kobracontrol_test"])
        self.assertEqual(self.fake.subscriptions, ["anycubic/#"])
        reader = [t for t in threading.enumerate() if t.name.startswith("kobracontrol-mqtt")]
        self.assertTrue(reader and all(t.daemon for t in reader))

    def test_connect_enables_tcp_keepalive(self):
        with mock.patch.object(mqtt, "enable_tcp_keepalive", wraps=mqtt.enable_tcp_keepalive) as spy:
            self.client()
        spy.assert_called_once()

    def test_packet_id_wraps(self):
        c = self.client()
        c._next_id = 65535
        c.subscribe("again/#")
        self.assertEqual(c._next_id, 1)
        self.assertEqual(self.fake.subscriptions[-1], "again/#")

    def test_unencodable_credentials_raise_mqtt_error(self):
        """M1: a 70000-byte password is an MqttError, not an OverflowError."""
        with self.assertRaises(mqtt.MqttError):
            self.client(password="p" * 70000)
        c = self.client()
        with self.assertRaises(mqtt.MqttError):
            c.publish("t" * 70000, b"")

    def test_oversized_packet_from_broker_closes(self):
        """M3: the reader refuses a packet declared above MAX_PACKET and closes."""
        c = self.client()
        self.fake._sessions[0].send(b"\x30" + mqtt.encode_length(mqtt.MAX_PACKET + 1) + b"\x00")
        self.assertTrue(wait_for(lambda: self.closes))
        self.assertIn("too large", self.closes[0])
        self.assertFalse(c.connected)

    def test_bad_password_is_auth_error(self):
        with self.assertRaises(mqtt.MqttAuthError) as cm:
            self.client(password="not-the-pass-xyz")
        self.assertNotIn("not-the-pass-xyz", str(cm.exception))
        self.assertNotIn(self.fake.password, str(cm.exception))

    def test_not_authorized_is_auth_error(self):
        self.fake.connack_code = 5
        with self.assertRaises(mqtt.MqttAuthError):
            self.client()

    def test_other_refusal(self):
        self.fake.connack_code = 3
        with self.assertRaises(mqtt.MqttError) as cm:
            self.client()
        self.assertNotIsInstance(cm.exception, mqtt.MqttAuthError)
        self.assertEqual(cm.exception.code, 3)

    def test_suback_failure(self):
        self.fake.suback_code = 0x80
        c = self.client(connect=False)
        c.connect()
        with self.assertRaises(mqtt.MqttError):
            c.subscribe("anycubic/#")

    def test_unreachable(self):
        port = socket.create_server(("127.0.0.1", 0))
        free = port.getsockname()[1]
        port.close()
        c = mqtt.Client("127.0.0.1", free, "x", timeout=1)
        with self.assertRaises(mqtt.MqttError):
            c.connect()
        self.assertFalse(c.connected)

    def test_silent_server_times_out(self):
        server = socket.create_server(("127.0.0.1", 0))
        self.addCleanup(server.close)
        c = mqtt.Client("127.0.0.1", server.getsockname()[1], "x", timeout=0.3)
        start = time.monotonic()
        with self.assertRaises(mqtt.MqttError):
            c.connect()
        self.assertLess(time.monotonic() - start, 2)


class TrafficTests(BrokerCase):
    def test_publish_sizes_to_broker(self):
        c = self.client()
        for n in SIZES:
            c.publish("a/b", b"p" * n)
        self.assertTrue(wait_for(lambda: len(self.fake.requests) == len(SIZES)))
        self.assertEqual([len(r["raw"]) for r in self.fake.requests], list(SIZES))
        self.assertEqual(self.fake.requests[0]["topic"], "a/b")

    def test_receive_sizes_from_broker(self):
        self.client()
        for n in SIZES:
            self.fake.publish_raw("anycubic/x", bytes([n % 251]) * n)
        self.assertTrue(wait_for(lambda: len(self.messages) == len(SIZES)))
        self.assertEqual([(t, len(p)) for t, p in self.messages], [("anycubic/x", n) for n in SIZES])
        self.assertEqual(self.messages[-1][1], bytes([200000 % 251]) * 200000)

    def test_messages_split_across_reads(self):
        self.client()
        self.fake.chunk_size = 1
        for i in range(3):
            self.fake.publish_raw("anycubic/s", b'{"n": %d}' % i)
        self.assertTrue(wait_for(lambda: len(self.messages) == 3))
        self.assertEqual([p for _, p in self.messages], [b'{"n": 0}', b'{"n": 1}', b'{"n": 2}'])

    def test_str_payload_is_utf8(self):
        c = self.client()
        c.publish("a", "é")
        self.assertTrue(wait_for(lambda: self.fake.requests))
        self.assertEqual(self.fake.requests[0]["raw"], "é".encode())

    def test_concurrent_publish(self):
        c = self.client()

        def burst(k):
            for i in range(50):
                c.publish("t/%d" % k, b"%d-%d" % (k, i) * 20)
        threads = [threading.Thread(target=burst, args=(k,)) for k in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(wait_for(lambda: len(self.fake.requests) == 400))
        for r in self.fake.requests:
            k = r["topic"].split("/")[1]
            self.assertTrue(r["raw"].startswith(k.encode() + b"-"), r["raw"][:20])

    def test_callback_exception_does_not_kill_reader(self):
        def boom(topic, payload):
            self.messages.append(payload)
            if payload == b"1":
                raise RuntimeError("boom")
        c = self.client()
        c.on_message = boom
        with self.assertLogs(mqtt.log, "ERROR"):
            self.fake.publish_raw("anycubic/x", b"1")
            self.fake.publish_raw("anycubic/x", b"2")
            self.assertTrue(wait_for(lambda: self.messages == [b"1", b"2"]))
        self.assertTrue(c.connected)

    def test_malformed_packet_closes(self):
        c = self.client()
        self.fake._sessions[0].send(b"\x30\xff\xff\xff\xff\xff")
        self.assertTrue(wait_for(lambda: self.closes))
        self.assertIn("protocol", self.closes[0])
        self.assertFalse(c.connected)


class KeepaliveTests(BrokerCase):
    def test_pings_keep_session_alive(self):
        c = self.client(keepalive=1)
        time.sleep(2.2)
        self.assertGreaterEqual(self.fake.pings, 2)
        self.assertTrue(c.connected)
        self.assertEqual(self.closes, [])

    def test_unanswered_pings_close(self):
        self.fake.answer_pings = False
        c = self.client(keepalive=1)
        self.assertTrue(wait_for(lambda: self.closes, 4))
        self.assertIn("keepalive", self.closes[0])
        self.assertFalse(c.connected)


class CloseTests(BrokerCase):
    def test_close_is_idempotent_prompt_and_sends_disconnect(self):
        c = self.client()
        start = time.monotonic()
        c.close()
        c.close()
        self.assertLess(time.monotonic() - start, 1)
        self.assertFalse(c.connected)
        self.assertTrue(wait_for(lambda: self.fake.disconnects == 1))
        self.assertTrue(wait_for(lambda: self.closes == ["closed"]))
        with self.assertRaises(mqtt.MqttError):
            c.publish("a", b"x")

    def test_close_before_connect(self):
        c = self.client(connect=False)
        c.close()
        self.assertEqual(self.closes, [])

    def test_broker_drop_reports_once(self):
        c = self.client()
        self.fake.drop_clients()
        self.assertTrue(wait_for(lambda: self.closes))
        c.close()
        time.sleep(0.1)
        self.assertEqual(len(self.closes), 1)
        self.assertNotEqual(self.closes[0], "closed")

    def test_close_from_callback(self):
        c = self.client()
        c.on_message = lambda t, p: c.close()
        self.fake.publish_raw("anycubic/x", b"1")
        self.assertTrue(wait_for(lambda: self.closes == ["closed"]))


@unittest.skipUnless(shutil.which("openssl"), "openssl CLI needed to generate throwaway certificates")
class TlsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tls = make_tls_files(self.tmp)
        self.fake = FakeKobra(tls=self.tls).start()
        self.addCleanup(self.fake.stop)

    def ctx(self, with_cert):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        if with_cert:
            ctx.load_cert_chain(self.tls.client_cert, self.tls.client_key)
        return ctx

    def test_mutual_tls(self):
        got = []
        c = mqtt.Client(self.fake.host, self.fake.mqtt_port, "k", username=self.fake.username,
                        password=self.fake.password, ssl_context=self.ctx(True), timeout=3,
                        on_message=lambda t, p: got.append(p))
        self.addCleanup(c.close)
        c.connect()
        c.subscribe("#")
        self.fake.publish_raw("x", b"y" * 70000)
        c.publish("up", b"z" * 70000)
        self.assertTrue(wait_for(lambda: got and self.fake.requests))
        self.assertEqual(len(got[0]), 70000)
        self.assertEqual(len(self.fake.requests[0]["raw"]), 70000)

    def test_missing_client_cert_fails(self):
        c = mqtt.Client(self.fake.host, self.fake.mqtt_port, "k", username=self.fake.username,
                        password=self.fake.password, ssl_context=self.ctx(False), timeout=2)
        with self.assertRaises(mqtt.MqttError):
            c.connect()


if __name__ == "__main__":
    unittest.main()
