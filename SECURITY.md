# Security

kobracontrol talks only to your Kobra X and, if you set one up, your Spoolman server, on your local
network. It has no cloud service and sends nothing to the internet.

## What it touches

- **Printer:** HTTP on port 18910 and MQTT over mutual TLS on port 9883. The printer's TLS
  certificate is self-signed, so the connection is encrypted but the printer's identity is not
  verified. Use it only on a network you trust.
- **Client certificate:** the printer accepts only the certificate that Anycubic Slicer Next carries.
  kobracontrol never ships it. It finds it in your own Anycubic Slicer Next installation, or in a
  file you pick, and keeps a copy in the plugin's storage folder, readable only by you (mode 0600).
- **MQTT credentials:** the username and password the printer returns are recovered at connection
  time and kept in memory only. They are never written to disk, sent to the page or written to
  logs. The certificate's private key is treated the same way.
- **ffmpeg:** the tab's camera starts `ffmpeg` as a subprocess to turn the stream into frames. It
  stops when the page is idle. OrcaSlicer asks for permission when it starts.
- **Files:** the plugin keeps its settings in its own storage folder and saves downloads to
  `~/Downloads/kobracontrol`, never overwriting a file.
- **Spooler:** it reads Spooler's files and never writes them.

Deleting files, moving or heating the printer, stopping a print and drying all ask first.

## Reporting a vulnerability

Please don't open a public issue. Use GitHub's private
[security advisory](https://github.com/bloodf/kobracontrol/security/advisories/new) form and include
the version, what an attacker can do, and how to reproduce it. You'll get an answer within a week.
