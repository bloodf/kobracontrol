# Security

kobracontrol connects to the printer address you give it and, if you set one up, to your Spoolman
server. It has no cloud service of its own.

## What it protects and what it does not

Use kobracontrol only on a network you trust. The Kobra X's LAN protocol gives little protection,
and kobracontrol cannot add any:

- **The MQTT credentials are public to the network.** The printer hands them out over plain HTTP
  (port 18910), scrambled with a key that travels in the same exchange. Anyone on the network who
  watches that exchange, or simply asks the printer, gets them.
- **The printer is not verified.** MQTT (port 9883) runs over TLS, but the printer's certificate is
  self-signed and is not checked. TLS stops someone from passively reading the MQTT traffic. It does
  not stop a device that answers in the printer's place.
- **A changed printer certificate is reported, not refused.** kobracontrol remembers the SHA-256
  fingerprint of the certificate each printer address presents (`printers.json` in the plugin's
  `tls` storage folder) and shows the current one in Settings. When a later connection presents a
  different one, the log and every tab of Kobra Control say so, and the new fingerprint is remembered.
  The connection is kept: whether a firmware update or a factory reset gives the printer a new
  certificate is not known, and refusing would stop a working printer with no way to recover from the
  plugin. The first connection to an address is trusted as it is, and an impostor that answers before
  the real printer was ever seen is not detected. Treat the warning as a reason to check the printer
  before you send it a print.

## What it touches

- **Printer:** HTTP on port 18910 and MQTT over mutual TLS on port 9883, at the address you set or, when
  you set none, at the one the plugin found. Addresses the printer reports about itself are ignored
  (also `ctrlInfoUrl` in `/info`: `/ctrl` is always asked of the same address), redirects are refused,
  and the camera is streamed only from the printer's own address.
- **Finding the printer:** with no address set, the plugin tries the address it found before and the
  printer preset's address, then sends SSDP searches to the local multicast group 239.255.255.250 (port
  1900). Replies are untrusted: only the address a reply came from is used, never an address or URL
  inside it; it must be a private, link-local or loopback IPv4 address and the reply must come from
  port 1900; at most 64 replies of at most 2048 bytes are read per search and at most 4 senders kept;
  and an address counts as a printer only when its own `/info` answers with a LAN token. Kobra Control
  brings up OrcaSlicer's permission dialog by itself at most once per session, and only when one new
  printer was found and none is remembered for the preset; in every other case the printers found are
  listed and you pick. An address that is not a Kobra X, or that you refused, is not asked about again until you press
  Search again. A search the plugin starts by itself, when a found printer stops answering, runs at
  most once a minute.
- **Which printer is used:** the printer found for a preset is remembered in the plugin's storage folder
  (`addresses.json`) with its identity (`cn` from `/info`, its serial) and the fingerprint of the TLS
  certificate it presented at the first connection; the fingerprint is also kept per identity, so it
  follows the printer to a new address. Later it is used only at an address whose `/info`
  gives that identity, and the session must present that certificate; otherwise it is not used, the
  remembered printer stays, and the tab asks "A different Kobra X answered at X. Use it?". A different
  printer is never taken by itself, even when it is the only one answering, and the plugin never looks
  for the printer elsewhere while it was printing. Any change of the address in use is handled as a
  printer switch: pending commands for the old one are refused. The certificate pin is enforced as soon as the
  plugin uses a remembered printer, also on a session that was already open (for example opened first by
  OrcaSlicer's Print or Device tab): a session that presented another certificate is closed at once.
- **An address you typed** (Settings > Printer address, or the printer preset's address used by OrcaSlicer's
  Print, Send and Device tab) is pinned per address and only warned about: a different certificate later is
  logged and shown on every tab, and the connection is kept. The first connection to a printer found
  on the network says which printer it is (name, model, address).

- **Client certificate:** the printer accepts only the certificate (`CN=AnycubicSlicer`) that
  Anycubic Slicer Next carries. This is a shared client identity, identical in every copy of Anycubic
  Slicer Next, not a per-user secret; kobracontrol **bundles it** (in the package and the wheel) so
  the plugin connects without a setup step. Anyone who has the wheel has this certificate and its
  key. The plugin never reads Anycubic Slicer Next on its own. You can override the bundled copy with
  the one from your own install: **Find certificate** (an advanced option in Settings) reads that
  install, after OrcaSlicer asks you, and saves the copy in the plugin's storage folder. On macOS and
  Linux a saved copy is readable only by you (mode 0600); on Windows it is protected only by the
  permissions of your user profile. While searching, candidate keys are written to a private
  temporary folder and removed afterwards. Neither the bundled key nor a saved key is ever sent to
  the page or written to logs.
- **MQTT credentials:** recovered from the printer each time it connects and kept in memory only.
  They are never written to disk, sent to the page or written to logs.
- **Spoolman:** the `http://` or `https://` address you enter, wherever it points. Binding a spool
  writes that spool's location in Spoolman; finished prints book filament use there when the option
  is on.
- **ffmpeg:** the tab's camera starts `ffmpeg` as a subprocess to turn the printer's stream into
  frames. It stops when the page is idle. OrcaSlicer asks for permission to run that exact command
  when it starts, and again whenever the printer's stream address changes.
- **Files:** the plugin keeps its settings and its print ledger in its own storage folder. It
  uploads the G-code you print to the printer. It downloads nothing.
- **Spooler:** it reads Spooler's files and never writes them.

### Someone on your network answering the search

The printer's certificate is self-signed, so the first contact with a printer is trust on first use:
on a network where another device answers the search before the real printer, and you allow that
address in OrcaSlicer's dialog, Kobra Control connects to that device. What it could then obtain:

- the print files you send and the commands you give (start, pause, temperatures, moves), and the
  status the tab would show;
- not the client certificate in any meaningful sense: it is Anycubic's shared one, public by design and
  in the wheel;
- not your printer's MQTT credentials: they come from the printer itself, never from Kobra Control;
- not your Spoolman credentials or files on your computer.

Once the real printer is remembered, its identity and certificate pin, together with the explicit
choice above, stop a device that answers later from taking its place unnoticed. A device that copies
the printer's `/info` identity is still refused if it cannot present the printer's certificate.

## What asks first

In the Kobra Control tab, stopping a print, heating, homing, turning the motors off, skipping
objects, feeding or retracting filament, starting a drying cycle, printing a stored file and
deleting files all ask first. Jog moves do not ask: they are limited to 50 mm per press and are
available only while the printer is idle or paused.

Commands from OrcaSlicer's own Device tab and Print dialog go through OrcaSlicer's interface, with
whatever confirmations OrcaSlicer shows.

Whatever the page or OrcaSlicer sends, the plugin refuses a command the printer's state does not
allow. On its own it sends the printer only status queries and the "feed finished" acknowledgement
the printer waits for after a filament load or unload.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private
[security advisory](https://github.com/bloodf/kobracontrol/security/advisories/new) form and include
the version, what an attacker can do, and how to reproduce it. You'll get an answer within a week.
