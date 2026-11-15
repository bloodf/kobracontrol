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

- **Printer:** HTTP on port 18910 and MQTT over mutual TLS on port 9883, at the address you set.
  Addresses the printer reports about itself are ignored, redirects are refused, and the camera is
  streamed only from the printer's own address.
- **Client certificate:** the printer accepts only the certificate (`CN=AnycubicSlicer`) that
  Anycubic Slicer Next carries. This is a shared client identity, identical in every copy of Anycubic
  Slicer Next, not a per-user secret; kobracontrol **bundles it** (in the package and the wheel) so
  the plugin connects without a setup step. Anyone who has the wheel has this certificate and its
  key. You can override the bundled copy with the one from your own Anycubic Slicer Next install:
  **Find certificate** saves it in the plugin's storage folder and uses it instead. On macOS and
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
