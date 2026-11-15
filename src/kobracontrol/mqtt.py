"""Minimal MQTT 3.1.1 client (QoS 0, clean session) over a plain or TLS socket, standard library only.

One daemon reader thread per connection delivers `on_message(topic, payload_bytes)` and, exactly once
when the connection ends, `on_close(reason)` ("closed" after `close()`). Callback exceptions are logged
and swallowed. `publish` is thread-safe. No reconnection: the owner decides when to build a new Client;
`connected` turns False as soon as a read, a write or the keepalive fails, and `last_rx` tells how long
the printer has been silent.

Socket handling (TCP keepalive + TCP_USER_TIMEOUT, tolerated empty TLS reads, one lock around every
socket read/write) is ported from KX-Bridge's kobrax_client.py; packet framing and request semantics
follow Kobralink's mqtt.js usage.
"""

import logging
import select
import socket
import threading
import time

log = logging.getLogger(__name__)

CONNECT, CONNACK, PUBLISH, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT = 1, 2, 3, 8, 9, 12, 13, 14
MAX_LENGTH = 268435455
MAX_PACKET = 4 * 1024 * 1024  # printer packets are a few KB; refuse more before buffering it
POLL = 0.25
EMPTY_READS_EOF = 5  # KX-Bridge: Windows TLS sockets can return b"" briefly without a real EOF


class MqttError(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class MqttAuthError(MqttError):
    """CONNACK 4 (bad user name or password) or 5 (not authorised)."""


def encode_length(n):
    if not 0 <= n <= MAX_LENGTH:
        raise ValueError("remaining length out of range")
    out = bytearray()
    while True:
        n, digit = divmod(n, 128)
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out)


def decode_length(buf, start):
    """(value, index after the varint), or None while incomplete."""
    value, mult = 0, 1
    for i in range(4):
        if start + i >= len(buf):
            return None
        b = buf[start + i]
        value += (b & 0x7F) * mult
        if not b & 0x80:
            return value, start + i + 1
        mult *= 128
    raise MqttError("protocol error: malformed remaining length")


def packet(head, body):
    return bytes([head]) + encode_length(len(body)) + body


def split_packets(buf):
    """Remove every complete packet from the bytearray `buf`; return [(type, flags, body)]."""
    out = []
    while len(buf) >= 2:
        decoded = decode_length(buf, 1)
        if decoded is None:
            break
        n, start = decoded
        if n > MAX_PACKET:
            raise MqttError("protocol error: packet too large (%d bytes)" % n)
        if len(buf) < start + n:
            break
        out.append((buf[0] >> 4, buf[0] & 0x0F, bytes(buf[start:start + n])))
        del buf[:start + n]
    return out


def parse_publish(flags, body):
    n = int.from_bytes(body[:2], "big")
    start = 2 + n + (2 if (flags >> 1) & 3 else 0)  # QoS > 0 carries a packet id
    return body[2:2 + n].decode("utf-8", "replace"), body[start:]


def enable_tcp_keepalive(sock):
    """Best effort. A printer that is unplugged never closes its TCP side; without short keepalive
    probes and TCP_USER_TIMEOUT (unacknowledged data in flight, Linux) the OS keeps the dead socket
    alive for 15+ minutes (KX-Bridge, verified by unplugging a real printer)."""
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    idle = getattr(socket, "TCP_KEEPIDLE", getattr(socket, "TCP_KEEPALIVE", None))  # TCP_KEEPALIVE: macOS
    for opt, value in ((idle, 5), (getattr(socket, "TCP_KEEPINTVL", None), 3),
                       (getattr(socket, "TCP_KEEPCNT", None), 3), (getattr(socket, "TCP_USER_TIMEOUT", None), 15000)):
        if opt is not None:
            options.append((socket.IPPROTO_TCP, opt, value))
    for level, opt, value in options:
        try:
            sock.setsockopt(level, opt, value)
        except OSError as e:
            log.debug("socket option %s not supported: %s", opt, e)


def _s(value):
    raw = value.encode("utf-8") if isinstance(value, str) else value
    if len(raw) > 0xFFFF:
        raise MqttError("MQTT string too long (%d bytes)" % len(raw))
    return len(raw).to_bytes(2, "big") + raw


class Client:
    def __init__(self, host, port, client_id, username=None, password=None, ssl_context=None,
                 keepalive=60, timeout=10, on_message=None, on_close=None):
        self.host, self.port, self.client_id = host, port, client_id
        self.username, self._password, self.ssl_context = username, password, ssl_context
        self.keepalive, self.timeout = keepalive, timeout
        self.on_message, self.on_close = on_message, on_close
        self._sock = self._thread = None
        self._buf = bytearray()
        self._io = threading.Lock()       # serialises every socket read/write (TLS objects are not thread-safe)
        self._state = threading.Lock()
        self._closing = self._open = False
        self._acks, self._next_id = {}, 0
        self._last_in = self._last_out = 0.0
        self._empty_reads = 0
        self.peer_cert = None             # the server's certificate (DER) of a TLS session, else None

    def __repr__(self):
        return "<mqtt.Client %s:%s id=%s>" % (self.host, self.port, self.client_id)

    @property
    def connected(self):
        return self._open and not self._closing

    @property
    def last_rx(self):
        """time.monotonic() of the last bytes received (0.0 before connect)."""
        return self._last_in

    # connection ---------------------------------------------------------------------------
    def connect(self):
        if self._closing:
            raise MqttError("client is closed")
        try:
            raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise MqttError("cannot reach %s:%s (%s)" % (self.host, self.port, e)) from None
        enable_tcp_keepalive(raw)
        try:
            sock = self.ssl_context.wrap_socket(raw) if self.ssl_context else raw
            self._sock = sock
            sock.sendall(self._connect_packet())
            self._await_connack(sock)
            self.peer_cert = sock.getpeercert(binary_form=True) if self.ssl_context else None
        except BaseException as e:
            for s in {raw, self._sock} - {None}:
                s.close()
            self._sock = None
            if isinstance(e, MqttError):
                raise
            if isinstance(e, OSError):
                raise MqttError("MQTT handshake with %s:%s failed (%s)" % (self.host, self.port, e)) from None
            raise
        # Short read timeout from now on: the reader holds the I/O lock across recv, and a TLS record that
        # stalls half-way would otherwise block every publish for the full timeout (KX-Bridge uses 0.2 s).
        sock.settimeout(POLL)
        self._last_in = self._last_out = time.monotonic()
        self._open = True
        self._thread = threading.Thread(target=self._run, name="kobracontrol-mqtt", daemon=True)
        self._thread.start()

    def _connect_packet(self):
        flags = 0x02 | (0x80 if self.username is not None else 0) | (0x40 if self._password is not None else 0)
        body = _s("MQTT") + bytes([4, flags]) + self.keepalive.to_bytes(2, "big") + _s(self.client_id)
        if self.username is not None:
            body += _s(self.username)
        if self._password is not None:
            body += _s(self._password)
        return packet(CONNECT << 4, body)

    def _await_connack(self, sock):
        deadline = time.monotonic() + self.timeout
        while True:
            packets = split_packets(self._buf)
            if packets:
                break
            if time.monotonic() >= deadline:
                raise MqttError("no CONNACK from %s:%s" % (self.host, self.port))
            data = sock.recv(65536)
            if not data:
                raise MqttError("connection closed during the MQTT handshake")
            self._buf += data
        ptype, _, body = packets[0]
        if ptype != CONNACK or len(body) < 2:
            raise MqttError("protocol error: expected CONNACK")
        code = body[1]
        if code in (4, 5):
            raise MqttAuthError("MQTT login refused (code %d): wrong user name or password" % code, code)
        if code:
            raise MqttError("MQTT connection refused (code %d)" % code, code)
        # Anything after CONNACK goes back in front of the buffer for the reader thread.
        self._buf[:0] = b"".join(packet(t << 4 | f, b) for t, f, b in packets[1:])

    def subscribe(self, topic, timeout=None):
        with self._state:
            self._next_id = self._next_id % 65535 + 1
            pid = self._next_id
            waiter = self._acks[pid] = [threading.Event(), None]
        try:
            self._send(packet(SUBSCRIBE << 4 | 2, pid.to_bytes(2, "big") + _s(topic) + b"\x00"))
            if not waiter[0].wait(self.timeout if timeout is None else timeout):
                raise MqttError("no SUBACK for %s" % topic)
        finally:
            self._acks.pop(pid, None)
        if waiter[1] is None or waiter[1] & 0x80:
            raise MqttError("subscription to %s refused" % topic)

    def publish(self, topic, payload):
        data = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        self._send(packet(PUBLISH << 4, _s(topic) + data))

    def close(self):
        with self._state:
            if self._closing:
                return
            self._closing = True
            sock, thread = self._sock, self._thread
        if sock is None or thread is None:
            return
        if self._io.acquire(timeout=1):
            try:
                sock.sendall(packet(DISCONNECT << 4, b""))
            except OSError:
                pass
            finally:
                self._io.release()
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if thread is not threading.current_thread():
            thread.join(2)

    def _send(self, data):
        if not self.connected:
            raise MqttError("not connected")
        try:
            with self._io:
                self._sock.settimeout(self.timeout)  # writes may take the full timeout; reads may not
                try:
                    self._sock.sendall(data)
                finally:
                    self._sock.settimeout(POLL)
                self._last_out = time.monotonic()
        except OSError as e:
            # A failed write means a dead session: report it now instead of waiting for the reader.
            self._open = False
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            raise MqttError("send failed (%s)" % e) from None

    # reader thread ------------------------------------------------------------------------
    def _run(self):
        reason = "closed"
        try:
            while not self._closing:
                self._keepalive()
                data = self._recv()
                if data is None:
                    continue
                if not data:
                    self._empty_reads += 1
                    if self._empty_reads >= EMPTY_READS_EOF:
                        raise MqttError("connection closed by the printer")
                    continue
                self._empty_reads = 0
                self._last_in = time.monotonic()
                self._buf += data
                for item in split_packets(self._buf):
                    self._dispatch(*item)
        except MqttError as e:
            reason = str(e)
        except (OSError, ValueError) as e:
            reason = "connection lost (%s)" % e
        except Exception as e:  # never a silently dead reader: close and tell the owner
            log.exception("MQTT reader failed")
            reason = "reader error (%s)" % e
        finally:
            self._open = False
            try:
                self._sock.close()
            except OSError:
                pass
            for waiter in list(self._acks.values()):
                waiter[0].set()
            self._call(self.on_close, "closed" if self._closing else reason)

    def _keepalive(self):
        now = time.monotonic()
        if now - self._last_in > self.keepalive * 1.5:
            raise MqttError("keepalive timeout: the printer stopped answering")
        if now - self._last_out >= self.keepalive / 2:
            self._send(packet(PINGREQ << 4, b""))

    def _recv(self):
        sock = self._sock
        pending = getattr(sock, "pending", None)  # TLS may hold decrypted bytes select() cannot see
        if not (pending and pending()) and not select.select([sock], [], [], POLL)[0]:
            return None
        try:
            with self._io:
                return sock.recv(65536)
        except TimeoutError:  # a partial TLS record; the rest arrives on a later read
            return None

    def _dispatch(self, ptype, flags, body):
        if ptype == PUBLISH:
            self._call(self.on_message, *parse_publish(flags, body))
        elif ptype == SUBACK and len(body) >= 3:
            waiter = self._acks.get(int.from_bytes(body[:2], "big"))
            if waiter:
                waiter[1] = body[2]
                waiter[0].set()

    def _call(self, callback, *args):
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            log.exception("MQTT callback %r failed", getattr(callback, "__name__", callback))
