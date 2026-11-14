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
is the last line of its stderr). Called again only when the reason or text changes.
"""

import os
import shutil
import subprocess
import threading
import time

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
        raise ValueError("not a camera stream URL")
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
                    self._fail("no_ffmpeg", "ffmpeg was not found")
                    stop.wait(1.0)
                    continue
                url = self.get_url()
                try:
                    cmd = argv(url, exe)
                except ValueError:
                    self._fail("no_stream", "the printer has not announced a camera stream")
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
                self._fail("failed", text or "ffmpeg ended")
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
