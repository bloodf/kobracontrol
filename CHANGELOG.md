# Changelog

All notable changes are listed here, in the [Keep a Changelog](https://keepachangelog.com/) format.

## [0.2.0] - 2026-11-14

The first release. The plugin is in development.

### Added

- A printer agent with the id `kobracontrol`, so OrcaSlicer's own Print and Send dialogs and its
  Device tab work with the Anycubic Kobra X: status, temperatures, pause, resume, stop, light, fan,
  speed, ACE slots as filament slots, and the camera.
- Direct LAN connection to the printer: HTTP on port 18910 and MQTT over mutual TLS on port 9883.
  Standard library only.
- A "Kobra Control" tab with Dashboard (status and controls, camera, ACE card, Spoolman, Spooler
  stock), Files and Settings pages.
- ACE card: slots with colour and material, feed, retract, auto-feed and drying.
- The Anycubic Slicer client certificate (a shared identity, the same in every Anycubic Slicer Next
  install) is bundled with the plugin and the wheel, so the plugin connects without a setup step.
  "Find certificate" still finds the copy in the user's own Anycubic Slicer Next install, or a file
  the user picks, and that saved copy overrides the bundled one.
- Plugins > Run scripts "Check Kobra X connection" and "Find Anycubic certificate".
- Spoolman and Spooler integration, shared with the sibling plugin u1control.
- `docs/brand-images-prompt.md`, a prompt for the logo and image set, and a placeholder icon.

### Added (audit, tests only: not yet tried on the printer)

- Files page: search by name and sort by newest, oldest, name or size.
- Print panel of a printer file: estimated time, layers, filament, layer height, temperatures and
  nozzle from the printer's file details, and the ACE slot that will print each filament. It warns
  when that slot holds another material, when a filament has no loaded slot, or when the file was
  sliced for another printer, and the print confirmation repeats the warning.
- Dashboard: the clock time a running print should finish.
- The printer's TLS certificate fingerprint is remembered per address and shown in Settings; a
  different one later is logged and shown on every tab as a warning. The connection is never refused
  for it (SECURITY.md).

### Fixed

Found by running the plugin against a real Kobra X (firmware 2.0.2.8).

- Reply matching: the printer acknowledges a request on `response` and answers on `<type>/report`
  with its own message id, so a request now settles on the matching report. Commands report
  confirmed, refused by the printer, or received without a result.
- Print start: `filepath` is now the folder `/` with `filename` separate. The old `/<name>` made the
  printer end the task with code 10111.
- A task the printer ends itself (`stoped` with a code other than 0 or 200) is shown as an error,
  and print start waits a few seconds to catch it.
- Job phases (heating, levelling, wiping, ACE feeding and others) are read as part of the running
  print; progress and times keep their last values meanwhile. `getSliceParam` reports no longer
  change the print state.
- Homing waits for the printer's answer, which comes when homing has finished.
- ACE drying: the remaining time is read as minutes; the reported duration is not used.
- Camera: the Device tab stream mode follows the URL scheme, so the printer's HTTP-FLV URL works.
- File details are matched to the requested file; file list timestamps are read as milliseconds.
- The printer file name from a job name no longer keeps a `.gcode.3mf` suffix.

Found in a code audit (tests only, not yet tried on the printer):

- A multiColorBox report whose box, slot or feed/drying status is not an object no longer stops the
  status updates; a bad slot reads as empty at its own position. Numbers such as `1e999` read as absent.
- The Device tab's status updates no longer stop for the session after one failed update.
- Switching the Device tab to another printer closes the connection to the previous one.
- Printing a file already on the printer from OrcaSlicer passes vibration compensation and reports the
  finished stage.
- A bundled certificate that cannot be loaded (and no saved one) is reported as a missing certificate
  with the Find certificate prompt, not as an unexpected answer from the printer.
- Settings show the certificate source actually in use: a saved copy that does not load is not "saved".
- The Device tab's unload with nothing loaded is refused with a plain reason, not "slot 0 does not exist".
- The camera no longer starts a capture thread on a session that was replaced a moment before.
