# Setup

Four things have to be in place before OrcaSlicer prints to a Kobra X through kobracontrol: LAN mode
on the printer, the client certificate, the "Use printer agents" preference and a printer preset.
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
Put the computer and the printer on the same network and note the printer's IP address.

## 3. Certificate (bundled)

The printer accepts only the TLS client certificate that Anycubic Slicer Next carries. kobracontrol
bundles this certificate, so there is nothing to do here: the plugin connects out of the box.

If a future firmware stops accepting the bundled certificate, you can replace it with the one from
your own Anycubic Slicer Next install:

1. Install Anycubic Slicer Next.
2. Open the **Kobra Control** tab and press **Find certificate**, or run Plugins > **Find Anycubic
   certificate**. The plugin saves the found copy in its storage folder and uses it instead of the
   bundled one.

## 4. Turn on printer agents in OrcaSlicer

Open **Preferences > Developer > Experimental Features** and tick **Use printer agents**. Restart
OrcaSlicer if it asks.

## 5. Set the printer preset

In a copy of your Kobra X printer preset:

- set the printer's address to the printer's IP
- set **Printer Agent** to `kobracontrol`

Keep any other preset you use for the printer as it is.

## 6. Check and print

1. Run Plugins > **Check Kobra X connection**. It reports the certificate, credentials, MQTT
   connection and firmware version.
2. Open the Device tab: status, temperatures and ACE slots should appear.
3. In Orca's Print dialog, sync the ACE slots, map each filament to a slot and send the print.
4. Expect a long preparation phase after the print starts: the printer heats, levels and cycles
   through the ACE slots before the first layer (about 11 minutes in one test, for a 5 minute
   print). It is not hung.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Nothing connects, the printer does not answer on port 18910 or 9883 | LAN mode is off. Turn it on at the printer. |
| The check reports the certificate is rejected by the printer | The bundled certificate no longer matches this firmware. Install Anycubic Slicer Next and press **Find certificate** to use your own copy (see section 3). |
| The preset has no `kobracontrol` Printer Agent, or Print and Device tab do not use the plugin | **Use printer agents** is off. Turn it on under Preferences > Developer > Experimental Features and restart OrcaSlicer. |
| Connection check fails with a timeout or connection refused | The address in the preset is wrong, or the printer is on another network. Use the printer's current IP. |

Not supported: Anycubic Cloud and access from outside the LAN, a G-code console (the printer's LAN
protocol has none), and other Kobra models.
