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

## What it touches

- **Printer:** HTTP on port 18910 and MQTT over mutual TLS on port 9883, at the address you set.
  Addresses the printer reports about itself are ignored, redirects are refused, and the camera is
  streamed only from the printer's own address.
- **Client certificate:** the printer accepts only the certificate that Anycubic Slicer Next
  carries. kobracontrol never ships it. It finds the certificate and its private key in your own
  Anycubic Slicer Next installation, or in a file you pick, and keeps a copy in the `tls` folder of
  the plugin's storage folder. On macOS and Linux the copy is readable only by you (mode 0600). On
  Windows it is protected only by the permissions of your user profile. While searching, candidate
  keys are written to a private temporary folder and removed afterwards. The key is never sent to
  the page or written to logs.
- **MQTT credentials:** recovered from the printer each time it connects and kept in memory only.
  They are never written to disk, sent to the page or written to logs.
- **Spoolman:** the `http://` or `https://` address you enter, wherever it points. Binding a spool
  writes that spool's location in Spoolman; finished prints book filament use there when the option
  is on.
- **ffmpeg:** the tab's camera starts `ffmpeg` as a subprocess to turn the printer's stream into
  frames. It stops when the page is idle. OrcaSlicer asks for permission when it starts.
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
allow, and it sends the printer nothing on its own except status queries.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private
[security advisory](https://github.com/bloodf/kobracontrol/security/advisories/new) form and include
the version, what an attacker can do, and how to reproduce it. You'll get an answer within a week.
