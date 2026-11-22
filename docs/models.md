# Anycubic models

Which Anycubic printers Kobra Control drives, how it tells them apart, and where each fact comes from. The table in
code is `src/kobracontrol/profiles.py`; this page explains it.

## How the model is known

The printer names its model when Kobra Control logs in: the decrypted `/ctrl` answer carries `modeId` (the model
code) and `modelName`. The model code is also part of every MQTT topic
(`anycubic/anycubicCloud/v1/printer/public/<modeId>/<deviceId>/...`), so Kobra Control already talked to whatever the
printer said it was. A printer that sends no `modeId` is taken for a Kobra X, as before.

The model decides:

- the highest nozzle and bed temperatures the page and OrcaSlicer's Device tab let you set, and the clamp in the
  plugin itself (`service.cmd_set_temp`);
- whether a refused MQTT login means "another app holds the printer" (one-client printers, below);
- whether a file sliced for another printer gets the "sliced for another printer" warning;
- the model OrcaSlicer is told about (Device tab, printer agent).

A model code that is not in the table connects **read-only**: status and files show, but heating, moving, feeding,
drying and printing are refused with a message that names the code. Pause, resume and stop stay available, so a print
started elsewhere can still be stopped.

## The table

| Model | Code | LAN on stock firmware | Nozzle / bed max | Bed (mm) | Feeder | Camera | One client | Status |
|---|---|---|---|---|---|---|---|---|
| Kobra X | 20030 | yes | 320 / 120 | 260 x 260 x 260 | head feeder box (-1) + ACE | `/live/<token>` | no | verified, firmware 2.0.2.8 |
| Kobra 3 / Combo | 20024 | yes (firmware 2.3.3.9 and later) | 300 / 110 | 255 x 255 x 260 | ACE | `:18088/flv` | yes | experimental |
| Kobra 3 V2 | 20027 | yes | 300 / 110 | 255 x 255 x 260 | ACE | `:18088/flv` | yes | experimental |
| Kobra 3 Max | 20026 | yes (inferred) | 300 / 90 | 426 x 420 x 501 | ACE | `:18088/flv` | yes | experimental |
| Kobra S1 / Combo | 20025 | yes | 320 / 120 | 250 x 250 x 250 | ACE | `:18088/flv` | yes | experimental |
| Kobra S1 Max | 20029 | yes (firmware 2.6.9.6, 2.7.1.4) | 350 / 120 | 350 x 350 x 350 | ACE | `:18088/flv` | yes | experimental |
| Kobra 4 | 20028 | yes (listed by anycubic_ha_local) | 300 / 100 | 260 x 260 x 260 | ACE | `:18088/flv` | yes | experimental |
| Kobra 2 Pro / Plus / Max | 20021 / 20022 / 20023 | no | 260 / 110 | 220 / 320 / 426 | none | none | – | not over the LAN |

"Experimental" means: same LAN protocol by every public source, never tried with Kobra Control. The page shows a
notice on these printers and asks for testers.

Not covered: the Kobra 2 Neo, the original Kobra, Kobra Go, Vyper and other Marlin printers have no network protocol
Kobra Control could use.

## One client at a time

The Kobra 3 and Kobra S1 families accept one LAN MQTT client at a time (anycubic_ha_local and Printer Tools notes).
When Anycubic Slicer Next, Home Assistant, Kobralink or another OrcaSlicer is connected, the printer refuses the login.
After three refused logins in a row Kobra Control says which app is the likely cause and stops retrying on a timer; the
**Retry** button tries again. The Kobra X accepted two clients at once on the owner's printer, so it keeps retrying as
before.

## Sources

- Model codes: anycubic_ha_local `custom_components/anycubic/anycubic_local/const.py` and Rinkhals `tools.sh`
  (both list 20021 to 20030).
- Bed sizes: Anycubic Slicer Next's own machine profiles (`printable_area`, `printable_height`).
- Temperature maxima: Anycubic's published specifications (store pages and wiki). The Kobra X keeps Kobralink's
  320 / 120 (`packages/shared/src/control.ts`), because its machine profile sets none. The Kobra 2 values are the
  cloud's `temp_limit` for a Kobra 2 Pro.
- Payloads for the tests (`tests/test_models.py`): the Kobra 3 info report from Rinkhals `docs/firmware/mqtt.md`
  (firmware 2.3.5.3), the Kobra S1 Max reports from anycubic_ha_local `tests/fixtures` (firmware 2.6.9.6). Addresses
  and ids are replaced.
- Camera: Rinkhals and anycubic_ha_local report `http://<printer>:18088/flv` as `rtspUrl` on the K3 and S1;
  `camera_url_for` already follows whatever URL the printer reports.

## What a tester should check

For each experimental model, in this order (nothing below moves or heats the printer unless you click it):

1. The tab connects and shows the right model name, firmware and temperatures.
2. The ACE slots show the right materials and colours (no head feeder box on these models).
3. The camera turns on.
4. The temperature fields stop at the limits in the table.
5. Print a small file from the Files tab, then from OrcaSlicer's Print button with the kobracontrol printer agent.
6. Pause, resume and stop a print.
7. With Anycubic Slicer Next open and connected to the printer, Kobra Control shows the "takes one app at a time"
   message instead of retrying.

Open an issue with the model, firmware and what happened, and the plugin log lines that start with `kobracontrol:`.
