# Setup

Four things have to be in place before OrcaSlicer prints to a Kobra X through kobracontrol: LAN mode
on the printer, the client certificate, the "Use printer agents" preference and a printer preset.
kobracontrol is in development and not released, so these steps have not been confirmed on a real
printer yet.

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

## 3. Find the certificate

The printer accepts only the TLS client certificate that Anycubic Slicer Next carries. kobracontrol
does not ship it.

1. Install Anycubic Slicer Next if it is not installed.
2. Open the **Kobra Control** tab. With no certificate, the page shows one task: finding it.
3. Press **Find certificate**. The plugin looks in your Anycubic Slicer Next installation. If it
   finds nothing, pick the file yourself.
4. The plugin keeps a copy in its storage folder. Plugins > Run > **Find Anycubic certificate** does
   the same from the menu.

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

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Nothing connects, the printer does not answer on port 18910 or 9883 | LAN mode is off. Turn it on at the printer. |
| The page asks for the certificate again, or the check reports no certificate | Anycubic Slicer Next is not installed, or the plugin could not find it. Install it, or pick the certificate file with **Find certificate**. |
| The preset has no `kobracontrol` Printer Agent, or Print and Device tab do not use the plugin | **Use printer agents** is off. Turn it on under Preferences > Developer > Experimental Features and restart OrcaSlicer. |
| Connection check fails with a timeout or connection refused | The address in the preset is wrong, or the printer is on another network. Use the printer's current IP. |

Not supported: Anycubic Cloud and access from outside the LAN, a G-code console (the printer's LAN
protocol has none), and other Kobra models.
