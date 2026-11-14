"""One printer address: its MQTT session, its `kobra.State` and the loop that keeps both alive. Free of the
`orca` module. The printer agent and the Kobra Control tab share one Connection per address (service.py).

The loop runs on its own thread: load the saved client certificate, recover the MQTT credentials from the
printer (kept in memory only, never logged), connect, then ask for a read-only snapshot (info/query,
print/query, multiColorBox/getInfo) and keep polling info/query (and print/query during a print), as
Kobralink's pollLoop does. Nothing else is ever sent on its own: every other command is the user's.
When the session drops it reconnects with a growing delay, recovering the credentials again each time.
"""

import threading
import time

import certs
import kobra

POLL_EVERY = 5.0                # s between read-only polls while connected
RETRY_FIRST, RETRY_MAX = 2.0, 60.0
CONNECT_QUERIES = (("info", "query"), ("print", "query"), ("multiColorBox", "getInfo"))


class NoCertificate(kobra.KobraError):
    """No usable saved Anycubic Slicer client certificate: the page offers Find certificate."""
    no_certificate = True


def tls_from(cert_dir):
    """The default `tls` factory: an ssl.SSLContext from the certificate saved in cert_dir."""
    def load():
        if not cert_dir:
            raise NoCertificate("no storage folder for the Anycubic Slicer certificate")
        try:
            certs.load(cert_dir)
            return certs.context(*certs.paths(cert_dir))
        except certs.CertError as e:
            raise NoCertificate("%s: run Find Anycubic certificate (needs Anycubic Slicer Next installed)" % e) from None
    return load


def _explain(host, error):
    text = str(error)
    if "ermission" in text or "denied" in text.lower():
        return ("OrcaSlicer has not allowed kobracontrol to reach %s yet: allow it in OrcaSlicer's permission "
                "prompt, then retry (%s)" % (host, text))
    return text


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
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._connected = threading.Event()
        self._thread = None

    # -- lifecycle -------------------------------------------------------------------------------------
    def start(self):
        with self._lock:
            if self._thread is None and not self._stop.is_set():
                self._thread = threading.Thread(target=self._loop, name="kobracontrol-link", daemon=True)
                self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self._wake.set()
        printer = self.printer
        if printer:
            printer.close()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(3)

    def retry(self):
        """Try again now (the user pressed Retry, or a certificate was just saved)."""
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
        delay = RETRY_FIRST
        while not self._stop.is_set():
            if not self.connected:
                if self._open():
                    delay = RETRY_FIRST
                else:
                    self._wake.wait(delay)
                    self._wake.clear()
                    delay = min(delay * 2, RETRY_MAX)
                    continue
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
            self._fail(_explain(self.host, e), False)
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
