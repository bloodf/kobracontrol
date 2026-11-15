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
import socket
import time

import kobra

SSDP_GROUP = "239.255.255.250"
SSDP_ADDR = (SSDP_GROUP, 1900)
SEARCH_TARGETS = ("ac:3dprinter:", "ssdp:all")   # the second only when the first finds nothing
MARKERS = ("ac:3dprinter", ":18910/")
SEARCH_SECONDS = 2.5            # per search target
SEND_GAP = 0.3                  # s between the two copies of a search
MAX_REPLIES = 64
MAX_REPLY = 2048
MAX_CANDIDATES = 16
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
            data, (ip, _port) = sock.recvfrom(MAX_REPLY)
        except TimeoutError:
            break
        replies += 1
        if ip in seen or not lan_address(ip) or not is_printer_reply(data):
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
    """{"ip", "name", "model"} when a Kobra X in LAN mode answers /info at ip; KobraError otherwise. Nothing in
    the answer is followed: /ctrl is always asked of this same address (kobra.fetch_credentials)."""
    info = kobra._http_json(ip, port, "/info", timeout, "/info")
    token = info.get("token") if isinstance(info, dict) else None
    if not isinstance(token, str) or len(token) < 32:
        raise kobra.KobraError("%s answers /info without a LAN token: is LAN mode on?" % ip, code="no_token")

    def text(*keys):
        return next((str(info[k])[:80] for k in keys if isinstance(info.get(k), (str, int)) and info.get(k) != ""), "")
    return {"ip": ip, "name": text("deviceName", "name", "printerName"), "model": text("modelName", "modelId")}


class Found:
    def __init__(self, host, source, note="", name=""):
        self.host, self.source, self.note, self.name = host, source, note, name


class NotFound(kobra.KobraError):
    """No Kobra X to connect to: the page shows the message, any `candidates` to choose from, and Search again."""
    no_target = True

    def __init__(self, message, candidates=(), pending=()):
        super().__init__(message, code="not_found")
        self.candidates, self.pending = list(candidates), list(pending)


def locate(override, preset_host, remembered="", probe=probe, search=search, own_agent=False, allowed=None):
    """Found or raises NotFound. override: the Settings address, used as given. remembered: the address that
    worked last time for this preset (or the one the user picked among several). allowed(ip): False for an
    address OrcaSlicer has not granted yet; such a candidate is not probed from this (worker) thread, where
    every refused attempt would queue another OrcaSlicer dialog, but returned in NotFound.pending so the page
    can have it granted once on the UI thread."""
    if override:
        return Found(override, "override")
    tried, errors = [], {}
    for host, source in ((remembered, "remembered"), (preset_host, "preset")):
        if not host or host in tried:
            continue
        tried.append(host)
        try:
            info = probe(host)
            return Found(host, source, name=info.get("name", ""))
        except kobra.KobraError as e:
            errors[host] = e
    try:
        replies = search()
    except OSError as e:
        replies, errors["search"] = [], e
    printers, denied = [], []
    for ip, _ in replies:
        if ip in tried:
            continue
        if allowed is not None and not allowed(ip):
            denied.append(ip)
            continue
        try:
            printers.append(probe(ip))
        except kobra.KobraError as e:
            if getattr(e, "code", None) == "denied":
                denied.append(ip)
    if len(printers) == 1:
        found = printers[0]
        note = ""
        if preset_host and preset_host != found["ip"]:
            note = ("The printer preset points to %s, which is not a Kobra X in LAN mode; found the Kobra X at %s "
                    "and using that." % (preset_host, found["ip"]))
        return Found(found["ip"], "discovered", note, found["name"])
    if printers:
        raise NotFound("%d Kobra X printers answer on this network: choose one." % len(printers), printers)
    if denied:   # a new address: OrcaSlicer must allow it first (the page asks for that on the UI thread)
        raise NotFound("Found a printer at %s. Allow Kobra Control to reach it in OrcaSlicer's dialog; it connects "
                       "by itself afterwards." % ", ".join(denied), pending=denied)
    raise NotFound(_nothing(preset_host, own_agent, errors))


def _nothing(preset_host, own_agent, errors):
    why = errors.get("search")
    searched = ("The network search could not run (%s)" % why) if why else "No Kobra X answered the network search"
    if preset_host:
        reason = errors.get(preset_host)
        refused = "refused" in str(reason).lower() or "errno 61" in str(reason).lower() or "errno 111" in str(reason)
        what = ("something answers at %s but it is not a Kobra X in LAN mode (port 18910 refused)" % preset_host
                if refused else "no Kobra X answers at %s (%s)" % (preset_host, reason))
        where = "the printer preset" if not own_agent else "the printer preset (Printer Agent kobracontrol)"
        return ("%s. The address comes from %s, and %s. Enter the printer's own address under Settings > Printer "
                "address, and check that LAN mode is on at the printer." % (searched, where, what))
    return ("%s. Check that the printer is on, on this network and in LAN mode, or enter its address under "
            "Settings > Printer address." % searched)
