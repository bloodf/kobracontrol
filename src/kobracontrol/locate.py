"""Where the Kobra X is: the address the tab connects to, found without the user typing it. Free of `orca`.

Order: the address set in Kobra Control's settings (used as given); else the address remembered for this
printer preset and then the preset's own address, each only if a Kobra X answers there; else a search of
the local network. A search that finds exactly one Kobra X uses it; several are offered to the user.

Search: SSDP, as Anycubic Slicer Next does it (its libssdplib: "M-SEARCH * HTTP/1.1", "Host:
239.255.255.250:1900", "ST: ac:3dprinter:{}", "Man: \"ssdp:discover\"", "MX: 5"). Measured on a Kobra X
(firmware 2.0.2.8, 2026-11-15): the printer answers every M-SEARCH (ST "ac:3dprinter:", "ac:3dprinter:20030",
"ssdp:all", "upnp:rootdevice"; multicast or unicast) with one EMPTY UDP datagram from its own address and
sends no NOTIFY. An empty reply is therefore the Kobra X's signature; a text reply counts only when it names
"ac:3dprinter" or ":18910/" (other firmware or models may answer in text), so ordinary UPnP devices (TVs,
routers) are never probed. The search goes out first with ST "ac:3dprinter:" only (other devices ignore an ST
they do not serve), twice SEND_GAP apart against UDP loss, on every local address it is given; "ssdp:all"
follows only when that finds nothing. A reply is untrusted: only its sender's address is used (never a URL or
address inside it), that address must be a private, link-local or loopback IPv4 address, at most MAX_REPLIES
replies of at most MAX_REPLY bytes are read, and a candidate counts only when its own /info answers with a
LAN token.
"""

import ipaddress
import json
import os
import threading
import socket
import time

import certs
import kobra
from i18n import tr

SSDP_GROUP = "239.255.255.250"
SSDP_ADDR = (SSDP_GROUP, 1900)
SEARCH_TARGETS = ("ac:3dprinter:", "ssdp:all")   # the second only when the first finds nothing
MARKERS = ("ac:3dprinter", ":18910/")
SEARCH_SECONDS = 2.5            # per search target
SEND_GAP = 0.3                  # s between the two copies of a search
MAX_REPLIES = 64
MAX_REPLY = 2048                # bytes of a reply that are read; the rest is dropped
RECV_BUFFER = 65535             # the largest UDP datagram: received whole on every OS, then cut to MAX_REPLY
MAX_CANDIDATES = 4             # Kobra X-looking senders kept per search (each may need an OrcaSlicer grant)
PROBE_TIMEOUT = 3.0


def search_packet(target):
    return ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 2\r\n"
            "ST: %s\r\n\r\n" % target).encode("ascii")


def lan_address(ip):
    """True for an IPv4 address a printer on this LAN can have (private, link-local or loopback)."""
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return (addr.is_private or addr.is_link_local or addr.is_loopback) and not (addr.is_multicast or addr.is_unspecified)


def headers(reply):
    """{upper-case name: value} of an SSDP reply (bytes); {} when it is not text."""
    out = {}
    for line in reply.decode("utf-8", "replace").splitlines()[1:]:
        name, sep, value = line.partition(":")
        if sep and name.strip():
            out.setdefault(name.strip().upper(), value.strip()[:200])
    return out


def is_printer_reply(reply):
    """An empty datagram (the Kobra X's answer) or a text reply naming an Anycubic printer."""
    if not reply:
        return True
    text = reply.decode("utf-8", "replace").lower()
    return any(m in text for m in MARKERS)


def local_addresses(addr=None):
    """The local IPv4 address the system routes the search through. The standard library cannot list
    interface addresses without a host-name lookup, which OrcaSlicer's audit would put to the user as a
    prompt for this computer's own name; on one flat network that route reaches every printer."""
    probe_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe_sock.connect(addr or SSDP_ADDR)   # UDP connect sends nothing; it only picks the route
        ip = probe_sock.getsockname()[0]
    except OSError:
        return []
    finally:
        probe_sock.close()
    return [ip] if ip and ip != "0.0.0.0" else []


def _search_once(sock, target, addr, interfaces, timeout):
    for attempt in range(2):
        for local in interfaces or [None]:
            if local:
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
                except OSError:
                    continue
            sock.sendto(search_packet(target), addr)
        if attempt == 0:
            time.sleep(SEND_GAP)
    found, seen, replies = [], set(), 0
    deadline = time.monotonic() + timeout
    while replies < MAX_REPLIES and len(found) < MAX_CANDIDATES:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        sock.settimeout(left)
        try:
            data, (ip, _port) = sock.recvfrom(RECV_BUFFER)   # Windows drops (and raises on) a datagram larger
            data = data[:MAX_REPLY]                            # than the buffer instead of truncating it
        except TimeoutError:
            break
        except OSError:
            # Windows reports a datagram larger than the buffer (WinError 10040) and an ICMP "port unreachable"
            # for an earlier send (WinError 10054, ConnectionResetError) as errors on recvfrom; elsewhere the
            # first is truncated and the second never shows. Either way it is one useless reply, not the end.
            replies += 1
            continue
        replies += 1
        # Only answers from the port the search went to: the real printer replied from its port 1900, and a
        # datagram from any other port is not an answer to this search.
        if _port != addr[1] or ip in seen or not lan_address(ip) or not is_printer_reply(data):
            continue
        seen.add(ip)
        found.append((ip, headers(data)))
    return found


def search(timeout=SEARCH_SECONDS, addr=None, interfaces=None):
    """Senders of Kobra X-looking SSDP replies -> [(ip, headers)], in reply order, LAN addresses only.
    addr: where the search goes (default SSDP_ADDR, read at call time so tests can point it at loopback);
    interfaces: local addresses to send from (default local_addresses())."""
    addr = addr or SSDP_ADDR
    if interfaces is None:
        interfaces = local_addresses(addr) if addr[0] == SSDP_GROUP else []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for target in SEARCH_TARGETS:
            found = _search_once(sock, target, addr, interfaces, timeout)
            if found:
                return found
        return []
    finally:
        sock.close()


def probe(ip, port=18910, timeout=PROBE_TIMEOUT):
    """{"ip", "name", "model", "id"} when a Kobra X in LAN mode answers /info at ip; KobraError otherwise. "id" is
    the printer's identity: /info "cn" (its serial, the same at every address), else "usn". Nothing in the answer
    is followed: /ctrl is always asked of this same address (kobra.fetch_credentials)."""
    info = kobra._http_json(ip, port, "/info", timeout, "/info")
    token = info.get("token") if isinstance(info, dict) else None
    if not isinstance(token, str) or len(token) < 32:
        raise kobra.KobraError(tr("%s answers /info without a LAN token: is LAN mode on?") % ip, code="no_token")

    def text(*keys):
        return next((str(info[k])[:80] for k in keys if isinstance(info.get(k), (str, int)) and info.get(k) != ""), "")
    return {"ip": ip, "name": text("deviceName", "name", "printerName"), "model": text("modelName", "modelId"),
            "id": text("cn", "usn")}


class Addresses:
    """The Kobra X found for each printer preset, in a JSON file in the plugin's storage folder:
    {"printers": {preset: {"ip", "id", "fp"}}}: its address, its /info identity and the SHA-256 fingerprint of
    the TLS certificate it presented. Read defensively: an oversized or malformed file, or an entry that is not
    a LAN IPv4 address with text fields of bounded size, reads as nothing."""
    MAX_BYTES, MAX_ENTRIES = 64 * 1024, 64

    def __init__(self, path):
        self.path, self._lock = path, threading.Lock()

    def _read(self):
        try:
            with open(self.path, "rb") as f:
                raw = f.read(self.MAX_BYTES + 1)
            data = json.loads(raw) if len(raw) <= self.MAX_BYTES else None
        except (OSError, ValueError):
            return {}
        printers = data.get("printers") if isinstance(data, dict) else None
        out = {}
        for key, rec in list(printers.items())[:self.MAX_ENTRIES] if isinstance(printers, dict) else []:
            if not (isinstance(key, str) and len(key) <= 200 and isinstance(rec, dict)):
                continue
            ip, ident, fp = rec.get("ip"), rec.get("id", ""), rec.get("fp", "")
            if (isinstance(ip, str) and lan_address(ip) and isinstance(ident, str) and len(ident) <= 200
                    and isinstance(fp, str) and len(fp) <= 64 and all(c in "0123456789abcdef" for c in fp)):
                out[key] = {"ip": ip, "id": ident, "fp": fp}
        return out

    def get(self, key):
        with self._lock:
            return self._read().get(key)

    def records(self):
        with self._lock:
            return list(self._read().values())

    def hosts(self):
        with self._lock:
            return sorted({r["ip"] for r in self._read().values()})

    def put(self, key, ip, ident="", fp=""):
        """Remember ip for preset `key`. ValueError when another preset already has that address for a printer
        with another identity (two presets never end up pointing at one printer by accident)."""
        with self._lock:
            known = self._read()
            for other, rec in known.items():
                if other != key and rec["ip"] == ip and rec["id"] and ident and rec["id"] != ident:
                    raise ValueError(tr("%s is already remembered for the printer preset %r") % (ip, other))
            known[key] = {"ip": ip, "id": ident, "fp": fp}
            os.makedirs(os.path.dirname(self.path) or ".", 0o700, exist_ok=True)
            certs._write_private(self.path, json.dumps({"printers": known}, indent=1, sort_keys=True))


class Found:
    """The address to use. identity: the printer's /info identity; expect_fp: the TLS fingerprint the connection
    must see there (a remembered printer), "" when there is nothing to compare with (first contact)."""

    def __init__(self, host, source, note="", name="", identity="", expect_fp="", model=""):
        self.host, self.source, self.note, self.name = host, source, note, name
        self.identity, self.expect_fp, self.model = identity, expect_fp, model


class NotFound(kobra.KobraError):
    """No Kobra X to use by itself: the page shows the message and `candidates` ({ip, name, model, needs_allow,
    different}) to choose from, and Search again. pending: the one address the page may have OrcaSlicer allow
    without asking first; rejected: addresses that are not a Kobra X, not asked about again this session."""
    no_target = True

    def __init__(self, message, candidates=(), pending=(), rejected=()):
        super().__init__(message, code="not_found")
        self.candidates, self.pending, self.rejected = list(candidates), list(pending), list(rejected)


def _found_note(found, preset_host):
    where = tr("%s%s at %s") % (found["name"] or tr("a Kobra X"), " (%s)" % found["model"] if found["model"] else "", found["ip"])
    note = tr("Connected to %s, found on the network.") % where
    if preset_host and preset_host != found["ip"]:
        note = tr("The printer preset points to %s, which is not a Kobra X in LAN mode. %s") % (preset_host, note)
    return note


def locate(override, preset_host, record=None, probe=probe, search=search, own_agent=False, allowed=None, skip=()):
    """Found, or raises NotFound. override: the Settings address, used as given. record: {"ip", "id", "fp"}
    remembered for this preset. A remembered printer is only ever used again at an address whose /info gives
    its identity (and the connection then checks its certificate fingerprint); any other Kobra X is offered,
    never adopted by itself. With nothing remembered, the preset's address is used if a Kobra X answers there,
    else the one Kobra X the search finds. allowed(ip): False for an address OrcaSlicer has not granted yet: it
    is not probed (from this worker thread each refused attempt queues another OrcaSlicer dialog) but offered;
    skip: addresses already found not to be a Kobra X this session."""
    if override:
        return Found(override, "override")
    record = record or {}
    tried, errors, different = [], {}, []

    def mine(info):
        return bool(record.get("id")) and info.get("id") == record["id"]
    for host, source in ((record.get("ip"), "remembered"), (preset_host, "preset")):
        if not host or host in tried or (allowed is not None and not allowed(host)):
            continue   # an ungranted address is not probed here; the search offers it if a Kobra X is there
        tried.append(host)
        try:
            info = probe(host)
        except kobra.KobraError as e:
            errors[host] = e
            continue
        if mine(info) or not record:
            return Found(host, source, name=info["name"], identity=info.get("id", ""), model=info.get("model", ""),
                         expect_fp=record.get("fp", "") if mine(info) else "")
        different.append(info)
    try:
        replies = search()
    except OSError as e:
        replies, errors["search"] = [], e
    printers, ungranted, rejected = [], [], []
    for ip, _ in replies:
        if ip in tried or ip in skip:
            continue
        if allowed is not None and not allowed(ip):
            ungranted.append(ip)
            continue
        try:
            info = probe(ip)
        except kobra.KobraError as e:
            if getattr(e, "code", None) != "denied":
                rejected.append(ip)
            continue
        if mine(info):
            return Found(ip, "discovered", tr("Found %s again at %s.") % (info["name"] or tr("the Kobra X"), ip), info["name"],
                         info.get("id", ""), record.get("fp", ""), info.get("model", ""))
        (different if record else printers).append(info)
    offered = [{**c, "needs_allow": False, "different": bool(record)} for c in different + printers]
    offered += [{"ip": ip, "name": "", "model": "", "id": "", "needs_allow": True, "different": bool(record)}
                for ip in ungranted]
    if len(printers) == 1 and not different and not ungranted:
        found = printers[0]
        return Found(found["ip"], "discovered", _found_note(found, preset_host), found["name"], found.get("id", ""),
                     model=found.get("model", ""))
    if record and record.get("ip") and not offered:
        # The remembered printer does not answer and nothing else does: keep its address (the connection retries
        # it with its growing delay), never another printer.
        return Found(record["ip"], "remembered", expect_fp=record.get("fp", ""), identity=record.get("id", ""))
    if different:
        raise NotFound(tr("A different Kobra X answered at %s. Use it? Kobra Control does not switch to another printer "
                       "by itself.") % ", ".join(c["ip"] for c in different), offered, rejected=rejected)
    if len(offered) > 1:
        raise NotFound(tr("%d possible Kobra X printers answer on this network: choose one.") % len(offered), offered,
                       rejected=rejected)
    if ungranted:   # exactly one: the page has OrcaSlicer ask about it once
        raise NotFound(tr("Found a printer at %s. Allow Kobra Control to reach it in OrcaSlicer's dialog; it connects "
                       "by itself afterwards.") % ungranted[0], offered, pending=ungranted, rejected=rejected)
    raise NotFound(_nothing(preset_host, own_agent, errors), rejected=rejected)


def _nothing(preset_host, own_agent, errors):
    why = errors.get("search")
    searched = (tr("The network search could not run (%s)") % why) if why else tr("No Kobra X answered the network search")
    if preset_host:
        reason = errors.get(preset_host)
        refused = "refused" in str(reason).lower() or "errno 61" in str(reason).lower() or "errno 111" in str(reason)
        what = (tr("something answers at %s but it is not a Kobra X in LAN mode (port 18910 refused)") % preset_host
                if refused else tr("no Kobra X answers at %s (%s)") % (preset_host, reason))
        where = tr("the printer preset") if not own_agent else tr("the printer preset (Printer Agent kobracontrol)")
        return tr("%s. The address comes from %s, and %s. Enter the printer's own address under Settings > Printer "
                  "address, and check that LAN mode is on at the printer.") % (searched, where, what)
    return tr("%s. Check that the printer is on, on this network and in LAN mode, or enter its address under "
              "Settings > Printer address.") % searched
