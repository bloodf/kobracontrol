"""Locating the tab's printer for service.Service (locate.py does the probing and the search). Free of `orca`.

Mixed into Service, which provides lock, target, generation, connections, connection(), release(), publish,
log, closed, probe, search, granted, http_port and the per-printer state reset.

Rules: a remembered printer (locate.Addresses: address, /info identity, TLS fingerprint) is used again only
where /info gives its identity and the session presents its certificate; any other Kobra X is offered to the
user, never adopted by itself. Relocation runs at most every RELOCATE_EVERY seconds, never while a print is
tracked on the printer or it was last seen printing or paused. Any change of the address in use is a printer
switch: new generation, per-printer state reset, the old connection released.
"""

import socket
import threading
import time

import kobra
import locate
import usage

ORIGIN_TEXT = {"override": "Settings > Printer address", "preset": "the printer preset",
               "remembered": "the address found earlier for this printer preset",
               "discovered": "a search of the local network", "chosen": "the printer you chose"}
RELOCATE_EVERY = 60.0           # s: at most one automatic search per period
BUSY_STATES = ("printing", "paused")


def _background(fn, name, track=None):
    t = threading.Thread(target=fn, name="kobracontrol-" + name, daemon=True)
    if track is not None:
        track.append(t)
    t.start()
    return t


class LocatingMixin:
    def _init_locating(self, addresses_path, search, probe, granted):
        self.addresses = locate.Addresses(addresses_path) if addresses_path else None
        self.search = search
        self.probe = probe or (lambda ip: locate.probe(ip, self.http_port))
        # Addresses OrcaSlicer already lets the plugin reach (declared at load, or allowed since); None outside
        # OrcaSlicer, where every address may be probed.
        self.granted = granted
        self._locating = threading.Lock()
        self._locators = []                       # locate threads, joined by close()
        self.locate_error, self.located_at, self.locate_note = None, 0.0, ""
        self._rejected = set()                    # not a Kobra X: not probed again until Search again
        self._last_state, self._recorded = {}, set()
        self._auto_dialogs = 0                    # OrcaSlicer dialogs raised without a click: at most one per session

    def _start_locate(self, gen, **kw):
        with self.lock:
            if self.closed:
                return
            self._locators = [t for t in self._locators if t.is_alive()]
            _background(lambda: self._locate(gen, **kw), "locate", self._locators)

    def _locate(self, gen, search_only=False, only=None, automatic=False):
        """Find the printer for the target of generation gen (locate.locate), then use it. One at a time.
        only: probe these addresses instead of searching (the ones the user just allowed). automatic: a search the
        plugin started by itself (relocation), whose finds are always offered, never asked about by themselves."""
        with self._locating:
            with self.lock:
                target = self.target if gen == self.generation and not self.closed else None
                skip = set(self._rejected)
            if target is None or target.override:
                return
            record = None
            if self.addresses is not None and not search_only:
                record = self.addresses.get(target.preset_key or "*")
            search = self.search if only is None else (lambda: [(h, {}) for h in only])
            try:
                found = locate.locate("", "" if search_only else target.preset_host, record, probe=self.probe,
                                      search=search, own_agent=target.preset_agent == "kobracontrol", skip=skip,
                                      allowed=None if self.granted is None else self.granted.__contains__)
            except locate.NotFound as e:
                if e.pending and (record or automatic or self._auto_dialogs):
                    e.pending = []   # offered in the page; only the user's click asks OrcaSlicer
                with self.lock:
                    self._rejected.update(e.rejected)
                    if gen == self.generation:
                        self.locate_error, self.located_at = e, time.monotonic()
                self.log("kobracontrol: %s" % e)
                return
            self._use_address(gen, found)

    def _use_address(self, gen, found):
        """Use found.host for the selected target of generation gen. A different address than the one in use is a
        printer switch (as set_target does for a new printer): new generation, state reset, old one released. A
        printer whose identity has a certificate pin must present that certificate, at any address, unless the user
        chose it."""
        if not found.expect_fp and found.identity and found.source != "chosen" and self.pins is not None:
            try:
                found.expect_fp = self.pins.get("id:" + found.identity) or ""
            except OSError:
                pass
        with self.lock:
            target = self.target
            if self.closed or gen != self.generation or target is None or target.override:
                return
            previous = target.host
            moved = bool(previous) and previous != found.host
            if moved:
                self.generation += 1
                self._reset_printer_state()
            target.host, target.source, target.identity = found.host, found.source, found.identity
            self.locate_error, self.located_at, self.locate_note = None, time.monotonic(), found.note
            if self.granted is not None:
                self.granted.add(found.host)
            conn = self.connection(found.host)
            conn.origin, conn.expect_fp, conn.identity = ORIGIN_TEXT.get(found.source, ""), found.expect_fp, found.identity
        if found.note:
            self.log("kobracontrol: " + found.note)
        if moved:
            self.log("kobracontrol: the printer moved from %s to %s" % (previous, found.host))
            self.release(previous)
            self.camera.stop()
            self.publish({"type": "selection_changed"})   # the page says hello again for the new address

    def allow(self, hosts, user=False):
        """UI thread (the page's allow_hosts): let OrcaSlicer ask about printer addresses the search found but may
        not reach yet. On the UI thread its dialog is shown at once and a Yes is saved; on a worker thread the
        attempt would only be refused and a dialog queued per attempt. getaddrinfo of a numeric address is the
        audited event and does no network I/O. user: the user clicked this address; otherwise (the page asking by
        itself) only the one pending address, and only once per plugin session: dialogs are counted, not
        addresses, so new spoofed addresses on every search do not each bring a dialog."""
        with self.lock:
            gen, error = self.generation, self.locate_error
            offered = {c["ip"] for c in getattr(error, "candidates", [])} if user else set(getattr(error, "pending", []))
            if not user:
                if self._auto_dialogs:
                    offered = set()
                elif offered:
                    self._auto_dialogs += 1
        allowed, refused = [], []
        for host in (hosts if isinstance(hosts, list) else [])[:1 if not user else 4]:
            if host not in offered or not locate.lan_address(host):
                continue
            try:
                socket.getaddrinfo(host, self.http_port, socket.AF_INET, socket.SOCK_STREAM)
            except PermissionError:
                refused.append(host)
                continue
            except OSError:
                pass
            allowed.append(host)
            if self.granted is not None:
                self.granted.add(host)
        with self.lock:
            self._rejected.update(refused)
            if allowed and gen == self.generation:
                self.locate_error = None   # the page's next hello waits for the result instead of the old error
        if allowed:
            if user:
                _background(lambda: self._adopt(gen, allowed[0]), "adopt", self._locators)
            else:
                self._start_locate(gen, only=allowed)
        return {"allowed": allowed, "refused": refused}

    def _adopt(self, gen, host):
        """The user chose this printer: use it if a Kobra X answers there, whatever is remembered."""
        try:
            info = self.probe(host)
        except kobra.KobraError as e:
            with self.lock:
                if gen == self.generation:
                    self.locate_error = locate.NotFound(str(e))
            return
        with self.lock:
            target = self.target if gen == self.generation else None
        if target is not None:
            self._forget_record(target)
            self._use_address(gen, locate.Found(host, "chosen", "Connected to %s (%s) at %s, as you chose." % (
                info["name"] or "the Kobra X", info["model"] or "Kobra X", host), info["name"], info.get("id", ""),
                model=info.get("model", "")))

    def _forget_record(self, target):
        with self.lock:
            self._recorded.discard((target.preset_key or "*", target.host))

    def _note_connection(self, conn):
        """A connection's thread (no I/O here): remember what the printer was last doing, record the printer once it
        is connected at a located address, and refuse a session whose certificate was not the expected one."""
        if conn.connected:
            self._last_state[conn.host] = conn.view()["state"]
            with self.lock:
                target = self.target
                key = (target.preset_key or "*", conn.host) if target is not None else None
                due = (target is not None and not target.override and target.host == conn.host
                       and self.addresses is not None and key not in self._recorded)
                if due:
                    self._recorded.add(key)
            if due:
                fp = (conn.server_cert or {}).get("fingerprint", "")
                _background(lambda: self._record(key[0], conn.host, target.identity, fp), "record")
        elif conn.mismatch:
            _background(lambda: self._refuse_impostor(conn), "impostor")
        elif conn.http_failed:
            self._relocate_if_lost(conn)

    def _record(self, key, host, identity, fp):
        try:
            self.addresses.put(key, host, identity, fp)
        except (OSError, ValueError) as e:
            self.log("kobracontrol: the printer's address was not remembered (%s)" % e)

    def _refuse_impostor(self, conn):
        """The session at a remembered printer's address presented another certificate: not used. The remembered
        address stays; the page offers this printer as an explicit choice."""
        with self.lock:
            target = self.target
            if target is None or target.host != conn.host or conn.host not in self.connections:
                return
            self.generation += 1
            self._reset_printer_state()
            target.host, target.source = "", ""
            self.locate_error = locate.NotFound(
                "A different Kobra X answered at %s: its certificate is not the one of the printer Kobra Control knows. "
                "Use it? Kobra Control does not switch to another printer by itself." % conn.host,
                [{"ip": conn.host, "name": "", "model": "", "id": "", "needs_allow": False, "different": True}])
        self.log("kobracontrol: %s" % self.locate_error)
        self.release(conn.host)
        self.publish({"type": "selection_changed"})

    def _relocate_if_lost(self, conn):
        """A located address whose /info stops answering (a new DHCP lease): search again, at most every
        RELOCATE_EVERY seconds. Never for an address set in Settings, and never while a print is tracked on the
        printer or it was last seen printing or paused: then the known address is retried with the usual delay."""
        with self.lock:
            target, gen = self.target, self.generation
            due = (target is not None and not target.override and target.host == conn.host and not self.closed
                   and not self._locating.locked() and time.monotonic() - self.located_at >= RELOCATE_EVERY)
            if due:
                self.located_at = time.monotonic()
        if not due:
            return
        if self._last_state.get(conn.host) in BUSY_STATES or self._tracking(conn.host):
            self._notice("The Kobra X at %s was printing when it stopped answering. Kobra Control keeps trying that "
                         "address and does not look for the printer elsewhere until it answers." % conn.host, gen)
            return
        self._start_locate(gen, automatic=True)

    def _tracking(self, host):
        ident = usage.printer_ident(host)
        return any(job.host == ident for job in self.ledger.pending())

    def wait_located(self, timeout):
        """The located target, or raises the NotFound of the last search (or KobraError after timeout)."""
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                target, error = self.target, self.locate_error
            if target is None:
                raise kobra.KobraError("no Kobra X selected")
            if target.host:
                return target
            if error is not None:
                raise error
            if time.monotonic() >= deadline or self.closed:
                raise kobra.KobraError("still searching the network for the Kobra X")
            time.sleep(0.05)

    def cmd_search_printer(self):
        """Settings > Search again: search the network for the printer of the selected preset; the page says
        hello again afterwards. The address set in Settings, if any, is still the one used."""
        with self.lock:
            gen, target = self.generation, self.target
            self._rejected.clear()
        if target is None:
            raise kobra.KobraError("no Kobra X selected")
        if target.override:
            return {"address": target.host, "source": "override"}
        self._locate(gen, search_only=not target.host)
        with self.lock:
            error = self.locate_error if gen == self.generation else None
            current = self.target.host if self.target is not None and gen == self.generation else ""
            if error is not None and current and not error.candidates:
                self.locate_error = error = None   # nothing else answered: the printer in use stays
        if error is not None:
            raise error
        return {"address": current, "source": target.source}

    def cmd_choose_printer(self, host):
        """The user picked one of the printers offered: remember it for this preset and use it."""
        with self.lock:
            gen, target, error = self.generation, self.target, self.locate_error
        offered = {c["ip"] for c in getattr(error, "candidates", [])}
        if target is None or host not in offered:
            raise ValueError("that printer was not among the ones found; search again")
        self._adopt(gen, host)
        with self.lock:
            error = self.locate_error if gen == self.generation else None
        if error is not None and not (self.target and self.target.host):
            raise error
        return {"address": host}

    def _join_locators(self, timeout=1.0):
        with self.lock:
            threads = list(self._locators)
        for t in threads:
            if t is not threading.current_thread():
                t.join(timeout)

