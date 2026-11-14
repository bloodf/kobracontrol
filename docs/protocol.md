# Kobra X LAN protocol

What kobracontrol uses to talk to an Anycubic Kobra X on the local network. The knowledge comes from
[Kobralink](https://github.com/NatHacks/Kobralink) and
[KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release) (both GPL-3.0), which kobracontrol
credits. This page
lists facts only. Nothing here has been checked on a real printer yet, because the plugin is in
development.

The printer must have LAN mode enabled. There is no cloud path: Anycubic Cloud and access from outside
the LAN are not supported.

## Transports

| Port | Protocol | Use |
|---|---|---|
| 18910 | HTTP | Token, credential recovery, G-code upload |
| 9883 | MQTT 3.1.1 over mutual TLS | Status reports and commands |

## Credential recovery

1. `GET http://<ip>:18910/info` returns a token.
2. `POST /ctrl?ts&nonce&sign&did` returns an AES-128-CBC encrypted blob.
3. The decrypted blob holds the MQTT username, password, `deviceId` and `modeId`.

The Python standard library has no AES, so the plugin carries a small decrypt-only AES-128-CBC
(`aes.py`).

## TLS

- The MQTT broker requires a client certificate. The printer accepts only the certificate (subject
  `CN=AnycubicSlicer`) that Anycubic Slicer Next carries. kobracontrol does not ship it. It finds the
  certificate and key in the user's own Anycubic Slicer Next installation, or in a file the user
  picks, and keeps a copy in the plugin's storage folder.
- The printer's server certificate is self-signed and is not verified (see [SECURITY.md](../SECURITY.md)).
- OrcaSlicer's Python is 3.12 with OpenSSL 1.1.1w. The connection uses the cipher string
  `DEFAULT:@SECLEVEL=0`.

## MQTT topics

Publish to:

```text
anycubic/anycubicCloud/v1/{slicer|web}/printer/<modeId>/<deviceId>/<type>
```

Subscribe to:

```text
anycubic/anycubicCloud/v1/{slicer|web}/printer/public/<modeId>/<deviceId>/#
```

Message types: `info`, `status`, `print`, `tempature` (spelled this way by the printer),
`multiColorBox`, `light`, `fan`, `file`, `axis`, `skip`, `video`.

The printer has no G-code console channel, so kobracontrol has no console page.

## Printing

1. Upload the file: multipart `POST /gcode_upload?s=<token>`.
2. Start it: MQTT `print/start` with `filepath`, `ams_settings.ams_box_mapping` and `task_settings`.

`ams_box_mapping` carries the filament-to-slot mapping chosen in OrcaSlicer's print dialog.

## Camera

MQTT `video/startCapture` asks the printer to start the stream. The tab's camera needs `ffmpeg`
installed. The Device tab camera plays a URL the plugin returns, with OrcaSlicer's own ffmpeg.

## Credit

Protocol details come from Kobralink's `packages/kobra-protocol` and from KX-Bridge. See
[NOTICE.md](../NOTICE.md). kobracontrol is independent and is
not made or supported by Anycubic.
