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

## Optional: Upload bridge (OrcaSlicer's OctoPrint host)

Off by default. With it on, OrcaSlicer's own **Upload** and **Upload and Print** buttons (the OctoPrint
host type, which the stock Kobra X preset already uses) reach the printer through Kobra Control. No printer agent
is needed for it.

1. In the Kobra Control tab, open **Settings > Upload bridge**, turn on **Accept uploads from OrcaSlicer**,
   keep or change the port (8765 by default) and press **Save settings**. OrcaSlicer may ask once to let
   Kobra Control use the network address 127.0.0.1: answer Yes. The status then reads
   "Listening on 127.0.0.1:8765".
2. Press **Copy** next to the API key.
3. In OrcaSlicer, edit the Kobra X printer preset and open its connection settings (the icon next to the printer):
   - **Host type**: OctoPrint
   - **Hostname, IP or URL**: `127.0.0.1:8765` (the port from step 1)
   - **API Key / Password**: paste the key
4. Press **Test**. OrcaSlicer should report a successful connection.

**Upload** stores the plate's G-code on the printer. **Upload and Print** stores it too, then waits: the Kobra
Control tab shows "A print from OrcaSlicer is waiting" with **Start print** and **Don't print**. Nothing prints
until you press Start, and Start is refused unless the printer is idle; an Upload and Print sent while the
printer is busy is refused before anything is uploaded. A waiting print is forgotten after 10 minutes (the file
stays on the printer). Start uses the print options from **Settings > Print defaults** and the loaded ACE slots in
order, as a print from the Files tab does.

What the bridge does and does not do:

- It listens on 127.0.0.1 only. Other computers on the network cannot reach it.
- Every request needs the API key. The key is kept in the plugin's storage folder in its own file
  (`bridge_key.txt`, readable by your user only), never in the settings file. **New key** replaces it at once;
  paste the new key into OrcaSlicer afterwards.
- It accepts one request at a time, 30 requests a minute, and locks out for a minute after 5 wrong keys.
  Uploads larger than 1 GB are refused. Requests whose Host is not 127.0.0.1 or localhost, and requests from web
  pages (an `Origin` or `Sec-Fetch-Site` header), are refused.
- It never overwrites the file the printer is printing, and a new upload with the name of a waiting print
  drops that waiting print.
- It speaks only the two requests OrcaSlicer's OctoPrint client makes (`GET /api/version` and
  `POST /api/files/local`). It is not a full OctoPrint server.
- Turning it off in Settings, or unloading the plugin, stops it.

## Optional: Purge and bed wait

Off by default, and **not yet tried on a Kobra X**. With it on, every print Kobra Control sends (OrcaSlicer's Print
and Send with the `kobracontrol` agent, and the Upload bridge) goes out as a processed **copy** of the sliced G-code;
the sliced file itself is never changed. Settings shows the exact lines for the values you choose. The copy gets two
kinds of lines, each wrapped in `; >>> kobracontrol purge add-on` and `; <<< kobracontrol purge add-on` comments.

**Before the first layer** (right before the first `;LAYER_CHANGE`), unless the file already has an `M190` there:

```gcode
M190 S<t> ; wait for the first-layer bed temperature
```

`<t>` is the first-layer bed temperature the file itself sets before its first layer: the first `M140 S<t>`, or the
Kobra X start macro's `G9111 bedTemp=<t>`.

**After each tool change during the print** (`T0` to `T15`, each ACE filament load, between the first
`;LAYER_CHANGE` and the end G-code; never in the start or end G-code, never for `T255`). With the defaults (15 mm at
5 mm/s, front-left corner, 260 x 260 mm bed), the first purge is:

```gcode
M83                  ; relative extrusion for the purge
G91
G1 Z3.203 F1200      ; lift: 2 mm plus the height the purged line can reach
G90
G1 X5 Y5 F12000      ; to this purge's own lane, 5 mm inside the corner
G91
G1 Z-3.203 F1200     ; back down to the layer height
G90
G1 X35 Y5 E15 F600   ; extrude while moving 30 mm along the lane (takes length / speed seconds)
G91
G1 Z3.203 F1200
G90
G1 X<x> Y<y> F12000  ; back to the last X/Y before the tool change (left out before the first move)
G91
G1 Z-3.203 F1200
G90
M83                  ; the extrusion mode as it was: M83, or M82 followed by G92 E<the E the file had reached>
```

Each purge after that takes the next lane, 3 mm further in from the edge (5 lanes in a 15 mm strip), then the next
30 mm row along the same edge, so no two purges land on one another. A 260 mm bed has room for 35 purges; a file
with more tool changes is refused. Purge length (1-50 mm), speed (1-20 mm/s) and corner (front left, front right,
back left, back right) are set in **Settings > Purge and bed wait**.

**The risk:** the purge strip is the 15 mm along the front (or back) edge of the bed from the chosen corner. Keep it
clear of parts and clips. A purged line can curl up, stick to the nozzle or be hit if the strip is not clear, so
watch the first prints with it on.

A file that cannot take these lines is refused with a message and nothing is sent: no bed size (`printable_area`)
in the file, no first-layer bed temperature when an `M190` is needed, relative moves (`G91`) at a tool change, or
more tool changes than lanes.

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
