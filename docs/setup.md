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
4. Expect a long preparation phase after the print starts: the printer heats, levels and cycles
   through the ACE slots before the first layer (about 11 minutes in one test, for a 5 minute
   print). It is not hung.

## 7. Use your own filament preset for a spool (optional)

OrcaSlicer's sync from AMS in the Print dialog picks a filament preset for each ACE slot from the id the
Device tab reports for it. A slot linked to a Spoolman spool gets that spool's Spooler preset, else the
Generic preset of its material. To have it pick a preset you tuned yourself:

1. In Spoolman, open **Settings > Extra fields** and add a field under **Spool**, **Filament** or both:
   key `orca_filament_preset`, type **Text**. Kobra Control only reads the field; [Spooler](https://github.com/bloodf/spooler)
   can create it and fill it from its spool editor.
2. Type the name of your OrcaSlicer filament preset in that field, as OrcaSlicer shows it, for example
   `My PLA @Anycubic Kobra X`. The spool's value wins; an empty spool field falls back to the filament's.
3. The preset must be one of your own (a user preset, not a system or Spooler one) and compatible with the
   selected printer. The exact name is used first, then a name that differs only in upper and lower case.

What sync from AMS can do with it (OrcaSlicer loads the first compatible preset that is its own base and carries
the reported `filament_id`):

- **A standalone preset** (one that inherits nothing, such as a copy made with **Detach from system preset**):
  the Device tab reports the `filament_id` from the preset's own file, so sync loads it. If another compatible
  standalone or system preset has the same id (a detached copy keeps its parent's id), OrcaSlicer takes whichever
  comes first in its list, which may not be yours.
- **A preset that inherits from another** (what **Save as** makes by default): it carries its parent's id, so
  OrcaSlicer's sync can never pick it and would load the parent. The slot keeps the usual id; pick the preset by
  hand after syncing, or detach it.
- A preset whose file has no `filament_id` also keeps the usual id.

If the name isn't one of your own presets compatible with the printer, or matches several of them when upper and
lower case are ignored, the slot keeps the usual preset and the
Kobra Control tab shows a notice once per name in each OrcaSlicer session. The colour, the spool link and the
Spoolman usage booking are not affected.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Nothing connects, the printer does not answer on port 18910 or 9883 | LAN mode is off. Turn it on at the printer. |
| The check reports the certificate is rejected by the printer | The bundled certificate no longer matches this firmware. Install Anycubic Slicer Next and press **Find certificate** to use your own copy (see section 3). |
| The preset has no `kobracontrol` Printer Agent, or Print and Device tab do not use the plugin | **Use printer agents instead of print hosts** is off. Turn it on under Preferences > Developer > Experimental Features and restart OrcaSlicer. |
| "Something answers at … but it is not a Kobra X in LAN mode" | The address is another device, often a bridge such as Kobralink, or LAN mode is off. Leave Settings > Printer address blank so the tab searches, or enter the printer's own IP there. |
| "No Kobra X answered the network search" | The printer is off, on another network, in LAN mode off, or the network blocks multicast. Enter its IP under Settings > Printer address. |
| Connection check fails with a timeout or connection refused | The address is wrong, or the printer is on another network. Use the printer's current IP. |

Not supported: Anycubic Cloud and access from outside the LAN, a G-code console (the printer's LAN
protocol has none), and other Kobra models.
