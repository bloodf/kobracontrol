"""The built-in camera player's feed: fmp4.py (FLV to fragmented MP4) against a real Kobra X capture
(tests/kobra_x_camera.flv: 3.5 s, H.264 High 1280x720, 10 fps, a keyframe a second), and camera.Relay reading it
over HTTP. Playback of the same output in a browser is ui/tests/page/run.mjs ("the page plays the printer stream")."""
import http.server
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import socket
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import camera  # noqa: E402
import fmp4  # noqa: E402

with open(os.path.join(ROOT, "tests", "kobra_x_camera.flv"), "rb") as _f:
    SAMPLE = _f.read()


def tags(data):
    """(offset, tag bytes incl. PreviousTagSize) of each FLV tag after the 13-byte header."""
    out, off = [], 13
    while off + 11 <= len(data):
        size = int.from_bytes(data[off + 1:off + 4], "big")
        out.append(data[off:off + 11 + size + 4])
        off += 11 + size + 4
    return out


def boxes(data):
    out, off = [], 0
    while off < len(data):
        size = struct.unpack(">I", data[off:off + 4])[0]
        out.append((data[off + 4:off + 8], data[off + 8:off + size]))
        off += size
    return out


def find(data, path):
    for kind, body in boxes(data):
        if kind == path[0]:
            return body if len(path) == 1 else find(body, path[1:])
    return None


def sample_info(segment):
    """(tfdt, data_offset, sample flags, mdat payload) of a one-sample media segment."""
    traf = find(segment, [b"moof", b"traf"])
    tfdt = struct.unpack(">Q", find(traf, [b"tfdt"])[4:12])[0]
    trun = find(traf, [b"trun"])
    count, offset = struct.unpack(">Ii", trun[4:12])
    flags = struct.unpack(">I", trun[20:24])[0]
    return count, tfdt, offset, flags


def wait(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = pred()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


class Remux(unittest.TestCase):
    def setUp(self):
        self.events = fmp4.Remuxer().feed(SAMPLE)

    def test_init_then_one_fragment_per_frame(self):
        kinds = [e[0] for e in self.events]
        self.assertEqual(kinds[0], "init")
        self.assertEqual(kinds[1:], ["media"] * 35)   # 36 frames; the last waits for the next one's timestamp
        self.assertEqual(self.events[0][1], "avc1.64c028")
        self.assertEqual(find(self.events[0][2], [b"moov", b"trak", b"tkhd"])[-8:],
                         struct.pack(">II", 1280 << 16, 720 << 16))

    def test_fragments_are_keyed_timed_and_point_at_their_data(self):
        last = -1
        for n, (_, seg, _) in enumerate(self.events[1:]):
            count, tfdt, offset, flags = sample_info(seg)
            self.assertEqual(count, 1)
            self.assertGreater(tfdt, last)
            last = tfdt
            moof_len = struct.unpack(">I", seg[:4])[0]
            self.assertEqual(offset, moof_len + 8)   # right after the mdat header
            self.assertEqual(seg[moof_len + 4:moof_len + 8], b"mdat")
            self.assertEqual(flags == fmp4.SYNC, n % 10 == 0, n)   # a keyframe every 10 frames
        self.assertEqual(sample_info(self.events[1][1])[1], 0)

    def test_chunking_does_not_matter(self):
        rnd, remux, got, i = random.Random(7), fmp4.Remuxer(), [], 0
        while i < len(SAMPLE):
            n = rnd.randint(1, 3000)
            got += remux.feed(SAMPLE[i:i + n])
            i += n
        self.assertEqual(got, self.events)

    def test_waits_for_a_keyframe(self):
        t = tags(SAMPLE)
        no_first_key = SAMPLE[:13] + t[0] + b"".join(t[2:])   # sequence header, then delta frames first
        events = fmp4.Remuxer().feed(no_first_key)
        self.assertEqual(sample_info(events[1][1])[3], fmp4.SYNC)
        self.assertEqual(sample_info(events[1][1])[1], 0)
        self.assertEqual(len(events), 1 + 35 - 10)

    def test_a_new_sequence_header_starts_a_new_stream(self):
        t = tags(SAMPLE)
        header = bytearray(t[0])
        header[11 + 5 + 3] ^= 1   # another level: a different configuration
        events = fmp4.Remuxer().feed(SAMPLE + bytes(header) + b"".join(t[1:12]))
        inits = [n for n, e in enumerate(events) if e[0] == "init"]
        self.assertEqual(len(inits), 2)
        self.assertEqual(sample_info(events[inits[1] + 1][1])[1], 0)

    def test_keyframe_flag_rides_with_each_fragment(self):
        self.assertEqual([e[2] for e in self.events[1:]], [n % 10 == 0 for n in range(35)])

    def test_a_clock_jump_never_overlaps_samples(self):
        t = tags(SAMPLE)
        def stamp(tag, ms):
            tag = bytearray(tag)
            tag[4:7], tag[7] = (ms & 0xFFFFFF).to_bytes(3, "big"), ms >> 24 & 0xFF
            return bytes(tag)
        # frames 1-10 at 100 ms steps, then the printer's clock goes back 5 s, then forward 1 h
        frames = [stamp(tag, 5000 + 100 * n) for n, tag in enumerate(t[1:11])]
        frames += [stamp(tag, 100 * n) for n, tag in enumerate(t[11:21])]
        frames += [stamp(tag, 3600000 + 100 * n) for n, tag in enumerate(t[21:31])]
        events = fmp4.Remuxer().feed(SAMPLE[:13] + t[0] + b"".join(frames))
        end = 0
        for _, seg, _ in events[1:]:
            _, tfdt, _, _ = sample_info(seg)
            duration = struct.unpack(">I", find(seg, [b"moof", b"traf", b"trun"])[12:16])[0]
            self.assertGreaterEqual(tfdt, end)   # each sample starts where the last one ended, or later
            self.assertGreater(duration, 0)
            end = tfdt + duration

    def test_bad_header_offset_is_refused(self):
        for offset in (0, 8, 1025, 0xFFFFFFFF):
            with self.subTest(offset=offset), self.assertRaises(fmp4.FlvError):
                fmp4.Remuxer().feed(SAMPLE[:5] + struct.pack(">I", offset) + SAMPLE[9:])

    def test_a_tag_too_large_is_refused(self):
        huge = bytes([9]) + (fmp4.MAX_TAG + 1).to_bytes(3, "big") + bytes(7)
        with self.assertRaises(fmp4.FlvError):
            fmp4.Remuxer().feed(SAMPLE[:13] + huge)

    def test_garbage_after_the_header_is_refused_or_ignored(self):
        rnd = random.Random(3)
        for _ in range(50):
            junk = bytes(rnd.randrange(256) for _ in range(4000))
            try:
                events = fmp4.Remuxer().feed(SAMPLE[:13] + junk)
            except fmp4.FlvError:
                continue
            self.assertEqual([e for e in events if e[0] == "media"], [])   # nothing playable invented

    def test_video_info_tags_are_not_pictures(self):
        t = tags(SAMPLE)
        info = bytearray(t[3])
        info[11] = 0x57   # frame type 5 (video info/command), AVC
        events = fmp4.Remuxer().feed(SAMPLE[:13] + b"".join(t[:3]) + bytes(info) + b"".join(t[3:]))
        self.assertEqual(len(events), len(self.events))

    def test_an_impossible_picture_size_is_refused(self):
        with mock.patch.object(fmp4, "sps_size", return_value=(70000, 720)), self.assertRaises(fmp4.FlvError):
            fmp4.Remuxer().feed(SAMPLE)

    def test_not_flv_or_not_h264_is_unsupported(self):
        with self.assertRaises(fmp4.Unsupported):
            fmp4.Remuxer().feed(b"\x00\x00\x00\x18ftypisom" + bytes(16))
        hevc = bytearray(tags(SAMPLE)[0])
        hevc[11] = 0x1C
        with self.assertRaises(fmp4.Unsupported):
            fmp4.Remuxer().feed(SAMPLE[:13] + bytes(hevc))

    def test_sps_size(self):
        remux = fmp4.Remuxer()
        remux.feed(SAMPLE)
        sps_len = struct.unpack(">H", remux.avcc[6:8])[0]
        self.assertEqual(fmp4.sps_size(remux.avcc[8:8 + sps_len]), (1280, 720))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_ffmpeg_decodes_every_frame(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(self.events[0][2] + b"".join(e[1] for e in self.events[1:]))
        self.addCleanup(os.unlink, f.name)
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", f.name, "-f", "null", "-"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, ""))


class Stream(http.server.BaseHTTPRequestHandler):
    """/live/<token>: the sample, paced; /drop: half of it, then the connection closes; /other: not FLV."""
    hits = []

    def do_GET(self):
        Stream.hits.append(self.path)
        body = b"<html>no</html>" if self.path == "/other" else SAMPLE[:len(SAMPLE) // 2] if self.path == "/drop" else SAMPLE
        self.send_response(200)
        self.send_header("Content-Type", "video/x-flv")
        self.end_headers()
        try:
            for i in range(0, len(body), 8192):
                self.wfile.write(body[i:i + 8192])
                self.wfile.flush()
                time.sleep(0.01)
            if self.path.startswith("/live/"):
                time.sleep(30)   # a live stream does not end
        except OSError:
            pass

    def log_message(self, *a):
        pass


REAL_HEADERS = (b"HTTP/1.1 206 Partial Content\r\nContent-Type: video/x-flv\r\nConnection: keep-alive\r\n"
                b'ETag: "66bdbc2b-b7965"\r\nAccess-Control-Allow-Origin: *\r\n'
                b"Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
                b"Access-Control-Allow-Headers: Content-Length, Content-Type\r\n"
                b"Access-Control-Expose-Headers:: Content-Length\r\n\r\n")   # a Kobra X's answer, byte for byte


class RawServer:
    """One-shot socket server: mode "real" (the printer's headers, no length, close-delimited), "chunked", "hang"."""

    def __init__(self, mode):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.mode, self.port = mode, self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        try:
            conn.recv(4096)
            if self.mode == "hang":
                time.sleep(30)
                return
            if self.mode == "chunked":
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: video/x-flv\r\nTransfer-Encoding: chunked\r\n\r\n")
                for i in range(0, len(SAMPLE), 5000):
                    piece = SAMPLE[i:i + 5000]
                    conn.sendall(b"%x\r\n" % len(piece) + piece + b"\r\n")
                    time.sleep(0.005)
            else:
                conn.sendall(REAL_HEADERS)
                for i in range(0, len(SAMPLE), 5000):
                    conn.sendall(SAMPLE[i:i + 5000])
                    time.sleep(0.005)
            time.sleep(30)   # live: never ends
        except OSError:
            pass
        finally:
            conn.close()

    def close(self):
        self.sock.close()


class RawRelay(unittest.TestCase):
    def relay(self, mode):
        server = RawServer(mode)
        self.addCleanup(server.close)
        parts, errors, box = [], [], []

        def on_video(part):   # a page that keeps up
            parts.append(part)
            if "data" in part:
                box[0].ack()
        relay = camera.Relay(lambda: "http://127.0.0.1:%d/live/x" % server.port, on_video,
                             lambda r, t: errors.append(r), log=lambda *a: None)
        box.append(relay)
        self.addCleanup(relay.close)
        return relay, parts, errors

    def test_the_printers_own_response_headers(self):
        relay, parts, errors = self.relay("real")
        relay.start()
        wait(lambda: len(parts) == 36)   # every frame of the recording but the last (it waits for a successor)
        self.assertEqual(parts[0]["codec"], "avc1.64c028")
        self.assertEqual(errors, [])

    def test_chunked_transfer_encoding(self):
        relay, parts, errors = self.relay("chunked")
        relay.start()
        wait(lambda: len(parts) >= 20)
        self.assertEqual(parts[0]["codec"], "avc1.64c028")
        self.assertTrue(all(len(p["data"]) > 100 for p in parts[1:20]))   # chunk framing never leaks into data
        self.assertEqual(errors, [])

    def test_stop_and_close_return_at_once_on_a_silent_printer(self):
        relay, parts, errors = self.relay("hang")
        relay.start()
        time.sleep(0.3)   # connected, waiting for an answer that never comes
        began = time.monotonic()
        relay.stop()
        relay.start()
        relay.close()
        self.assertLess(time.monotonic() - began, 0.1)


class RelayTests(unittest.TestCase):
    def setUp(self):
        Stream.hits = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stream)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:%d/live/a" % self.server.server_port
        self.parts, self.errors = [], []
        self.auto_ack = True   # a page that keeps up

        def on_video(part):
            self.parts.append(part)
            if self.auto_ack and "data" in part:
                self.relay.ack()
        self.relay = camera.Relay(lambda: self.url, on_video, lambda r, t: self.errors.append((r, t)),
                                  backoff=(0.1, 0.2), log=lambda *a: None)
        self.addCleanup(self.relay.close)

    def inits(self):
        return [p for p in self.parts if "init" in p]

    def test_init_then_fragments(self):
        self.relay.start()
        wait(lambda: len(self.parts) >= 36)
        self.assertEqual(self.parts[0]["codec"], "avc1.64c028")
        self.assertTrue(self.parts[0]["init"].startswith(b"\x00\x00\x00\x20ftypisom"))
        self.assertTrue(all("data" in p for p in self.parts[1:]))
        self.assertEqual(self.errors, [])

    def test_a_new_token_starts_over_on_the_new_url(self):
        self.relay.start()
        wait(lambda: self.parts)
        self.url = self.url.replace("/live/a", "/live/b")
        wait(lambda: len(self.inits()) == 2)
        self.assertEqual(Stream.hits, ["/live/a", "/live/b"])

    def test_reconnects_when_the_stream_drops(self):
        self.url = self.url.replace("/live/a", "/drop")
        self.relay.start()
        wait(lambda: len(self.inits()) >= 2)
        self.assertEqual(self.errors, [])   # it played: a quiet reconnect, no error on the page
        self.assertEqual(self.parts[1]["key"], True)

    def test_not_flv_is_unsupported(self):
        self.url = self.url.replace("/live/a", "/other")
        self.relay.start()
        wait(lambda: self.errors)
        self.assertEqual(self.errors[0][0], "unsupported")
        self.assertEqual(self.parts, [])

    def test_no_stream_until_the_printer_announces_one(self):
        self.url = ""
        self.relay.start()
        wait(lambda: self.errors)
        self.assertEqual(self.errors[0][0], "no_stream")

    def test_a_player_that_attaches_late_gets_the_init_again(self):
        self.relay.start()
        wait(lambda: len(self.parts) > 5)
        self.assertEqual(self.parts[1]["key"], True)
        self.relay.resend_init()
        wait(lambda: len(self.inits()) == 2)
        self.assertEqual(self.inits()[0], self.inits()[1])
        self.relay.stop()
        count = len(self.parts)
        self.relay.resend_init()   # stopped: nothing to resend
        self.assertEqual(len(self.parts), count)

    def test_a_page_that_does_not_ack_gets_keyframes_only_after_a_backlog(self):
        self.auto_ack = False
        self.relay.start()
        wait(lambda: len(self.parts) >= 1 + camera.MAX_UNACKED)
        time.sleep(0.5)
        self.assertEqual(len(self.parts), 1 + camera.MAX_UNACKED)   # held at the cap: the rest dropped
        for _ in range(camera.MAX_UNACKED):
            self.relay.ack()
        self.url = self.url.replace("/live/a", "/live/c")   # more frames: resumes, at a keyframe
        wait(lambda: len(self.inits()) == 2 and self.parts[-1] is not self.inits()[1])

    def test_a_stream_that_drops_at_once_backs_off_without_an_error(self):
        self.url = self.url.replace("/live/a", "/drop")
        self.relay.backoff = (0.5, 0.5)
        self.relay.start()
        wait(lambda: len(self.inits()) >= 2)
        time.sleep(1.0)
        self.assertLessEqual(len(self.inits()), 4)   # about one reconnect per 0.5 s backoff, not a loop
        self.assertEqual(self.errors, [])

    def test_stop_ends_the_connection(self):
        self.relay.start()
        wait(lambda: self.parts)
        self.relay.stop()
        count = len(self.parts)
        time.sleep(0.3)
        self.assertEqual(len(self.parts), count)


if __name__ == "__main__":
    unittest.main()
