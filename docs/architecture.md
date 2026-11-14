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
| `connection.py` | One connection and one state per printer address, with the reconnect loop; certificate search | no |
| `jobs.py` | Print and Send: plate G-code streamed from the sliced `.3mf` to the printer, then print start | no |
| `service.py` | The connections, shared by the printer agent and the tab; command worker; monitor | no |
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

`service.py` owns the connections (`connection.py`). For a printer address it loads the saved certificate, recovers the
MQTT credentials from the printer (`kobra.fetch_credentials`; kept in memory only, never written to
disk), connects, subscribes and feeds every report into one `kobra.State`. The printer agent and the
tab are two consumers of that one connection and one state. The scripts use it too: the plugin
never opens a second MQTT session to a printer. When the connection drops the service reconnects
with a growing delay (2 s doubling to 60 s, reset only after a session has lasted 30 s), recovering
the credentials again each time.

On connect the plugin sends three status queries and nothing else. After that it polls status. The
one thing it sends without a user command is the "feed finished" acknowledgement the printer waits
for after a filament load or unload, as both upstream bridges do.

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

Every key of `kobra.State.view()` (see the docstring of `kobra.py`) except `file_details`; `upload_url`
is always empty, because it carries the upload token. Plus:

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
| `set_speed` | `mode`: 1 quiet, 2 standard, 3 sport; only while printing | |
| `move` | `axis` (`x`, `y`, `z`), `distance` (mm, signed, at most 50) | |
| `home` | `axes` (`xy`, `z` or `xyz`) | yes |
| `motors_off` | | yes |
| `objects` | | |
| `skip_objects` | `names` (each must be an object of the running file) | yes |
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
| `stock` | `refresh` (optional) | |
| `stock_assign` | `slot`, `spool_id`, `key` (the row's key from the `stock` reply) | yes |
| `usage`, `usage_ack` | the ledger of filament use still to be booked in Spoolman; no page surface yet | |

Replies:

| `cmd` | `result` |
|---|---|
| `files` | `{files: [{name, size, timestamp, thumbnail}]}`; storage is in `status.data.storage` |
| `file_details` | `{name, thumbnail}` (PNG data URL or `null`) |
| `file_print` | `{started: name}`; uses the automatic slot mapping from the loaded slots |
| `objects` | `{filename, objects: [name], skipped: [name]}` for the running print; an error when none runs |
| `find_certificate` | `{found, source}` |
| `spools` | `{spools, bindings}` |
| `stock` | the stock list plus `available` and `reason` (`null`, `absent`, `stale`, `waiting`, `unsupported`); rows carry `bound_slot` |

`stop` and `pause` run on their own short-lived thread so they never wait behind another command.
A command the printer state does not allow is refused by the service with a plain error, whatever
the page shows.

To add a command, write `cmd_<name>` in `service.py`, call it from the page with
`run({cmd: "<name>", ...})` (`ui/src/app/store.ts`), run `npm run build` in `ui/`, and add a test
that drives it against `tests/fake_kobra.py`.

## OrcaSlicer permissions

OrcaSlicer audits what plugin code does. Off the main thread it denies file reads that were not
granted and every temp-file creation, and it matches a `urllib` request by its full URL. The plugin
is written around that:

- It asks at load for: threads; read access to the trees where Anycubic Slicer Next is installed
  (`certs.grant_targets()`); read access to OrcaSlicer's own temp tree, where the sliced `.3mf`
  lives (`plugin.slicer_temp_root()`); network access to the printer addresses it already knows.
- It creates files only inside its storage folder. The certificate copy is in `<storage>/tls`
  (OrcaSlicer refuses folders named `cert`, `certs`, `config` or `secret`).
- Print and Send stream the plate G-code out of the `.3mf` straight to the printer; no temp file.
- All printer HTTP goes through `http.client`, so one grant of the printer's address covers the
  credential calls, the upload and MQTT.
- A printer address entered after load is not granted yet: OrcaSlicer shows its dialog on the first
  attempt, and the connection error says to allow it and retry.
- The tab's camera starts `ffmpeg`, which OrcaSlicer matches by its full command line.

`tests/audit_guard.py` models these checks so the tests run Print, Send, Find certificate and
connect under them. It is a model: only a real OrcaSlicer shows the real behaviour.
