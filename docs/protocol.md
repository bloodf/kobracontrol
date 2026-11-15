# Kobra X LAN protocol

What kobracontrol uses to talk to an Anycubic Kobra X on the local network. The knowledge comes from
[Kobralink](https://github.com/NatHacks/Kobralink) and
[KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release) (both GPL-3.0), which kobracontrol
credits. This page
lists facts only. Statements marked as observed were checked on a real printer running firmware
2.0.2.8; they are not claims about other firmware. The last section lists what is verified and what
is not.

The printer must have LAN mode enabled. There is no cloud path: Anycubic Cloud and access from outside
the LAN are not supported.

## Transports

| Port | Protocol | Use |
|---|---|---|
| 1900 (UDP multicast 239.255.255.250) | SSDP | Finding the printer on the network |
| 18910 | HTTP | Token, credential recovery, G-code upload |
| 9883 | MQTT 3.1.1 over mutual TLS | Status reports and commands |

## Finding the printer (SSDP)

Kobralink and KX-Bridge take the printer's IP from the user and have no discovery.

**Observed** on a Kobra X, firmware 2.0.2.8, 2026-11-15, with `scripts/discover.py` and hand-made searches
from a Mac on the same flat network:

- The printer answers every `M-SEARCH` with exactly **one empty UDP datagram** (0 bytes) sent from its own
  address: for `ST: ac:3dprinter:`, `ac:3dprinter:20030`, `ssdp:all` and `upnp:rootdevice`, sent to the
  multicast group or unicast to its port 1900, with `MX: 1` or `MX: 2`.
- It sent no `NOTIFY` during 40 s of listening on the group.
- Its `GET /info` answers with `cn`, `ctrlInfoUrl` (`http://<its own ip>:18910/ctrl`), `ctrlType` (`lan`),
  `deviceName` (`Anycubic Kobra X`), `deviceType` (`fdm`), `env`, `ip`, `modelId` (`20030`), `modelName`,
  `token` (32 characters), `usn` and `zone`.
- Other devices on the same network answer `ssdp:all` with ordinary `HTTP/1.1 200 OK` text replies.

From two other sources (not observed):

- Anycubic Slicer Next 1.x, `libssdplib.dylib` (strings in the binary, macOS): the search it sends is
  `M-SEARCH * HTTP/1.1`, `Host: 239.255.255.250:1900`, `ST: ac:3dprinter:{}`, `Man: "ssdp:discover"`,
  `MX: 5`, where `{}` is filled by the caller with a value not visible in the binary. Reading a reply,
  it looks for `ac:3dprinter:` and the fields `USN`, `modelId`, `ctrlType` (value `lan`) and `cn`; the
  slicer logs `cn={}, model={}, url={}`.
- [ianloic/anycubic-orca-plugin](https://github.com/ianloic/anycubic-orca-plugin) (AGPL-3.0, facts only,
  `anycubic_lan.py`), tested by its author on a Kobra S1 and a Kobra 3: it sends one `M-SEARCH` with
  `ST: ssdp:all` and `MX: 2`, listens 2.5 s and keeps replies containing `18910/info` or `ac:3dprinter`.

The reply came from the printer's port 1900. kobracontrol sends `ST: ac:3dprinter:` twice, 0.3 s apart, from the local address the system routes the
multicast group through, and listens 2.5 s; only when that finds nothing does it do the same with
`ssdp:all`. A sender is a candidate when it answers with an empty datagram (the Kobra X above) or with a
text reply containing `ac:3dprinter` or `:18910/`, from port 1900; any other text reply (a TV, a router)
is ignored and never probed. At most 4 senders are kept per search. It uses only the address the reply came from (never an address or URL inside it), only
when it is a private, link-local or loopback IPv4 address, reads at most 64 replies of at most 2048
bytes, and counts the sender as a printer only when its own `GET /info` answers with a LAN token.
`/ctrl` is always asked of that same address; a `ctrlInfoUrl` in `/info` is never followed.

## Credential recovery

1. `GET http://<ip>:18910/info` returns a token.
2. `POST /ctrl?ts&nonce&sign&did` returns an AES-128-CBC encrypted blob.
3. The decrypted blob holds the MQTT username, password, `deviceId` and `modeId`.

The Python standard library has no AES, so the plugin carries a small decrypt-only AES-128-CBC
(`aes.py`).

## TLS

- The MQTT broker requires a client certificate. The printer accepts only the certificate (subject
  `CN=AnycubicSlicer`) that Anycubic Slicer Next carries. It is a shared client identity, the same in
  every Anycubic Slicer Next install, so kobracontrol bundles it (`certs.bundled()`) in the package
  and the wheel. A copy found in the user's own install (Find certificate) overrides the bundled one.
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

Observed on firmware 2.0.2.8: two MQTT sessions coexist. Another client (Kobralink) stayed
connected the whole time, and each client sees the reports the other one causes. kobracontrol still
keeps one connection per printer.

## Requests and replies

Observed on firmware 2.0.2.8:

- Every request is acknowledged at once on `<deviceId>/response` with empty `type` and `action`,
  code 0 and the request's `msgid`. The ack only means "received".
- The answer arrives later on `<type>/report`, with a `msgid` the printer made, code 200, state
  `done` or `success`, and the request's action. `info/query` is answered with action `report`.
- The report topic is shared with other clients. kobracontrol settles a request on the first report
  of that type and action that arrives after it published, whoever caused it. A report that carries
  the request's own `msgid` always settles it.
- A request can end in one of three ways: confirmed (a successful report), refused (a report with
  state `failed` or a code other than 0 or 200), or received without a result (only the ack came;
  for example `print/query` on an idle printer).

## Printing

1. Upload the file: multipart `POST /gcode_upload?s=<token>`. The printer answers
   `{"code":200,"data":{"gcode":"<name>"},"message":"success"}`.
2. Start it: MQTT `print/start` with `filepath`, `ams_settings.ams_box_mapping` and `task_settings`.

`ams_box_mapping` carries the filament-to-slot mapping chosen in OrcaSlicer's print dialog.
`taskid` is `"-1"` for LAN jobs.

`filepath` must be the folder, `"/"`, with `filename` given separately. With `"/<name>"` the printer
ends the task with code 10111 ("abnormal end of task") about one second after the start. A start
report alone is therefore no proof that the print runs: kobracontrol watches `print/report` for a
few seconds after it.

### Job phases

During a job the printer reports its phase on `print/report` with action `start`: `checking`,
`printing`, `hotbed_heating`, `nozzle_heating`, `ace_filament_unfeeding`, `ace_filament_feeding`,
`nozzle_purging`, `nozzle_wiping`, `nozzle_cooling`, `auto_leveling`, `z_offset_calibrating`,
`frequency_sweeping`, `hotbed_cooling_off`, `nozzle_cooling_off` and `finished`. A phase other than
`printing` is preparation; kobracontrol shows the job as printing and keeps the last progress,
layer and time values, because the printer reports 0 meanwhile. `print/report` with action
`getSliceParam` is an answer to another client and is not a job state.

A job that the printer ends itself reports `stoped` with a code other than 0 or 200 (for example
10111); kobracontrol shows that as an error. `stoped` with code 200 is a cancel.

Before the first layer the printer cycled through all four ACE slots twice, about 11 minutes of
preparation for a 5 minute print. The plugin's `print/start` matches Kobralink's field for field
apart from `filepath`, and the G-code holds only the `G9111` start macro, so this is believed to be
firmware behaviour. It is not confirmed.

## Reports

Observed on firmware 2.0.2.8:

- `info/report`: `state` is only `free` or `busy`. `project` is null when idle and a dict during a
  job. `last_project` is not updated for LAN jobs. `features` holds `*_support` booleans.
- `urls.rtspUrl` is in fact an HTTP-FLV URL, `http://<printer>:18088/live/<token>`. It plays
  without `video/startCapture`.
- `multiColorBox/report`: box fields `auto_feed`, `drying_status` (`status`, `target_temp`,
  `duration`, `remain_time`), `humidity`, `temp`, `loaded_slot` and `model_id`; slot fields
  `brand_name`, `color`, `consumables_percent`, `material_name`, `status`, `type` and `weight`.
  `remain_time` counts minutes (measured). The reported `duration` (86400) is not used for display.
- `file/report`: `listLocal` timestamps are milliseconds. `fileDetails` data is
  `{root, filename, file_details{...}}`; the plugin matches it to the file it asked for, because other
  clients poll the same topic.

## Motion and heating

Observed on firmware 2.0.2.8:

- `axis/move` with `{axis: 5, move_type: 2}` homes X, Y and Z. It answers only when finished, after
  about 23 to 41 s; `info` state is `busy` meanwhile.
- Jog: `axis` 1 = X, 2 = Y, 3 = Z; `move_type` 1 = plus, 0 = minus.
- Heating when idle: `tempature/set` with `type` 2 and `target_nozzle_temp` / `target_hotbed_temp`.

## Camera

The printer announces the stream URL in `info/report` (`urls.rtspUrl`). On firmware 2.0.2.8 it is
an HTTP-FLV URL and plays without `video/startCapture`. The plugin sets the Device tab's stream mode
from the URL's scheme (`http`, `https` or `rtsp`). MQTT `video/startCapture` asks the printer to
start the stream. The tab's camera needs `ffmpeg` installed. The Device tab camera plays the URL the
plugin returns, with OrcaSlicer's own ffmpeg.

## Verified on a real printer

Checked on firmware 2.0.2.8, through the plugin's service layer outside OrcaSlicer: certificate
search, credentials, connect, status, ACE slots, file list, details, upload and delete, light,
camera stream URL, home, jog, idle heating, print from a `.3mf` with a slot mapping, finish
detection, and filament usage tracking of the job.

## Not yet verified

- On the printer: pause, resume, stop, filament feed and retract, drying start and stop, slot edit,
  skip objects, speed mode and Spoolman booking.
- Inside OrcaSlicer itself: nothing has been tested there. That covers the Device tab, the Print
  dialog, the permissions dialog and the Device tab camera with OrcaSlicer's bundled ffmpeg.

## Credit

Protocol details come from Kobralink's `packages/kobra-protocol` and from KX-Bridge. See
[NOTICE.md](../NOTICE.md). kobracontrol is independent and is
not made or supported by Anycubic.
