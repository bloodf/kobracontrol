"""One printer address: its MQTT session, its `kobra.State` and the loop that keeps both alive. Free of the
`orca` module. The printer agent and the Kobra Control tab share one Connection per address (service.py).

The loop runs on its own thread: load the saved client certificate, recover the MQTT credentials from the
printer (kept in memory only, never logged), connect, then ask for a read-only snapshot (info/query,
print/query, multiColorBox/getInfo) and keep polling info/query (and print/query during a print), as
Kobralink's pollLoop does. Nothing else is ever sent on its own: every other command is the user's.
When the session drops it reconnects with a growing delay, recovering the credentials again each time.
"""

import os
import threading
import time
import urllib.parse

import certs
import kobra

POLL_EVERY = 5.0                # s between read-only polls while connected
RETRY_FIRST, RETRY_MAX = 2.0, 60.0
STABLE_AFTER = 30.0             # s a session must stay up before the retry delay starts again from RETRY_FIRST
CONNECT_QUERIES = (("info", "query"), ("print", "query"), ("multiColorBox", "getInfo"))


class NoCertificate(kobra.KobraError):
    """No usable saved Anycubic Slicer client certificate: the page offers Find certificate."""
    no_certificate = True


def tls_from(cert_dir):
    """The default `tls` factory: an ssl.SSLContext from the certificate saved in cert_dir, or the
    one bundled with the plugin when none has been saved."""
    def load():
        if cert_dir:
            try:
                certs.load(cert_dir)
                return certs.context(*certs.paths(cert_dir))
            except certs.CertError:
                pass
        shipped = certs.bundled()
        if shipped:
            return certs.context(*shipped)
        raise NoCertificate("no Anycubic Slicer certificate: run Find Anycubic certificate "
                            "(needs Anycubic Slicer Next installed)")
    return load


def _explain(host, error):
    """The error to show. code "denied" (kobra: OrcaSlicer's audit refused the connection) says what to do."""
    if getattr(error, "code", None) == "denied" or isinstance(error, PermissionError):
        return ("OrcaSlicer has not let kobracontrol reach %s yet. Allow kobracontrol to reach %s in the dialog "
                "OrcaSlicer just showed, then press Retry. If no dialog appeared, restart OrcaSlicer once so the "
                "saved address is granted when the plugin loads." % (host, host))
    return str(error)


class Connection:
    def __init__(self, host, tls, log=print, http_port=18910, mqtt_port=9883, fetch=kobra.fetch_credentials,
                 model="Anycubic Kobra X"):
        self.host, self.tls, self.log, self.fetch = host, tls, log, fetch
        self.http_port, self.mqtt_port = http_port, mqtt_port
        self.state = kobra.State(model)
        self.printer = None
        self.error, self.no_certificate = "", False
        self.firmware_name = ""
        self._listeners = []
        self._lock = threading.Lock()
        self._wake = threading.Event()      # ends the poll wait: a drop, a retry or stop
        self._retry = threading.Event()     # ends a backoff wait: only a retry (the user's) or stop
        self._opened_at = None
        self.start_lock = threading.Lock()  # "check idle + print/start" runs for one job at a time
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = None

    # -- lifecycle -------------------------------------------------------------------------------------
    def start(self):
        """Start the loop thread, or start it again if it ever ended (it should not: see _loop)."""
        with self._lock:
            if (self._thread is None or not self._thread.is_alive()) and not self._stop.is_set():
                self._thread = threading.Thread(target=self._loop, name="kobracontrol-link", daemon=True)
                self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._retry.set()
        printer = self.printer
        if printer:
            printer.close()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(3)

    def retry(self):
        """Try again now (the user pressed Retry, or a certificate was just saved)."""
        self.start()
        self._retry.set()
        self._wake.set()

    def wait_connected(self, timeout):
        return self._connected.wait(timeout)

    @property
    def connected(self):
        printer = self.printer
        return bool(printer and printer.connected and self.state.connected)

    def add_listener(self, fn):
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def remove_listener(self, fn):
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    @property
    def listeners(self):
        with self._lock:
            return list(self._listeners)

    def _notify(self):
        for fn in self.listeners:
            try:
                fn(self)
            except Exception as e:   # one consumer must not starve the other
                self.log("kobracontrol: status listener failed: %r" % e)

    # -- loop --------------------------------------------------------------------------------------
    def _loop(self):
        delay = [RETRY_FIRST]
        while not self._stop.is_set():
            try:
                self._step(delay)
            except Exception as e:   # never let the loop die: pause and stop must stay reachable
                self.log("kobracontrol: %s: connection loop error %s: %s" % (self.host, type(e).__name__, e))
                self._backoff(delay)

    def _backoff(self, delay):
        """Wait delay[0] (cut short only by retry() or stop()), then double it up to RETRY_MAX."""
        self._retry.wait(delay[0])
        self._retry.clear()
        delay[0] = min(delay[0] * 2, RETRY_MAX)

    def _step(self, delay):
        """One turn: reconnect with backoff when not connected, else wait and poll."""
        if not self.connected:
            if self._opened_at is not None:   # a session just ended: never reconnect at once
                stable = time.monotonic() - self._opened_at >= STABLE_AFTER
                self._opened_at = None
                if stable:
                    delay[0] = RETRY_FIRST
                self._backoff(delay)
                if self._stop.is_set():
                    return
            if not self._open():
                self._backoff(delay)
            return
        self._wake.wait(POLL_EVERY)
        self._wake.clear()
        if not self._stop.is_set() and self.connected:
            self._poll()

    def _open(self):
        old, self.printer, printer = self.printer, None, None
        if old:
            old.close()
        try:
            ssl_context = self.tls()
            creds = self.fetch(self.host, port=self.http_port)
            printer = kobra.Printer(creds, ssl_context=ssl_context, mqtt_port=self.mqtt_port, http_port=self.http_port,
                                    on_report=self._report, on_disconnect=self._dropped)
            printer.connect()
        except kobra.KobraError as e:
            if printer:
                printer.close()
            self._fail(_explain(self.host, e), getattr(e, "no_certificate", False))
            return False
        except OSError as e:   # e.g. the plugin sandbox refusing a socket before kobra wraps it
            if printer:
                printer.close()
            self._fail(_explain(self.host, e), False)
            return False
        except Exception as e:   # anything else a hostile or broken answer can raise (RecursionError, ...)
            if printer:
                printer.close()
            self._fail("unexpected answer from the printer (%s: %s)" % (type(e).__name__, e), False)
            return False
        if self._stop.is_set():
            printer.close()
            return False
        self.printer = printer
        self._poll(initial=True)   # the first snapshot, before anyone sees the printer as connected
        if not printer.connected:
            self._fail("the printer closed the connection right after it opened", False)
            return False
        self.state.connected = True
        self._opened_at = time.monotonic()
        self.error, self.no_certificate = "", False
        self._connected.set()
        self.log("kobracontrol: connected to %s" % self.host)
        self._notify()
        return True

    def _poll(self, initial=False):
        printer = self.printer
        if not printer:
            return
        queries = CONNECT_QUERIES if initial else CONNECT_QUERIES[:1]
        for type_, action in queries:
            printer.request(type_, action, timeout=5)
        if not initial and self.state.view()["state"] in ("printing", "paused"):
            printer.query_print()

    def _fail(self, error, no_certificate):
        changed = error != self.error
        self.error, self.no_certificate = error, no_certificate
        self.state.connected = False
        self._connected.clear()
        if changed:
            self.log("kobracontrol: %s: %s" % (self.host, error))
        self._notify()

    def _report(self, suffix, payload):
        self.state.apply(suffix, payload)
        self._notify()

    def _dropped(self, reason):
        self.state.connected = False
        self._connected.clear()
        self.error = "connection to the printer lost (%s); reconnecting" % (reason or "closed")
        self.log("kobracontrol: %s: %s" % (self.host, self.error))
        self._notify()
        self._wake.set()

    def view(self):
        return self.state.view()

    def __repr__(self):
        return "Connection(%r, connected=%r)" % (self.host, self.connected)


def wait_until(predicate, timeout, step=0.05):
    """Poll predicate() until it is true or timeout passes; returns its last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value or time.monotonic() >= deadline:
            return value
        time.sleep(step)


def camera_url_for(view, host, log=None, logged=None):
    """The printer's stream URL only when its host is the printer itself, else "". The URL comes from the
    printer and goes to ffmpeg (or to OrcaSlicer's viewer), so a stream elsewhere is never opened."""
    url = (view.get("camera_url") or "") if view and view.get("connected") else ""
    try:
        same = bool(url) and (urllib.parse.urlsplit(url).hostname or "").lower() == str(host).lower()
    except ValueError:
        same = False
    if url and not same:
        if log and (logged is None or url not in logged):   # `logged`: the caller's set, one line per URL
            if logged is not None:
                logged.add(url)
            log("kobracontrol: camera stream %s is not on the printer (%s); not opened" % (url, host))
        return ""
    return url


DENIED_PATH = ("OrcaSlicer did not let kobracontrol read %s. Allow it in OrcaSlicer's permission dialog (Plugins > "
               "Permissions), then press Find certificate again.")


def find_and_save_certificate(cert_dir, path=None):
    """Find the Anycubic Slicer client certificate (in `path`, else the default install folders, which the plugin
    holds tree grants for) and save it in cert_dir. Key matching writes its candidates under cert_dir (the plugin
    storage folder), never through tempfile, which OrcaSlicer denies off the main thread."""
    if not cert_dir:
        raise certs.CertError("no storage folder to keep the certificate in")
    if path:
        real = os.path.realpath(str(path))
        if not os.path.exists(real):
            raise ValueError("%s does not exist" % path)
        try:   # a read OrcaSlicer denies off the main thread must say so, not "nothing found"
            if os.path.isdir(real):
                os.listdir(real)
            else:
                open(real, "rb").close()
        except PermissionError:
            raise certs.CertError(DENIED_PATH % path) from None
        where = [real]
    else:
        where = certs.default_locations()
    os.makedirs(cert_dir, 0o700, exist_ok=True)
    found = certs.find(where, workdir=cert_dir)
    certs.save(cert_dir, found.cert_pem, found.key_pem)
    return found
