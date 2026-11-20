import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src", "kobracontrol")]

import camera  # noqa: E402

# A fake "ffmpeg": reads the URL after -i; ?mode=... picks what it does. Frames are b"\xff\xd8F<n>\xff\xd9"
# written in odd-sized chunks, preceded by garbage, so the splitter has to find the markers.
FAKE = r'''
import os, sys, time
url = sys.argv[sys.argv.index("-i") + 1]
mode = url.split("mode=")[1].split("&")[0] if "mode=" in url else "frames"
with open(os.environ["FAKE_PIDS"], "a") as f:
    f.write("%d %s\n" % (os.getpid(), url))
out = sys.stdout.buffer
def frame(n): return b"\xff\xd8F%d\xff\xd9" % n
def emit(data, step=3):
    for i in range(0, len(data), step):
        out.write(data[i:i + step]); out.flush()
if mode == "die":
    sys.stderr.write("boom: Server returned 404\n"); sys.exit(1)
out.write(b"garbage"); out.flush()
if mode == "burst":
    for n in range(30):
        emit(frame(n)); time.sleep(0.01)
    with open(os.environ["FAKE_PIDS"] + ".done", "w") as f:   # every frame of the burst is written
        f.write("%d\n" % os.getpid())
else:
    n = 0
    while True:
        emit(frame(n)); n += 1; time.sleep(0.02)
time.sleep(60)
'''


def _kernel32():
    """kernel32 with the signatures these tests call. Without argtypes/restype ctypes passes and returns C int,
    and a HANDLE is pointer-sized: GetCurrentProcess's pseudo-handle (-1) comes back as a 64-bit value that
    overflows the int argument (Windows CI: "ctypes.ArgumentError: int too long to convert")."""
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    for name, args, res in (("GetCurrentProcess", [], wintypes.HANDLE),
                            ("GetProcessHandleCount", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
                            ("OpenProcess", [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
                            ("GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
                            ("CloseHandle", [wintypes.HANDLE], wintypes.BOOL)):
        fn = getattr(k, name)
        fn.argtypes, fn.restype = args, res
    return k


def open_handles():
    """This process's open file descriptors (POSIX) or kernel handles (Windows, which has no /dev/fd)."""
    if os.name != "nt":
        return len(os.listdir("/dev/fd"))
    import ctypes
    from ctypes import wintypes
    kernel32, count = _kernel32(), wintypes.DWORD()
    if not kernel32.GetProcessHandleCount(kernel32.GetCurrentProcess(), ctypes.byref(count)):
        raise ctypes.WinError(ctypes.get_last_error())
    return count.value


def process_exists(pid):
    """POSIX: os.kill(pid, 0), where an exited but unreaped child (a zombie) still exists, so a camera that kills
    without wait() is caught. Windows has no zombies and no signal 0: os.kill(pid, 0) there is CTRL_C_EVENT,
    delivered to every process on the console, the test runner included (CI run 43670339285 ended in
    KeyboardInterrupt), and an exited pid raises OSError, not ProcessLookupError. So ask the kernel instead."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    import ctypes
    from ctypes import wintypes
    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False                                     # no such process (any more)
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259                         # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cam-")
        self.script = os.path.join(self.dir, "fake_ffmpeg.py")
        with open(self.script, "w") as f:
            f.write(FAKE)
        self.exe = os.path.join(self.dir, "ffmpeg")
        with open(self.exe, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.exe, os.stat(self.exe).st_mode | stat.S_IXUSR)
        self.pids = os.path.join(self.dir, "pids")
        env = dict(os.environ, FAKE_PIDS=self.pids)
        self.spawned = 0

        def popen(argv, **kw):
            self.spawned += 1
            return subprocess.Popen([sys.executable, self.script, *argv[1:]], env=env, **kw)
        self.popen = popen
        self.frames, self.errors, self.url = [], [], "rtsp://127.0.0.1:1/live?mode=frames"
        self.cams = []

    def tearDown(self):
        for c in self.cams:
            c.close()

    def make(self, **kw):
        opts = dict(get_url=lambda: self.url, on_frame=self.frames.append, ffmpeg_path=self.exe,
                    on_error=lambda reason, text: self.errors.append((reason, text)), popen=self.popen,
                    backoff=(0.05, 0.2), log=lambda m: None)
        cam = camera.Camera(**{**opts, **kw})
        self.cams.append(cam)
        return cam

    def pid_lines(self):
        with open(self.pids) as f:
            return f.read().split("\n")

    def pids_alive(self):
        try:
            lines = self.pid_lines()
        except OSError:
            return []
        return [int(line.split()[0]) for line in lines if line and process_exists(int(line.split()[0]))]


class ArgvTests(unittest.TestCase):
    def test_deterministic_list_without_shell_and_url_after_dash_i(self):
        url = "rtsp://192.168.1.5:554/live?token=abc"
        a = camera.argv(url, "/x/ffmpeg")
        self.assertEqual(a, camera.argv(url, "/x/ffmpeg"))
        self.assertIsInstance(a, list)
        self.assertEqual(a[0], "/x/ffmpeg")
        self.assertEqual(a[a.index("-i") + 1], url)
        self.assertIn("mjpeg", a)
        self.assertEqual(a[-1], "pipe:1")
        self.assertEqual(camera.argv(url)[0], "ffmpeg")
        self.assertTrue(all(isinstance(x, str) for x in a))

    def test_rtsp_uses_tcp_and_http_does_not(self):
        rtsp = camera.argv("rtsp://h/x", "f")
        http = camera.argv("http://h/x.flv", "f")
        self.assertIn("-rtsp_transport", rtsp)
        self.assertNotIn("-rtsp_transport", http)
        self.assertIn("-use_wallclock_as_timestamps", http)
        self.assertIn("nobuffer", rtsp)

    def test_url_must_be_rtsp_or_http(self):
        for bad in ("", "-i evil", "file:///etc/passwd", "ftp://h/x", None, "rtsp://"):
            with self.assertRaises(ValueError, msg=bad):
                camera.argv(bad, "f")


class FindTests(Base):
    def test_setting_then_path_then_none(self):
        self.assertEqual(camera.find_ffmpeg(self.exe), self.exe)
        with mock.patch.object(camera, "EXTRA_DIRS", ()), mock.patch.object(camera.shutil, "which", return_value=self.exe):
            self.assertEqual(camera.find_ffmpeg(os.path.join(self.dir, "missing")), self.exe)
            self.assertEqual(camera.find_ffmpeg(""), self.exe)
        with mock.patch.object(camera, "EXTRA_DIRS", ()), mock.patch.object(camera.shutil, "which", return_value=None):
            self.assertIsNone(camera.find_ffmpeg(""))

    def test_frame_splitter_handles_split_markers_and_garbage(self):
        sp = camera.FrameSplitter()
        data = b"junk\xff\xd8AB\xff\xd9\xff\xd8CD\xff\xd9\xff\xd8EF"
        out = []
        for i in range(len(data)):
            out += sp.feed(data[i:i + 1])
        self.assertEqual(out, [b"\xff\xd8AB\xff\xd9", b"\xff\xd8CD\xff\xd9"])
        self.assertEqual(sp.feed(b"\xff\xd9"), [b"\xff\xd8EF\xff\xd9"])

    def test_frame_splitter_drops_a_runaway_frame(self):
        sp = camera.FrameSplitter(limit=100)
        self.assertEqual(sp.feed(b"\xff\xd8" + b"x" * 500), [])
        self.assertEqual(sp.feed(b"\xff\xd8ok\xff\xd9"), [b"\xff\xd8ok\xff\xd9"])


class RunTests(Base):
    def test_frames_arrive_whole_and_only_after_ack(self):
        self.url = "rtsp://127.0.0.1:1/live?mode=burst"
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: len(self.frames) == 1))
        # The burst's end is waited for, never assumed after a fixed sleep: on a slow runner the fake was still
        # writing (frame 23 was the latest at the ack, CI run 43670339285, macOS). Then the reader must hold the
        # last frame: only that makes "the latest" frame 29.
        self.assertTrue(wait_for(lambda: os.path.exists(self.pids + ".done"), 10))
        self.assertTrue(wait_for(lambda: cam._latest == b"\xff\xd8F29\xff\xd9"))
        time.sleep(0.3)                                   # well past the 0.2 s frame interval: still held for the ack
        self.assertEqual(len(self.frames), 1)
        self.assertTrue(self.frames[0].startswith(b"\xff\xd8F") and self.frames[0].endswith(b"\xff\xd9"))
        cam.ack()
        self.assertTrue(wait_for(lambda: len(self.frames) == 2))
        self.assertEqual(self.frames[1], b"\xff\xd8F29\xff\xd9")   # the latest, not the oldest
        time.sleep(0.4)
        self.assertEqual(len(self.frames), 2)

    def test_at_most_about_five_frames_a_second(self):
        cam = self.make()
        times = []
        cam2 = self.make(on_frame=lambda f: (times.append(time.monotonic()), cam2.ack()))
        cam2.start()
        self.assertTrue(wait_for(lambda: len(times) >= 4))
        gaps = [b - a for a, b in zip(times, times[1:])]
        self.assertGreaterEqual(min(gaps), 0.15)
        cam.close()

    def test_no_stream_reason_then_starts_when_url_appears(self):
        self.url = ""
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertEqual(self.errors[0][0], "no_stream")
        self.assertEqual(self.spawned, 0)
        self.url = "rtsp://127.0.0.1:1/live?mode=frames"
        self.assertTrue(wait_for(lambda: self.frames))

    def test_bad_scheme_is_no_stream_and_spawns_nothing(self):
        self.url = "file:///etc/passwd"
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertEqual(self.errors[0][0], "no_stream")
        self.assertEqual(self.spawned, 0)

    def test_no_ffmpeg_reason(self):
        with mock.patch.object(camera, "EXTRA_DIRS", ()), mock.patch.object(camera.shutil, "which", return_value=None):
            cam = self.make(ffmpeg_path="")
            cam.start()
            self.assertTrue(wait_for(lambda: self.errors))
        self.assertEqual(self.errors[0][0], "no_ffmpeg")
        self.assertEqual(self.spawned, 0)

    def test_no_ffmpeg_ends_the_reader_instead_of_looking_every_second(self):
        looked = []
        with mock.patch.object(camera, "find_ffmpeg", side_effect=lambda s: looked.append(s)):
            cam = self.make(ffmpeg_path="/gone/ffmpeg")
            cam.start()
            self.assertTrue(wait_for(lambda: self.errors))
            self.assertTrue(wait_for(lambda: not any(t.is_alive() for t in cam._threads)))
            time.sleep(1.3)
        self.assertEqual(looked, ["/gone/ffmpeg"])   # one lookup, not one per second
        self.assertEqual(self.errors, [("no_ffmpeg", "ffmpeg was not found")])

    def test_failure_reports_failed_with_stderr_and_restarts_with_backoff(self):
        self.url = "rtsp://127.0.0.1:1/live?mode=die"
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.spawned >= 3))
        self.assertEqual(self.errors[0][0], "failed")
        self.assertIn("404", self.errors[0][1])
        cam.close()
        self.assertEqual(self.pids_alive(), [])

    def test_url_change_restarts_on_the_new_url_and_kills_the_old_process(self):
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        self.url = "rtsp://127.0.0.1:1/live?mode=frames&token=2"
        n = len(self.frames)
        cam.ack()
        self.assertTrue(wait_for(lambda: self.spawned == 2))
        self.assertTrue(wait_for(lambda: len(self.pids_alive()) == 1))
        self.assertTrue(wait_for(lambda: len(self.frames) > n or (cam.ack() or False)))
        self.assertIn("token=2", self.pid_lines()[1])

    def test_close_reaps_the_process_and_silences_callbacks(self):
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        cam.close()
        self.assertEqual(self.pids_alive(), [])
        n = len(self.frames)
        cam.ack()
        cam.start()                                       # closed: stays closed
        time.sleep(0.3)
        self.assertEqual(len(self.frames), n)
        self.assertEqual(self.spawned, 1)
        self.assertEqual([t for t in threading.enumerate() if t.name.startswith("kobracontrol-camera")], [])

    def test_pipes_are_closed_on_every_restart_and_stop(self):
        fds = open_handles
        self.url = "rtsp://127.0.0.1:1/live?mode=die"
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.spawned >= 1))
        time.sleep(0.3)                                   # let thread and file startup settle
        before = fds()
        self.assertTrue(wait_for(lambda: self.spawned >= 6, 10))
        procs_seen = self.spawned
        cam.stop()
        self.assertGreater(procs_seen, 5)
        self.assertLessEqual(fds(), before)               # 5+ restarts leaked nothing
        self.url = "rtsp://127.0.0.1:1/live?mode=frames"
        for _ in range(3):                                # start/stop cycles with a live ffmpeg
            cam.start()
            self.assertTrue(wait_for(lambda: self.frames))
            cam.stop()
        cam.close()
        self.assertLessEqual(fds(), before)

    def test_stdout_and_stderr_are_closed_after_a_session(self):
        procs = []

        def popen(argv, **kw):
            procs.append(self.popen(argv, **kw))
            return procs[-1]
        cam = self.make(popen=popen)
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        cam.close()
        self.assertTrue(procs and all(p.stdout.closed and p.stderr.closed for p in procs))

    def test_stop_then_start_again(self):
        cam = self.make()
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        cam.stop()
        self.assertEqual(self.pids_alive(), [])
        n = len(self.frames)
        cam.start()
        self.assertTrue(wait_for(lambda: len(self.frames) > n))
        self.assertEqual(self.spawned, 2)

    def test_idle_stops_the_process_and_start_resumes(self):
        cam = self.make(idle_s=0.4)
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        self.assertTrue(wait_for(lambda: self.pids_alive() == [], 3))
        n = len(self.frames)
        cam.start()
        cam.ack()
        self.assertTrue(wait_for(lambda: len(self.frames) > n))

    def test_start_twice_runs_one_process(self):
        cam = self.make()
        cam.start()
        cam.start()
        self.assertTrue(wait_for(lambda: self.frames))
        self.assertEqual(self.spawned, 1)


if __name__ == "__main__":
    unittest.main()
