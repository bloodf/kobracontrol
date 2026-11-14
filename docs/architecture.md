# Architecture

kobracontrol ships as a pure-Python wheel, `kobracontrol_any.whl`, which OrcaSlicer loads as a
plugin. The sources live in `src/kobracontrol/`, and `scripts/build.py` packs them.

## Modules

| Module | Job | Uses `orca`? |
|---|---|---|
| `aes.py` | AES-128-CBC, for the printer's credential answer | no |
| `mqtt.py` | Minimal MQTT 3.1.1 client over TLS | no |
| `certs.py` | Finds, saves and loads the Anycubic Slicer client certificate; builds the TLS context | no |
| `kobra.py` | Credential recovery, printer commands, upload, print start, `State` (reports folded into one view) | no |
| `ace.py` | ACE and print-head slot model, slot mapping for a print, drying | no |
| `bambu.py` | Translates the view to the Device tab's status JSON and Device tab commands to printer commands | no |
| `camera.py` | Camera start and, for the tab, `ffmpeg` to JPEG frames | no |
| `files.py` | Printer file list, details, delete, print | no |
| `spoolman.py`, `peers.py`, `spooler_bridge.py`, `stockview.py`, `usage.py` | Spoolman, Spooler presence and stock, filament use | no |
| `settings.py` | Settings store | no |
| `service.py` | One connection per printer, shared by the printer agent and the tab; command worker; monitor | no |
| `plugin.py` | OrcaSlicer glue: printer agent, tab, scripts | yes |
| `ui/app.html` | The Kobra Control tab: one compiled Vue 3 + PrimeVue page, built from `ui/` | - |

Only `plugin.py` imports `orca`, so everything else is tested without OrcaSlicer.

## Capabilities

| Name | OrcaSlicer type | Where it shows |
|---|---|---|
| Anycubic Kobra X (kobracontrol) | Printer agent, id `kobracontrol` | Printer preset > Printer Agent; then Print, Send and the Device tab |
| Kobra Control | Pages | a tab next to Prepare / Preview / Device |
| Check Kobra X connection | Script | Plugins > Run |
| Find Anycubic certificate | Script | Plugins > Run |

## Connection

`service.py` owns the connection. For a printer address it loads the saved certificate, recovers the
MQTT credentials from the printer (`kobra.fetch_credentials`; kept in memory only, never written to
disk), connects, subscribes and feeds every report into one `kobra.State`. The printer agent and the
tab are two consumers of that one connection and one state. When the connection drops the service
reconnects with a growing delay, recovering the credentials again each time.

No printer traffic runs on OrcaSlicer's threads: the UI thread, the slicing thread and the agent's
callbacks only queue work and return.

## Page protocol

The page and the plugin exchange JSON through `orca.postMessage` and `post_message`.

Page to plugin:

| type | fields | effect |
|---|---|---|
| `hello` | `id` | resolve the printer, connect, send `config`; with no usable printer the error reply has `no_target: true`; with no certificate it has `no_certificate: true` |
| `lease` | `camera`, `stock` | keep status updates coming (renewed every 2 s, lapses after 6 s); camera on or off; `stock`: the Stock card is on screen |
| `cmd` | `id`, `cmd`, `args`, `gen` | run `Service.cmd_<cmd>(**args)` for printer generation `gen` |
| `frame_ack` | | the page has shown the last camera frame |
| `save_settings` | `id`, `settings` | validate and store settings |
| `ui_language` | `value` | store the page's language choice |

Plugin to page:

| type | fields |
|---|---|
| `reply` | `id`, `result` or `error` |
| `status` | `data` (below), `gen` |
| `frame` | `image` (JPEG data URL) |
| `camera_error` | `error`, `reason` (`no_ffmpeg`, `no_stream`, `failed`) |
| `config` | `settings`, `certificate` (`{found, source}`), `spooler`, `version`, `limits` (`{nozzle_max, bed_max}`) |
| `notice` | `text` |
| `offline` | `error` |
| `selection_changed` | |

### `status.data`

Every key of `kobra.State.view()` (see the docstring of `kobra.py`), plus:

| key | value |
|---|---|
| `mode` | `toolhead`, `ace_direct` or `ace_hub` (`ace.detect_filament_mode`) |
| `slots` | `ace.aggregate_slots` slots, each with `activity` filled, plus `tray` (`ace.tray_id`), `usable` (`ace.slot_usable_for_print`) and `spool_id` (bound Spoolman spool or `null`) |
| `loaded_slot` | `global_index` of the loaded slot, or -1 |
| `ace_units` | `ace.aggregate_ace_units` units: `{id, auto_feed, drying}` |
| `can` | `{pause, resume, stop, move, heat, feed, print}` booleans: what the printer state allows now |

### Commands

| `cmd` | `args` | Asks first in the UI |
|---|---|---|
| `connect` | | |
| `pause`, `resume` | | |
| `stop` | | yes |
| `set_temp` | `nozzle`, `bed` (either may be absent; 0 turns off) | yes when heating |
| `set_fan` | `pct` 0-100 | |
| `set_light` | `on` | |
| `set_speed` | `mode` (the printer's speed mode number) | |
| `move` | `axis` (`x`, `y`, `z`), `distance` (mm, signed) | |
| `home` | `axes` (`xy`, `z` or `xyz`) | yes |
| `motors_off` | | yes |
| `skip_objects` | `names` | yes |
| `slot_set` | `slot` (global index), `type`, `colour` (`#RRGGBB`) | |
| `slot_feed`, `slot_retract` | `slot` | yes |
| `auto_feed` | `ace` (unit id), `on` | |
| `dry_start` | `aces`, `temp`, `minutes` | yes |
| `dry_stop` | `aces` | |
| `files` | | |
| `file_details` | `name` | |
| `file_print` | `name`, `auto_leveling`, `vibration_compensation` | yes |
| `file_delete` | `names` | yes |
| `find_certificate` | `path` (optional file or folder) | |
| `spools` | | |
| `bind`, `unbind` | `slot`, `spool_id` | |
| `stock`, `stock_assign` | as in u1control, with `slot` in place of `head` | |

`stop` and `pause` run on their own short-lived thread so they never wait behind another command.
A command the printer state does not allow is refused by the service with a plain error, whatever
the page shows.

To add a command, write `cmd_<name>` in `service.py`, call it from the page with
`run({cmd: "<name>", ...})` (`ui/src/app/store.ts`), run `npm run build` in `ui/`, and add a test
that drives it against `tests/fake_kobra.py`.
