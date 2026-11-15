"""Read-only network search for Kobra X printers: python3 scripts/discover.py [--seconds 5] [--all] [--ip IP].

Sends the plugin's two SSDP searches (ST "ac:3dprinter:" and "ssdp:all" to 239.255.255.250:1900), prints
every reply that looks like an Anycubic printer (with --all: every reply, so the real format can be
checked), then asks each such sender's http://<ip>:18910/info once, as the plugin does to confirm a
printer. --ip also asks /info of that address directly. Nothing else is sent: no /ctrl, no MQTT, nothing that
moves or changes the printer. Tokens, serial numbers and similar values are masked.
"""

import argparse
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "kobracontrol"))

import kobra  # noqa: E402
import locate  # noqa: E402

SECRET_WORDS = ("token", "cn", "sn", "serial", "password", "key", "secret", "uuid", "usn", "deviceid", "device_id")


def mask(name, value):
    text = str(value)
    if any(w in name.lower() for w in SECRET_WORDS) and len(text) > 6:
        return "%s...(%d chars)" % (text[:4], len(text))
    return text


def listen(seconds, show_all, out):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    interfaces = locate.local_addresses() if locate.SSDP_ADDR[0] == locate.SSDP_GROUP else []
    for local in interfaces or [None]:
        if local:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(local))
        for target in locate.SEARCH_TARGETS:
            sock.sendto(locate.search_packet(target), locate.SSDP_ADDR)
    out("sent M-SEARCH for %s to %s:%d from %s, listening %g s" % (", ".join(locate.SEARCH_TARGETS), *locate.SSDP_ADDR,
                                                                 ", ".join(interfaces) or "the default route", seconds))
    found, deadline = [], time.monotonic() + seconds
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        sock.settimeout(left)
        try:
            data, (ip, port) = sock.recvfrom(locate.MAX_REPLY)
        except TimeoutError:
            break
        printer = locate.is_printer_reply(data)
        if not (printer or show_all):
            continue
        if not data:
            out("\nreply from %s:%d: empty datagram [Kobra X signature]" % (ip, port))
        else:
            first = data.decode("utf-8", "replace").splitlines()[:1]
            out("\nreply from %s:%d%s  %s" % (ip, port, "  [Anycubic]" if printer else "", first[0] if first else ""))
        for name, value in locate.headers(data).items():
            out("    %s: %s" % (name, mask(name, value)))
        if printer and ip not in found:
            found.append(ip)
    sock.close()
    return found


def confirm(ip, out):
    try:
        info = kobra._http_json(ip, 18910, "/info", 3, "/info")
    except kobra.KobraError as e:
        out("  /info at %s: %s" % (ip, e))
        return
    fields = {k: mask(k, v) for k, v in info.items()} if isinstance(info, dict) else info
    ok = isinstance(info, dict) and isinstance(info.get("token"), str) and len(info["token"]) >= 32
    out("  /info at %s: %s -> %s" % (ip, "a Kobra X in LAN mode" if ok else "NOT a Kobra X in LAN mode",
                                      json.dumps(fields, sort_keys=True)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--all", action="store_true", help="print every SSDP reply, not only Anycubic ones")
    parser.add_argument("--ip", action="append", default=[], help="also ask /info of this address")
    args = parser.parse_args(argv)
    found = listen(args.seconds, args.all, print)
    print("\n%d Anycubic-looking repl%s" % (len(found), "y" if len(found) == 1 else "ies"))
    for ip in found + [ip for ip in args.ip if ip not in found]:
        if not locate.lan_address(ip):
            print("  %s: not a LAN address, not asked" % ip)
            continue
        confirm(ip, print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
