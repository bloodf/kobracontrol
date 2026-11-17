# Setup

The Kobra Control tab needs only LAN mode on the printer: the client certificate is built in and the tab
finds the printer on the network. OrcaSlicer's own Print, Send and Device tab go through kobracontrol
only when the "Use printer agents instead of print hosts" preference is on and the printer preset's agent is `kobracontrol`
(sections 4 and 5). Without that, for example next to Kobralink or another Moonraker bridge, they keep
using the preset's own agent and the tab works on its own.
kobracontrol is in development. The connection, status, files, camera stream and
printing were checked on a real Kobra X (firmware 2.0.2.8) outside OrcaSlicer. These setup steps,
and everything inside OrcaSlicer (Device tab, Print dialog, permissions dialog), have not been
confirmed on a real printer yet.

kobracontrol targets stock OrcaSlicer 2.5 or newer. It does not need a patched build such as
[OrcaSlicer-KX](https://gitea.it-drui.de/viewit/OrcaSlicer-KX).

## 1. Install the plugin

Build the wheel and install it:

```sh
python3 scripts/build.py
```

In OrcaSlicer, use **File > Plugins > Install local plugin**, pick `dist/kobracontrol_any.whl`, then
tick **Activate** and allow what OrcaSlicer asks for. The **Kobra Control** tab appears next to
Prepare, Preview and Device.

## 2. Turn on LAN mode on the printer

The plugin talks to the printer on the local network and needs LAN mode enabled on the Kobra X.
Put the computer and the printer on the same network.

The tab finds the printer by itself, in this order:

1. the address under Settings > Printer address, if you typed one (used as given);
2. the address it found before for the selected printer preset;
3. the printer preset's own address, if a Kobra X in LAN mode answers there;
4. a search of the local network (SSDP). One Kobra X found: it is used and remembered for the preset.
   Several: the Dashboard lists them once and remembers your choice.

If a found address stops answering (a new DHCP address, say), it searches again by itself, at most once
a minute. Settings shows the address in use and how it was found, with **Search again**. When the
preset's address is not a Kobra X (a Moonraker bridge such as Kobralink at port 7125, say), the tab says
so in one line and uses the printer it found.

The first time the tab finds a printer on the network, OrcaSlicer asks once whether kobracontrol may
connect to that address. Allow it; the tab connects by itself.

## 3. Certificate (built in)

The printer accepts only the TLS client certificate that Anycubic Slicer Next carries. kobracontrol
bundles this certificate and reads it from its own package, so there is nothing to do here and
Anycubic Slicer Next is not needed. The plugin never looks into Anycubic Slicer Next on its own.

If a future firmware stops accepting the bundled certificate, you can replace it with the one from
your own Anycubic Slicer Next install: Settings > Anycubic certificate > **Use the certificate from my
own Anycubic Slicer Next install** > **Find certificate**, or Plugins > **Find Anycubic certificate**.
OrcaSlicer asks once whether kobracontrol may read that file (on macOS
`AnycubicSlicerNext.app/Contents/Frameworks/libcloud_mqtt.dylib`); allow it and press Find certificate
again. The plugin saves the copy in its storage folder and uses it instead of the bundled one.

## 4. Turn on printer agents in OrcaSlicer

Open **Preferences > Developer > Experimental Features**, tick **Use printer agents instead of print hosts** and restart
OrcaSlicer. Settings > Requirements in the Kobra Control tab shows "In use" once OrcaSlicer runs the
kobracontrol agent (a plugin cannot read the preference itself, so before that it says "Not detected").

## 5. Set the printer preset (only for Print, Send and the Device tab)

In a copy of your Kobra X printer preset:

- set the printer's address to the printer's IP
- set **Printer Agent** to `kobracontrol`

Keep any other preset you use for the printer as it is. A preset whose agent is `moonraker` (for
Kobralink) keeps working through Kobralink; the Kobra Control tab says which agent the preset uses.

## 6. Check and print

1. Run Plugins > **Check Kobra X connection**. It reports the certificate, credentials, MQTT
   connection and firmware version.
2. Open the Device tab: status, temperatures and ACE slots should appear.
3. In Orca's Print dialog, sync the ACE slots, map each filament to a slot and send the print.
   Kobra Control's print setup window then opens (OrcaSlicer's own dialog can't be replaced, so there are two):
   check each filament's slot and the options, then Start print. Settings > Print defaults can turn it off.
4. Expect a long preparation phase after the print starts: the printer heats, levels and cycles
   through the ACE slots before the first layer (about 11 minutes in one test, for a 5 minute
   print). It is not hung.

## 7. G-code checks before sending

When OrcaSlicer's Print or Send goes through kobracontrol, the plugin reads the plate's G-code before the
upload: the first 1 MB and the last 256 kB. It never changes the file, and a warning never stops the print.
Each warning shows as an OrcaSlicer notification and in the log; the Print dialog's last line ("Print
started" or "File uploaded") says to look at the notification. Plugins > **Check Kobra X connection** names the same settings when the
selected Kobra X printer preset has them.

| Check | Warning when | What to change in the printer preset |
|---|---|---|
| Settings block | No `; CONFIG_BLOCK_END` in the file. | Turn off **Printer settings > Basic information > Advanced > Skip G-code config block** and slice again. |
| Preview picture | No `; thumbnail ... begin` block. | Set **Printer settings > Basic information > Advanced > G-code thumbnails**, for example to `300x300/PNG`, and slice again. |
| PNG preview | Thumbnails only in JPG, QOI or another format. | Use `/PNG` sizes in **G-code thumbnails**. |

Why these two blocks: on firmware 2.0.2.8 the printer's file details (`file/fileDetails`, see
[protocol.md](protocol.md)) carry the picture as a PNG and the printer model, each filament's type,
colour and weight, the layer height, temperatures and speeds, which OrcaSlicer writes in the preview
block and in the settings block. That the screen needs them is inferred from that answer: a file without
them has not been tried on a Kobra X, so the warnings say "probably" and "likely cause". The settings
block finding was first reported for the Kobra 3 V2. Both settings are in OrcaSlicer's Advanced mode.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Nothing connects, the printer does not answer on port 18910 or 9883 | LAN mode is off. Turn it on at the printer. |
| The check reports the certificate is rejected by the printer | The bundled certificate no longer matches this firmware. Install Anycubic Slicer Next and press **Find certificate** to use your own copy (see section 3). |
| The preset has no `kobracontrol` Printer Agent, or Print and Device tab do not use the plugin | **Use printer agents instead of print hosts** is off. Turn it on under Preferences > Developer > Experimental Features and restart OrcaSlicer. |
| "Something answers at … but it is not a Kobra X in LAN mode" | The address is another device, often a bridge such as Kobralink, or LAN mode is off. Leave Settings > Printer address blank so the tab searches, or enter the printer's own IP there. |
| "No Kobra X answered the network search" | The printer is off, on another network, in LAN mode off, or the network blocks multicast. Enter its IP under Settings > Printer address. |
| Connection check fails with a timeout or connection refused | The address is wrong, or the printer is on another network. Use the printer's current IP. |
| The printer's screen shows no filament or no picture for a file sent from OrcaSlicer | Likely the printer preset skips the G-code settings block or writes no PNG preview. See section 7. |

Not supported: Anycubic Cloud and access from outside the LAN, a G-code console (the printer's LAN
protocol has none), and other Kobra models.
