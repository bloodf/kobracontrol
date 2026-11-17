"""The Kobra Control tab's camera: ffmpeg turns the printer's RTSP (or HTTP-FLV) stream into MJPEG on its
stdout, split here into JPEG frames. Free of the `orca` module. Ported in spirit from Kobralink's
camera.ts and KX-Bridge's camera.py (both GPL-3.0): the same low-latency input flags, restart with
backoff, and a restart when the printer rotates the stream token (`State.view()["camera_url_rev"]`).

    cam = Camera(get_url, on_frame, ffmpeg_path, on_error)
    cam.start()   # while the tab wants the camera; call again to renew (it stops itself after idle_s)
    cam.ack()     # the page showed the last frame; only then is the next one handed over
    cam.stop() / cam.close()

on_frame(jpeg_bytes) gets the LATEST frame, at most MAX_FPS per second, never before the previous one was
acknowledged (ACK_TIMEOUT s later it goes on anyway, a lost ack must not freeze the picture).
on_error(reason, text): reason is "no_ffmpeg", "no_stream" or "failed" (ffmpeg ended without a frame; text
is the last line of its stderr). Called again only when the reason or text changes. "no_ffmpeg" ends the reader:
it is reported once, not looked up again every second (the service marks ffmpeg missing and stops asking).

Relay is the default without ffmpeg: it reads the printer's HTTP-FLV itself and hands fragmented MP4 to the
page's own player (fmp4.py). Same start/stop/close; on_video({"codec", "init"}) then on_video({"data"}); its
on_error adds "unsupported" (the stream is not FLV/H.264: use ffmpeg instead).
"""

import http.client
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse

import fmp4
from i18n import tr

MAX_FPS = 5.0
ACK_TIMEOUT = 5.0
EXTRA_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")   # a GUI app's PATH often lacks Homebrew
MAX_FRAME = 4 * 1024 * 1024
SOI, EOI = b"\xff\xd8", b"\xff\xd9"
POLL = 0.1


def argv(url, ffmpeg="ffmpeg"):
    """The exact command line (a list, never a shell string; OrcaSlicer matches it verbatim)."""
    if not isinstance(url, str) or not url.lower().startswith(("rtsp://", "http://", "https://")) \
            or "://" in url and not url.split("://", 1)[1]:
        raise ValueError(tr("not a camera stream URL"))
    base = ["-fflags", "nobuffer", "-flags", "low_delay", "-timeout", "10000000"]
    if url.lower().startswith("rtsp://"):
        base += ["-probesize", "32", "-analyzeduration", "0", "-rtsp_transport", "tcp"]
    else:
        base += ["-use_wallclock_as_timestamps", "1", "-probesize", "500000", "-analyzeduration", "500000"]
    return [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "warning", *base, "-i", url, "-an",
            "-vf", "fps=10,scale=640:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5",
            "-flush_packets", "1", "pipe:1"]


def find_ffmpeg(setting=""):
    """The ffmpeg to run: the settings path, else PATH, else the usual install folders; None when none works."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [setting] if setting else []
    candidates.append(shutil.which("ffmpeg"))
    candidates += [os.path.join(d, name) for d in EXTRA_DIRS]
    return next((c for c in candidates if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


class FrameSplitter:
    """Cuts a byte stream into JPEGs at SOI/EOI markers; bytes before the first SOI are dropped."""

    def __init__(self, limit=MAX_FRAME):
        self.buf, self.limit = b"", limit

    def feed(self, chunk):
        self.buf += chunk
        frames = []
        while True:
            start = self.buf.find(SOI)
            if start < 0:
                self.buf = self.buf[-1:] if self.buf.endswith(SOI[:1]) else b""
                return frames
            end = self.buf.find(EOI, start + 2)
            if end < 0:
                self.buf = self.buf[start:] if len(self.buf) - start <= self.limit else b""
                return frames
            frames.append(self.buf[start:end + 2])
            self.buf = self.buf[end + 2:]


class Camera:
    def __init__(self, get_url, on_frame, ffmpeg_path="", on_error=None, popen=subprocess.Popen,
                 backoff=(2.0, 60.0), idle_s=15.0, log=print, clock=time.monotonic):
        self.get_url, self.on_frame, self.on_error = get_url, on_frame, on_error
        self.ffmpeg_path, self.popen, self.backoff, self.idle_s = ffmpeg_path, popen, backoff, idle_s
        self.log, self.clock = log, clock
        self._lock = threading.Lock()          # start / stop
        self._cond = threading.Condition()     # latest frame, ack state
        self._stop = threading.Event()
        self._threads = []
        self._proc = None
        self._closed = False
        self._touched = 0.0
        self._latest = None
        self._awaiting, self._sent_at = False, 0.0
        self._last_error = None

    def set_ffmpeg(self, path):
        self.ffmpeg_path = path or ""

    # ---- called by the service ----------------------------------------------------------------
    def start(self):
        with self._lock:
            if self._closed:
                return
            self._touched = self.clock()
            if self._threads and not self._stop.is_set() and all(t.is_alive() for t in self._threads):
                return
            self._join()
            self._stop = threading.Event()
            self._last_error = None
            self._threads = [threading.Thread(target=f, name="kobracontrol-camera-" + n, daemon=True)
                             for n, f in (("run", self._run), ("send", self._send))]
            for t in self._threads:
                t.start()

    def ack(self):
        with self._cond:
            self._awaiting = False
            self._cond.notify_all()
        self._touched = self.clock()

    def stop(self):
        with self._lock:
            self._join()

    def close(self):
        with self._lock:
            self._closed = True
            self._join()

    def _join(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(5)
        self._threads = []
        self._kill(self._proc)
        with self._cond:
            self._latest, self._awaiting = None, False

    # ---- worker threads -----------------------------------------------------------------------
    def _fail(self, reason, text=""):
        if (reason, text) != self._last_error:
            self._last_error = (reason, text)
            if self.on_error:
                try:
                    self.on_error(reason, text)
                except Exception as e:  # a broken callback must not kill the camera
                    self.log("kobracontrol camera: on_error raised %r" % (e,))

    @staticmethod
    def _kill(proc):
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(5)
        except (subprocess.TimeoutExpired, OSError):
            pass

    def _run(self):
        stop, fails = self._stop, 0
        try:
            while not stop.is_set():
                if self.clock() - self._touched > self.idle_s:
                    return
                exe = find_ffmpeg(self.ffmpeg_path)
                if exe is None:
                    self._fail("no_ffmpeg", tr("ffmpeg was not found"))
                    return
                url = self.get_url()
                try:
                    cmd = argv(url, exe)
                except ValueError:
                    self._fail("no_stream", tr("the printer has not announced a camera stream"))
                    stop.wait(0.5)
                    continue
                got, text, changed = self._session(cmd, url, stop)
                if stop.is_set():
                    return
                if got:
                    fails = 0
                if changed:
                    fails = 0
                    continue
                self._fail("failed", text or tr("ffmpeg ended"))
                fails += 1
                stop.wait(min(self.backoff[0] * 2 ** (fails - 1), self.backoff[1]))
        finally:
            stop.set()
            with self._cond:
                self._cond.notify_all()

    def _session(self, cmd, url, stop):
        """Run one ffmpeg until it ends, the URL changes or we stop. (got_frame, last stderr line, url_changed)"""
        try:
            proc = self.popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return False, str(e), False
        self._proc = proc
        with self._cond:
            self._latest = None
        tail, got = [""], [False]

        def drain():
            for line in iter(proc.stderr.readline, b""):
                tail[0] = line.decode("utf-8", "replace").strip() or tail[0]

        def read():
            splitter = FrameSplitter()
            while True:
                chunk = proc.stdout.read1(65536)
                if not chunk:
                    return
                for frame in splitter.feed(chunk)[-1:]:   # only the newest of a burst matters
                    got[0] = True
                    with self._cond:
                        self._latest = frame
                        self._cond.notify_all()

        workers = [threading.Thread(target=f, daemon=True, name="kobracontrol-camera-io") for f in (drain, read)]
        for w in workers:
            w.start()
        changed = False
        while not stop.is_set() and proc.poll() is None:
            if self.clock() - self._touched > self.idle_s:
                stop.set()
            elif self.get_url() != url:
                changed = True
                break
            stop.wait(POLL)
        self._kill(proc)
        for w in workers:
            w.join(2)
        for pipe in (proc.stdout, proc.stderr):   # after the readers ended: a closed pipe under a reader would raise
            try:
                pipe.close()
            except (OSError, ValueError):
                pass
        self._proc = None
        if got[0]:
            self._last_error = None
        return got[0], tail[0], changed

    def _send(self):
        stop = self._stop
        while not stop.is_set():
            with self._cond:
                now = self.clock()
                due = self._sent_at + 1.0 / MAX_FPS
                held = self._awaiting and now - self._sent_at < ACK_TIMEOUT
                if self._latest is None or held or now < due:
                    wait = POLL if self._latest is None or held else due - now
                    self._cond.wait(min(wait, POLL))
                    continue
                frame, self._latest = self._latest, None
                self._awaiting, self._sent_at = True, now
            try:
                self.on_frame(frame)
            except Exception as e:
                self.log("kobracontrol camera: on_frame raised %r" % (e,))


STALL_S = 10.0   # no bytes for this long: the stream is dead, reconnect
RECONNECT_S = 0.5


class Relay(Camera):
    """The printer's HTTP-FLV stream remuxed to fragmented MP4 for the page's player: no ffmpeg involved.
    Reconnects when the stream drops, starts over when the printer rotates the stream token (a new URL), and
    sends nothing before the first keyframe."""

    def __init__(self, get_url, on_video, on_error=None, connect=http.client.HTTPConnection, backoff=(2.0, 60.0),
                 idle_s=15.0, log=print, clock=time.monotonic):
        super().__init__(get_url, on_video, "", on_error, backoff=backoff, idle_s=idle_s, log=log, clock=clock)
        self.connect = connect

    def _send(self):   # Camera's frame pacing is not needed: every fragment goes out, the decoder needs them all
        self._stop.wait()

    def _run(self):
        stop, fails = self._stop, 0
        try:
            while not stop.is_set():
                if self.clock() - self._touched > self.idle_s:
                    return
                url = self.get_url()
                if not isinstance(url, str) or not url.lower().startswith("http://") or not url[7:]:
                    self._fail("no_stream", tr("the printer has not announced a camera stream"))
                    stop.wait(0.5)
                    continue
                got, reason, text, changed = self._session(url, stop)
                if stop.is_set():
                    return
                if got or changed:   # it played: reconnect at once, the page keeps its last picture meanwhile
                    fails = 0
                    stop.wait(0 if changed else RECONNECT_S)
                    continue
                self._fail(reason, text or tr("the camera stream ended"))
                fails += 1
                stop.wait(min(self.backoff[0] * 2 ** (fails - 1), self.backoff[1]))
        finally:
            stop.set()

    def _session(self, url, stop):
        """Read one connection until it ends, the URL changes or we stop. (got, reason, error text, url_changed)"""
        parts = urllib.parse.urlsplit(url)
        done = threading.Event()
        box = {"sock": None, "got": False, "reason": "failed", "error": ""}

        def pump():
            conn = None
            try:
                conn = self.connect(parts.hostname, parts.port or 80, timeout=STALL_S)
                conn.connect()
                box["sock"] = conn.sock
                if done.is_set():
                    return
                conn.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""))
                resp = conn.getresponse()
                if resp.status not in (200, 206):
                    raise fmp4.FlvError("HTTP %d" % resp.status)
                remux = fmp4.Remuxer()
                while not done.is_set():
                    chunk = resp.read1(65536)
                    if not chunk:
                        return
                    for event in remux.feed(chunk):
                        if done.is_set():
                            return
                        if not box["got"]:
                            box["got"], self._last_error = True, None
                        self._emit(event)
            except fmp4.Unsupported as e:
                box.update(reason="unsupported", error=str(e))
            except (OSError, http.client.HTTPException, fmp4.FlvError) as e:
                box["error"] = str(e) or type(e).__name__
            finally:
                if conn is not None:
                    conn.close()

        worker = threading.Thread(target=pump, daemon=True, name="kobracontrol-camera-relay")
        worker.start()
        changed = False
        while not stop.is_set() and worker.is_alive():
            if self.clock() - self._touched > self.idle_s:
                stop.set()
            elif self.get_url() != url:
                changed = True
                break
            stop.wait(POLL)
        done.set()
        if box["sock"] is not None:
            try:
                box["sock"].shutdown(socket.SHUT_RDWR)   # unblocks a read waiting on a silent printer
            except OSError:
                pass
        worker.join(2)
        return box["got"], box["reason"], box["error"], changed

    def _emit(self, event):
        message = {"codec": event[1], "init": event[2]} if event[0] == "init" else {"data": event[1]}
        try:
            self.on_frame(message)
        except Exception as e:
            self.log("kobracontrol camera: on_video raised %r" % (e,))
