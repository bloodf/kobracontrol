<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-hero-dark-en.png">
    <img alt="Kobra Control: run the Anycubic Kobra X from OrcaSlicer over your LAN" src="assets/readme/kobracontrol-hero-light-en.png" width="100%">
  </picture>
</p>

<h1 align="center">🟣 Kobra Control</h1>
<p align="center"><b>Run the Anycubic Kobra X from OrcaSlicer over your LAN.</b><br><sub>An OrcaSlicer plugin · by bloodf</sub></p>

<p align="center">
  <a href="https://cloud.orcaslicer.com/p/59c786285255"><img alt="Install from Orca Cloud" src="https://img.shields.io/badge/Orca_Cloud-Install-6240c8?style=for-the-badge"></a>
  <a href="https://github.com/bloodf/kobracontrol/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/bloodf/kobracontrol?style=for-the-badge&color=6240c8"></a>
  <img alt="OrcaSlicer 2.5+" src="https://img.shields.io/badge/OrcaSlicer-2.5%2B-555?style=for-the-badge">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/bloodf/kobracontrol?style=for-the-badge&color=555"></a>
</p>

<p align="center">
  <a href="#-install">Install</a> · <a href="#-features">Features</a> · <a href="#-how-to-use">How to use</a> · <a href="#-faq">FAQ</a> · <a href="README.pt-BR.md">Português</a>
</p>

## ✨ What it does

Kobra Control (`kobracontrol`) is an OrcaSlicer 2.5 plugin for the Anycubic Kobra X. It talks to the printer directly on your local network and registers an OrcaSlicer printer agent, so OrcaSlicer's own Print and Send dialogs and its Device tab work with the Kobra X. It also adds a **Kobra Control** tab with a dashboard, the camera, the ACE filament slots, the printer's files and Spoolman. It needs no cloud account and no extra Python packages.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-dashboard-dark-en.png">
    <img alt="The Dashboard during a print: 37 % done, time left, nozzle and bed temperatures, the camera picture and the filament slots" src="assets/readme/kobracontrol-dashboard-light-en.png" width="100%">
  </picture>
</p>

## 📦 Install

Kobra Control is listed on Orca Cloud: open [its page](https://cloud.orcaslicer.com/p/59c786285255) and install it from there.

From a file:

1. Download `kobracontrol_any.whl` from the [latest release](https://github.com/bloodf/kobracontrol/releases/latest).
2. In OrcaSlicer open **File > Plugins > Install local plugin** and pick the wheel.
3. Tick **Activate** and allow what OrcaSlicer asks for. The **Kobra Control** tab appears next to Prepare, Preview and Device.

| Requirement | Detail |
|---|---|
| OrcaSlicer | 2.5.0 or newer, the stock build. No patched build is needed. |
| Printer | An Anycubic Kobra X on the same network, with LAN mode enabled. Checked on firmware 2.0.2.8. |
| `ffmpeg` | Only for the camera in the Kobra Control tab. The Device tab camera works without it. |
| Anycubic Slicer Next | Not required. The client certificate the printer asks for is bundled. |
| Spoolman | Optional, for spool tracking. |

### Verified on the printer

Run on a real Kobra X through the plugin's service layer, outside OrcaSlicer. The dates come from the [changelog](CHANGELOG.md) and [docs/protocol.md](docs/protocol.md).

| What was checked | Firmware | Date |
|---|---|---|
| Connect, credentials, status, ACE slots, file list, details, upload and delete, light, camera stream | 2.0.2.8 | 2026-11-14 |
| Homing, jogging and heating while idle | 2.0.2.8 | 2026-11-14 |
| A print from a `.3mf` with a slot mapping, finish detection and the job's filament use | 2.0.2.8 | 2026-11-14 |
| How the printer answers the network search (SSDP) | 2.0.2.8 | 2026-11-15 |
| Listing the time-lapse videos | 2.0.2.8 | 2026-11-16 |
| Deleting a time-lapse video | 2.0.2.8 | 2026-11-16 |

Not tried on the printer yet: pause, resume, stop, filament feed and retract, drying, slot edit, skip objects, speed mode, Spoolman booking, flow calibration and time-lapse at print start, the Printer panel and Print Assist, and the G-code checks. Nothing has been tested inside OrcaSlicer itself (Device tab, Print dialog, permission dialogs).

Kobra Control is an independent project. It is not made or supported by Anycubic.

## 🧰 Features

<table>
  <tr>
    <td width="50%" valign="top">
      <img alt="The Settings page with the connection answering and the certificate ready" src="assets/orca-cloud/kobracontrol-feature-01-lan-en.png" width="100%">
      <p><b>Send prints over your local network</b><br>Print and Send work from OrcaSlicer's own dialogs. The tab finds the printer by itself and the client certificate is built in.</p>
    </td>
    <td width="50%" valign="top">
      <img alt="The Dashboard with progress, temperatures and the camera picture" src="assets/orca-cloud/kobracontrol-feature-02-status-en.png" width="100%">
      <p><b>Keep an eye on your print</b><br>Progress, layer, time left and the clock time the print should finish, next to temperatures, fan, speed, light and the camera.</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img alt="Four ACE slots with material, colour, weight left and drying at 50 °C" src="assets/orca-cloud/kobracontrol-feature-03-ace-en.png" width="100%">
      <p><b>Manage the filament in each slot</b><br>Every print head and ACE slot shows its colour and material, with feed, retract, auto-feed, drying and the Spoolman spool linked to it.</p>
    </td>
    <td width="50%" valign="top">
      <img alt="The printer's file list and the print panel with time, layers, filament and slot mapping" src="assets/orca-cloud/kobracontrol-feature-04-files-en.png" width="100%">
      <p><b>Choose files before you print</b><br>Browse the printer's files and see time, layers, filament and which ACE slot prints each colour before you press <b>Start printing</b>.</p>
    </td>
  </tr>
</table>

| Feature | What you get |
|---|---|
| Printer agent | The agent id is `kobracontrol`. Print and Send use the filament-to-slot mapping you pick in OrcaSlicer's print dialog, with auto-leveling, flow calibration and time-lapse from that dialog and vibration compensation from the plugin's settings. Before sending, it reads the sliced G-code and warns when the settings block or a PNG preview picture is missing. |
| Device tab | Status, temperatures, pause, resume, stop, light, fan, speed and the camera in OrcaSlicer's own Device tab. ACE slots show there as filament slots, with sync and slot mapping in the print dialog. |
| Dashboard | Status and controls, moves and homing, the camera, the filament card, a Printer panel and the Spoolman and Spooler stock. |
| Printer panel | Name and **Rename**, firmware, network address, print counters and the **Print Assist** switches. |
| Files | Search and sorting (newest, oldest, name, size). The print panel warns when a slot holds a different material than the file was sliced with, when a filament has no loaded slot, and when the file was sliced for another printer. The confirmation repeats the warning. |
| Time-lapses | The printer's time-lapse videos with print, date, length and size, and **Delete**. The printer offers no way to download a video over the local network yet. |
| Spoolman | Link a Spoolman spool to a slot. Finished prints book their filament use there when the option is on. |
| Works with Spooler | [Spooler](https://github.com/bloodf/spooler) turns your Spoolman filaments into OrcaSlicer filament profiles. With it installed, the Dashboard shows Spooler's stock. Kobra Control also works alongside [Print Calculator](https://github.com/bloodf/orca_print_calculator). |
| Settings | Connection (with the printer's certificate fingerprint), certificate, print defaults, `ffmpeg` path, Spoolman and language. If the printer presents a different TLS certificate than last time, every tab shows a warning. |
| Plugins > Run | **Check Kobra X connection** reports the certificate, credentials, MQTT and firmware version. **Find Anycubic certificate** looks for the client certificate and reports the result. |

Not supported: Anycubic Cloud and access from outside your local network, a G-code console (the printer's LAN protocol has none), and other Kobra models.

<a id="-how-to-use"></a>
## 🛠️ How to use

1. Turn on LAN mode on the Kobra X and put the printer and the computer on the same network.
2. Open the **Kobra Control** tab. It looks for the printer by itself. The first time, OrcaSlicer asks once whether kobracontrol may connect to that address. Allow it.
3. Use the **Dashboard** to follow the print, set temperatures, turn the camera on with **Turn on**, and feed, retract or dry filament.
4. To print a file stored on the printer, open **Files**, press **Print** on the file, check the panel and press **Start printing**.
5. To send prints from OrcaSlicer itself, tick **Preferences > Developer > Experimental Features > Use printer agents**. Then, in a copy of your Kobra X printer preset, set **Printer Agent** to `kobracontrol` and the address to the printer's IP.
6. Run **Plugins > Check Kobra X connection**. Then, in OrcaSlicer's print dialog, sync the ACE slots, map each filament to a slot and send the print.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/kobracontrol-files-dark-en.png">
    <img alt="The Files tab: three files on the printer, four time-lapse videos, and the print panel for desk_organiser_plate_1.gcode with a warning that slot 2 holds ABS instead of PETG" src="assets/readme/kobracontrol-files-light-en.png" width="100%">
  </picture>
</p>

Steps 5 and 6 are optional. Without them the tab works on its own, for example next to Kobralink or another Moonraker bridge that your printer preset already uses, and OrcaSlicer's Print, Send and Device tab keep using the preset's own agent.

The tab looks for the printer in this order: the address in **Settings** if you set one, the address it found before for the selected printer preset, the preset's own address if a Kobra X answers there, then a search of the local network (SSDP, the way Anycubic Slicer Next finds printers).

After a print starts, the printer can spend many minutes in preparation (heating, levelling, and cycling through the ACE slots) before the first layer. In one test that took about 11 minutes for a 5 minute print. The printer is not hung; the job is reported as printing meanwhile.

Full steps and a troubleshooting table are in [docs/setup.md](docs/setup.md).

## 🔒 Privacy and safety

### What the plugin can access

| OrcaSlicer permission | What it is used for |
|---|---|
| Network: the printer's address and the multicast group 239.255.255.250 | HTTP on port 18910 (credentials, G-code upload), MQTT over TLS on port 9883 (status and commands) and the network search. OrcaSlicer asks once for a printer found later. |
| Network: your Spoolman address, only if you set one | Spool links and filament use. |
| Read: OrcaSlicer's temporary folder | The sliced file that Print and Send hand over. It is read, checked and uploaded as it is, never changed. |
| Read: Anycubic Slicer Next's files, only when you press **Find certificate** | Its client certificate. OrcaSlicer asks first. |
| Run: `ffmpeg`, only for the camera in the tab | Turning the printer's stream into pictures. OrcaSlicer shows the command and asks. |
| Threads | Network work off OrcaSlicer's main thread. |

Print files and commands go to the printer, spool links and filament use go to Spoolman, and nothing goes anywhere else. There is no telemetry and no analytics. The plugin writes files only in its own storage folder (settings, the print ledger, the printers it found) and reads Spooler's stock list when Spooler is installed.

### Network and certificate

Kobra Control connects only to the Kobra X and to your Spoolman server, if you set one. The printer is reached over HTTP on port 18910 and MQTT over mutual TLS on port 9883, at the address you set or one the plugin found on your local network and confirmed as a Kobra X in LAN mode. The network search sends SSDP queries to the local multicast group 239.255.255.250 only. There is no cloud service.

Use it on a network you trust. The printer hands out its MQTT credentials to anyone on the network, and its TLS certificate is self-signed and not verified, so the connection is protected against passive reading only.

The printer accepts only the TLS client certificate that Anycubic Slicer Next carries. That certificate is a shared client identity, the same in every copy of Anycubic Slicer Next, not a per-user secret, and the plugin bundles it. Neither that certificate's key nor the MQTT credentials are ever sent to the page or written to logs.

In the tab, stopping a print, heating, homing, turning the motors off, skipping objects, feeding or retracting filament, starting a drying cycle, printing a stored file and deleting files all ask first. Details are in [SECURITY.md](SECURITY.md).

## ❓ FAQ

<details>
<summary>Do I need Anycubic Slicer Next installed?</summary>

No. The client certificate is bundled, so there is no certificate step. If a future firmware stops accepting the bundled copy, **Find certificate** (in **Settings**, under the certificate's advanced option) replaces it with the one from your own Anycubic Slicer Next install.
</details>

<details>
<summary>The print started but nothing moves for minutes. Is it stuck?</summary>

No. The printer heats, levels and cycles through the ACE slots before the first layer. In one test that took about 11 minutes for a 5 minute print.
</details>

<details>
<summary>Can I keep using Kobralink or another Moonraker bridge?</summary>

Yes. Leave your printer preset as it is. The Kobra Control tab finds the printer and works on its own, and OrcaSlicer's Print, Send and Device tab keep going through the bridge. When the preset's address is a bridge and not the printer, the tab says so in one line.
</details>

<details>
<summary>Why does OrcaSlicer ask for permission to run ffmpeg?</summary>

The camera in the Kobra Control tab uses `ffmpeg` to turn the printer's stream into pictures. When the camera starts, OrcaSlicer shows the full command with the printer's stream address and asks. It asks again when that address changes, which happens when the printer restarts. The Device tab camera does not need `ffmpeg`.
</details>

<details>
<summary>Nothing connects, or "No Kobra X answered the network search".</summary>

Check that LAN mode is on at the printer and that the printer and the computer are on the same network. If your network blocks multicast, type the printer's IP under **Settings > Printer address**.
</details>

<details>
<summary>"Something answers at … but it is not a Kobra X in LAN mode".</summary>

The address belongs to another device, often a bridge such as Kobralink, or LAN mode is off. Leave **Settings > Printer address** blank so the tab searches, or type the printer's own IP there.
</details>

<details>
<summary>The printer preset has no kobracontrol Printer Agent.</summary>

**Use printer agents** is off. Turn it on under **Preferences > Developer > Experimental Features** and restart OrcaSlicer.
</details>

<details>
<summary>Can I download the time-lapse videos?</summary>

Not yet. The printer has no known way to hand a video over the local network, so the tab lists and deletes them only.
</details>

## 🌍 Languages

English, Brazilian Portuguese, Spanish, German and Simplified Chinese. The tab follows OrcaSlicer's language, and **Settings > Language** changes it.

## 🧩 More plugins by bloodf

| | Plugin | What it does | |
|:-:|---|---|---|
| <img src="https://raw.githubusercontent.com/bloodf/orca_organizer/main/assets/orca-cloud/orca_organizer-tile.png" alt="Organizer icon" width="40"> | 🧩 [Organizer](https://github.com/bloodf/orca_organizer) | Arrange parts by their real outline and fill a plate with more copies. | [Install](https://cloud.orcaslicer.com/p/5bf381fd42d4) |
| <img src="https://raw.githubusercontent.com/bloodf/embedder/main/assets/orca-cloud/embedder-tile.png" alt="Embedder icon" width="40"> | 🧲 [Embedder](https://github.com/bloodf/embedder) | Magnet and NFC pockets, with the pause at the right layer. | [Install](https://cloud.orcaslicer.com/p/58222d4f9e52) |
| <img src="https://raw.githubusercontent.com/bloodf/orca_print_calculator/main/assets/orca-cloud/orca_print_calculator-tile.png" alt="Print Calculator icon" width="40"> | 💰 [Print Calculator](https://github.com/bloodf/orca_print_calculator) | Price every plate: filament, energy, labour, fees and margin. | [Install](https://cloud.orcaslicer.com/p/521c07cf6de2) |
| <img src="https://raw.githubusercontent.com/bloodf/spooler/main/assets/orca-cloud/spooler-tile.png" alt="Spooler icon" width="40"> | 🧵 [Spooler](https://github.com/bloodf/spooler) | Your Spoolman stock inside OrcaSlicer, with what is left on each spool. | [Install](https://cloud.orcaslicer.com/p/50c35dcbd6f3) |
| <img src="assets/orca-cloud/kobracontrol-tile.png" alt="Kobra Control icon" width="40"> | 🟣 **Kobra Control** · you are here | Run the Anycubic Kobra X from OrcaSlicer over your LAN. | |
| <img src="https://raw.githubusercontent.com/bloodf/u1control/main/assets/orca-cloud/u1control-tile.png" alt="U1 Control icon" width="40"> | 🔵 [U1 Control](https://github.com/bloodf/u1control) | Run the Snapmaker U1 from OrcaSlicer: toolheads, camera, files. | [Install](https://cloud.orcaslicer.com/p/55b8c347d443) |

Each plugin works on its own; installed together they share data where it helps.

## 🤝 Contributing

Bug reports, logs and pull requests are welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md). The developer documentation is in [docs/](docs/): [setup](docs/setup.md), [architecture](docs/architecture.md), [protocol](docs/protocol.md), [releasing](docs/release.md) and the [Orca Cloud description](docs/orca-cloud-description.md). See also the [changelog](CHANGELOG.md), the [security notes](SECURITY.md) and [NOTICE.md](NOTICE.md) for credits to the projects the protocol code is ported from.

## 📄 License

GPL-3.0-only. See [LICENSE](LICENSE).

Printer photo: Anycubic product image (see [NOTICE.md](NOTICE.md)).

<p align="center"><sub>by bloodf</sub></p>
