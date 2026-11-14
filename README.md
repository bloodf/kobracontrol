# kobracontrol

kobracontrol is an OrcaSlicer 2.5 plugin for the Anycubic Kobra X. It talks to the printer directly
on your local network and registers an OrcaSlicer printer agent, so OrcaSlicer's own Print and Send
dialogs and its Device tab work with the Kobra X. It also adds a Kobra Control tab with a dashboard,
camera, ACE card, file list and Spoolman.

Everything stays on your local network. The plugin needs no extra Python packages and no cloud.

> **Status: in development, not released.** The plugin is being built and has not been tested on a
> real printer yet. There is no release and no Orca Cloud listing.

kobracontrol is an independent project. It is not made or supported by Anycubic.

## How it works

kobracontrol connects to the printer over HTTP on port 18910 and MQTT over mutual TLS on port 9883.
The printer must have LAN mode enabled. The printer only accepts the TLS client certificate that
Anycubic Slicer Next carries. The plugin never ships it: on first use it finds the certificate in
your own Anycubic Slicer Next installation (or a file you pick) and keeps a copy in the plugin's
storage folder. The protocol is described in [docs/protocol.md](docs/protocol.md).

## Features

### Printer agent

The agent has the id `kobracontrol`. With it, OrcaSlicer's own dialogs work with the Kobra X:

- Print and Send, with the filament-to-slot mapping you pick in Orca's print dialog.
- Device tab: status, temperatures, pause, resume, stop, light, fan and speed.
- ACE slots shown as filament slots, with sync and slot mapping in Orca's print dialog.
- Device tab camera.

### Kobra Control tab

- **Dashboard:** status and controls, camera, an ACE card (slots, feed, retract, auto-feed and
  drying), Spoolman and Spooler stock.
- **Files:** the printer's files.
- **Settings:** connection, certificate, ffmpeg path, Spoolman and Spooler.

The tab's camera needs `ffmpeg` installed. The Device tab camera does not.

### Plugins > Run

- **Check Kobra X connection:** certificate, credentials, MQTT and firmware version.
- **Find Anycubic certificate:** finds the client certificate and reports the result.

### Works with Spooler

[Spooler](https://github.com/bloodf/spooler) turns your Spoolman filaments into OrcaSlicer filament
profiles. With Spooler installed, kobracontrol shows Spooler's stock on the Dashboard. The plugin
also works alongside [Orca Print Calculator](https://github.com/bloodf/orca_print_calculator). Each
plugin works on its own.

### Not supported

- Anycubic Cloud and access from outside your local network.
- A G-code console. The printer's LAN protocol has none.
- Other Kobra models.

## Requirements

- OrcaSlicer 2.5.0 or newer.
- An Anycubic Kobra X on the same network, with LAN mode enabled.
- Anycubic Slicer Next installed, to find the client certificate.
- `ffmpeg`, only for the tab's camera.

## Install

There is no release yet. Build the wheel and install it:

```sh
python3 scripts/build.py     # writes dist/kobracontrol_any.whl
```

In OrcaSlicer use **File > Plugins > Install local plugin**, pick the wheel, then tick **Activate**.
The **Kobra Control** tab appears next to Prepare, Preview and Device.

## Setup

Full steps are in [docs/setup.md](docs/setup.md). In short:

1. **Certificate:** open the Kobra Control tab and press **Find certificate**.
2. **Preference:** in OrcaSlicer, tick **Preferences > Developer > Experimental Features > Use
   printer agents**.
3. **Printer preset:** set the address to the printer's IP and **Printer Agent** to `kobracontrol`.

## Privacy and security

kobracontrol talks only to your printer and, if you set one up, your Spoolman server. It sends
nothing to the internet. The printer's TLS certificate is self-signed, so the connection is
encrypted but the printer's identity is not verified: use it on a network you trust. The client
certificate copy and the MQTT credentials are never sent to the page or written to logs. See
[SECURITY.md](SECURITY.md).

## Documentation

- [Setup](docs/setup.md)
- [Protocol](docs/protocol.md)
- [Brand image prompt](docs/brand-images-prompt.md)
- [Notice](NOTICE.md), [Contributing](CONTRIBUTING.md), [Changelog](CHANGELOG.md) and [Security](SECURITY.md)

## Credits

The protocol code is ported from two GPL-3.0 projects:
[KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release) (viewit and contributors) and
[Kobralink](https://github.com/NatHacks/Kobralink) (NatHacks). See [NOTICE.md](NOTICE.md).
kobracontrol is independent and not made or supported by Anycubic.

License: [GPL-3.0-only](LICENSE).
