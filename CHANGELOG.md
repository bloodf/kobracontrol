# Changelog

All notable changes are listed here, in the [Keep a Changelog](https://keepachangelog.com/) format.

## [Unreleased]

### Added

- **G-code checks before sending.** OrcaSlicer's Print and Send through kobracontrol read the plate's G-code first
  (only its first 1 MB and last 256 kB, never changing it) and warn when the settings block at its end is missing or
  when it has no PNG preview picture. The Kobra X screen probably reads the filament and print details and the
  picture from those blocks. The warning names the OrcaSlicer setting to change (Skip G-code config block, G-code
  thumbnails), shows in the Print dialog's last line and as an OrcaSlicer notification, and never stops the print.
  Check Kobra X connection names the same settings when the selected Kobra X printer preset has them. See
  `docs/setup.md`, section 7. Checked with the repository's tests and sample G-code files; not tried on a Kobra X.

### Changed

- The README, its Portuguese version and the Orca Cloud description show what was verified on the printer, with the
  firmware and the date, and what the plugin can access: each OrcaSlicer permission, what is sent where, and that
  there is no telemetry.

## [0.7.0] - 2026-11-16

Kobra Control speaks Spanish, German and Simplified Chinese, next to English and Brazilian Portuguese. Checked
against the repository's tests and screenshots of the page in all five languages; the new translations have not
been reviewed by native speakers yet.

### Added

- **Español, Deutsch and 简体中文** for the whole tab: Dashboard, ACE slots and drying, Print Assist, the Printer
  panel, the Files tab and its time-lapses, Settings, confirmations, tooltips, empty states and screen-reader labels.
  Words follow OrcaSlicer's own translations where it has one.
- The texts OrcaSlicer shows for the Kobra X outside the tab are translated too: the Print dialog's progress
  ("Uploading G-code...", "Print started"), the plugin's errors and notices, and the results of the Check connection
  and Find certificate scripts.
- The language follows OrcaSlicer's automatically (Traditional Chinese reads Simplified Chinese; a language the
  plugin doesn't have reads English). Settings > Language can still pick one by hand.
- Numbers, temperatures, sizes, durations, dates, lists and plural counts are written the way each language writes
  them (for example "1.234,5 g" in German, "1 小时 5 分钟" in Chinese).

### Changed

- The README (now also in Portuguese, `README.pt-BR.md`), the Orca Cloud description
  (`docs/orca-cloud-description.md`) and the listing, social and README images were redone. The images carry real
  screenshots of the page and are rebuilt with `scripts/marketing_images.py`. `docs/release.md` describes a release
  and the listing.
- Deleting a time-lapse was confirmed on a Kobra X (firmware 2.0.2.8); it is no longer listed as untried.
- Printer names, file names and firmware texts are shown exactly as the printer gives them, in every language.

### Fixed

- In Brazilian Portuguese, the delete button in the Files list no longer gets cut off by the Print button next to it.
- A decimal typed or pasted into a number field (temperature targets, fan, drying temperature and time) no longer
  loses its decimal sign: "22.5" was read as 225, in every language. Now "22.5" and "22,5" both read as 22.5, and
  temperatures and times are rounded to whole numbers as before.

## [0.6.0] - 2026-11-16

The Files tab shows the printer's time-lapse videos and can delete them. Checked against the repository's test
fakes, page tests and screenshots. Reading the list was checked on a Kobra X (firmware 2.0.2.8); **deleting a video
has not been tried on a Kobra X yet** (see "Not yet tried on the printer" below).

### Added

- A **Time-lapses** section in the Files tab, under the file list: each video with the print it belongs to, when it
  was recorded, its length and its size, newest first. Refresh reads the list again.
- **Delete** on each video. It asks first, naming the print and the date, and the list is read again afterwards.
- A print that was stopped before anything was recorded leaves an empty video on the printer; it is listed as
  "Empty" and can be deleted like the others.
- The section shows for a connected printer, idle or printing: listing and deleting videos does not touch the
  running print.

### Not in this version

- **Downloading a video.** The printer has no known way to hand a video over the local network, so there is no
  Download button; the section says so. The cover picture of each video can't be fetched either, so a video icon
  stands in for it.

### Not yet tried on the printer

- `file/deleteVideo` with `{path: "/", filename}`, as Anycubic Slicer Next names its fields. If the printer refuses
  it, the page shows the printer's answer and the video stays in the list.

## [0.5.1] - 2026-11-16

### Fixed

- When reading the printer's details and Print Assist switches fails (say a print started at that moment), the
  Printer panel asks again the next time the printer is idle. Before, it gave up until the page was reloaded.
- A Print Assist report with an option or value like "--3" is no longer misread; only plain whole numbers count.
- A plugin test that could fail on a heavily loaded machine now waits for the printer's reported state instead of
  depending on timing.

## [0.5.0] - 2026-11-16

Printing from OrcaSlicer gets the options Anycubic Slicer Next offers, and the Dashboard gets a Printer panel with
the printer's details and its Print Assist switches. Checked against the repository's test fakes, page tests and
screenshots. **None of the new printer messages has been tried on a Kobra X yet** (see "Not yet tried on the
printer" below), so the new print options are **opt-in and off by default** in Settings > Print defaults.

### Added

- **Flow calibration** and **Time-lapse** print options, off by default because they are untested on the printer.
  Turn them on in Settings > Print defaults. Once on there, OrcaSlicer's Print dialog choice is used: its Flow
  Dynamics Calibration now shows for the Kobra X, and Timelapse can be ticked when the printer reports it has a
  time-lapse camera. While the setting is off, the plugin sends both as off whatever the dialog says (the dialog
  starts with both ticked for a printer it has not seen before).
- The Files tab's print options add Flow calibration and Time-lapse, shown only when the printer reports them and
  starting from the Print defaults. The confirmation names every option.
- A **Printer** panel on the Dashboard: the printer's name with Rename, its firmware, its network (MAC) address, and its
  total print time, number of prints and filament used. A counter the printer does not report is left out, never
  shown as 0. These are read once per connection, when the printer is idle; nothing new is asked during a print.
- **Print Assist** switches in that panel: filament break alert, filament jam alert, auto feed, remaining filament
  detection, belt detection and lost step recovery. Only the switches the printer reports are shown; auto feed
  changes every ACE at once. Each change asks first and is possible only while the printer is idle; so is Rename
  (up to 32 bytes: fewer letters with accents).

### Changed

- **Vibration (resonance) compensation now applies to prints sent from OrcaSlicer.** OrcaSlicer's Print dialog has no
  such option and always sent it as off; the Settings > Print defaults switch (on by default) is now used for those
  prints as well. This field was already sent by earlier versions from the Files tab.
- **Auto-leveling for OrcaSlicer prints also follows Settings > Print defaults.** It runs when both the Print dialog's
  Bed Leveling and the setting (on by default) are on, so turning the setting off now keeps OrcaSlicer prints from
  levelling too. With the default setting nothing changes.
- Setting the part fan while a print runs still sends the fan command that was checked on the printer, then also
  sets the fan through the print's own settings, as Anycubic Slicer Next does.
- Turning the camera light on uses full brightness (it was 80 %), and off sends brightness 0, as Anycubic Slicer Next
  does.

### Not yet tried on the printer

These come from Anycubic Slicer Next 2.0.0.3 and from Kobralink and KX-Bridge, not from our own Kobra X.

- Print options (opt-in): `flow_calibration` and `timelapse` (`{status, count: 0, type: 64}`) in `print/start`.
  What a printer does with them when they are on is not known yet.
- OrcaSlicer's status push: the flow calibration bit and `support_timelapse`, which make the Print dialog offer them.
- Printer details, read only while idle: `info/net` (network address) and `info/statistic-query` (print time, prints,
  filament used). A firmware that does not answer them shows less in the Printer panel.
- Writes: `info/setPrinterName` (Rename) and `properties/write` of `assistant_settings` (Print Assist), after a
  `properties/read`. If the printer does not answer a write, the page says it was sent and the next status shows the
  printer's value; what an unknown answer does to the printer is not known.
- The second fan message during a print (`print/update` `fan_speed_pct`) and light brightness 100 / 0.

## [0.4.1] - 2026-11-16

### Fixed

- The list of recently checked filament uses shows again whenever there is one; 0.4.0 only showed it inside Review,
  which needs at least one unconfirmed use.
- Choose objects says why it is off when Stop print still works, and the button points screen readers at that reason.
- The page has one main landmark holding the three tabs, instead of one per tab.
- Eleven unused texts were removed from the English and Portuguese messages; a test now fails on any unused text.

## [0.4.0] - 2026-11-15

A new look for the Kobra Control tab, on the interface shared by the Orca plugin family. Checked against the
repository's page tests and screenshots in Chrome; not yet tried in OrcaSlicer's own web view.

### Changed

- The tab has a violet top bar with the plugin's mark, the printer's connection state and its address, and the
  Dashboard, Files and Settings tabs, each with an icon. Panels have coloured headers by subject: heat in orange,
  motion in blue, camera in light blue, filament in magenta, Spoolman and stock in green.
- The print is the page's main block: a drawing of the Kobra X with its four spools in their real colours, the
  file, a large percentage, the progress bar, and elapsed, left and finish time. Pause, Resume, Choose objects and a
  red Stop print sit under it. A printer that stopped answering keeps its last values, in grey, with their age.
- Temperatures, fan, speed mode and light are rows of one "Temperature and air" panel. Each heater shows its
  reading in the colour of what it is doing (heating, at target, cooling), its target and a small chart of the
  last ten minutes.
- Move has a jog pad (X/Y with home in the middle, Z), the step as one segmented control, Home XY, Home Z and
  Motors off.
- The camera is one row while it is off, so it no longer pushes the printer's state down.
- Each filament slot is a card that opens with the filament's colour, then a drawn spool showing how much is left,
  the amount and its bar, the Spoolman spool it books on (the picker that was in the separate Spoolman card), and
  Edit, Feed and Retract. Auto-feed sits by each ACE's name; drying is one strip with its temperature, time left
  and humidity.
- Spoolman and Spooler's stock are one panel: where the spools come from and Refresh, then the stock list with
  search, material filter, "same material as the slot", the slot to link to, drawn spools and level bars.
- Filament use that Spoolman did not confirm is one warning line with Review; the list and "I checked it in
  Spoolman" open from there.
- The first run (no printer found yet, or the certificate missing) is one panel with an illustration, the reason
  and the way out: Open Settings and Search again, the printers to choose from, or Find certificate.
- Files has search and sort in a toolbar and the print details beside the list on wide screens, with what the file
  needs, which slot prints each filament, and the auto-leveling and vibration compensation switches.
- Settings has a section index that follows the page, sections in two columns (Connection, Certificate, Print
  defaults, Camera, Spoolman, Language, About) and one save bar that names what changed, with Discard.
- One reason is said once: when the printer does not answer, is still connecting or is not found, one line under
  the top bar says why and offers the way out; disabled controls point at it instead of repeating it.
- Text is set in Manrope (embedded) and icons come from one shared set; the spool pictures are drawn instead of
  fifteen bitmaps, and the page is about 14 kB smaller.

## [0.3.0] - 2026-11-15

Checked against the repository's test fakes and page tests. How a real Kobra X (firmware 2.0.2.8) answers the
network search was measured on the printer; the plugin itself has not been tried in OrcaSlicer yet.

### Added

- The Kobra Control tab finds the printer by itself. With no address under Settings it tries the address found
  before for the selected printer preset, then the preset's own address if a Kobra X answers there, then searches
  the local network with SSDP (the search Anycubic Slicer Next sends; a Kobra X on firmware 2.0.2.8 answers it
  with an empty datagram, which is what the search looks for). A printer found at an address OrcaSlicer does not
  allow yet brings up OrcaSlicer's dialog once; Allow is the only click. One printer found is used and remembered
  per preset; several are listed once to choose from. A found address that stops answering is searched again, at
  most once a minute. When the preset's address is not a Kobra X (a Kobralink or Moonraker bridge, say), the tab
  says so in one line and uses the printer it found. Settings shows the address in use, how it was found, and
  Search again.
- The tab says once when the selected preset uses another printer agent (Kobralink's `moonraker`, say), and how to
  switch it to `kobracontrol`; the tab works on its own either way.
- With no Spoolman address set in Kobra Control, the one Spooler uses is taken, and Settings says so. An address
  set in Kobra Control always wins.
- `scripts/discover.py`: a read-only network search that prints what printers answer, with secrets masked.
- The printer found for a preset is remembered with its identity (`cn` from `/info`) and its TLS certificate
  fingerprint. It is used again only where both match; any other Kobra X, even the only one answering, is
  offered as "A different Kobra X answered at X. Use it?" and never taken by itself. The first connection to a
  printer found on the network names it (name, model, address).

### Changed

- The certificate is the built-in one, with no setup step: the plugin no longer asks at load for read access to
  Anycubic Slicer Next's folders and never reads them on its own. Settings shows "Certificate: built in"; using
  the copy from your own Anycubic Slicer Next install is an advanced option, and on macOS reads only
  `libcloud_mqtt.dylib`, so OrcaSlicer asks about one file.
- Saving a certificate no longer uses chmod or opens a file descriptor, which OrcaSlicer's audit cannot judge by
  path and blocked ("event=os.chmod reason=audit permission required").

### Fixed

- A change of the printer address in use is a printer switch: new generation, per-printer state reset, and
  commands queued for the old printer refused as stale. No search for the printer elsewhere while it was last
  seen printing or a print is tracked on it. Two presets can no longer be recorded for one printer.
- Closing the plugin while a network search runs no longer leaves a connection running afterwards.
- Changing the printer name or the Spoolman address in Settings no longer restarts the connection.
- The network search keeps only answers from port 1900, at most 4 per search. Kobra Control brings up
  OrcaSlicer's permission dialog by itself at most once per session (one new printer, none remembered); every
  other printer found is listed for you to pick, and an address that is not a Kobra X or was refused is not asked
  about again until Search again. If the dialog does not allow it, the tab says to allow the address and search
  again instead of waiting.
- The certificate fingerprint is kept per printer identity, so it follows the printer to a new address.
- Saving a certificate writes both files before replacing either, and removes its temporary files when a write
  fails; certificate pins are written through a unique temporary file.
- Filament use is not booked in Spooler's Spoolman when Spooler says it books Kobra X prints itself (Spooler 0.26
  never does). The Stock card says when Kobra Control uses Spooler's Spoolman because none is set here.
- Check Kobra X connection takes at most 20 s.
- When the known printer stops answering and another Kobra X answers, the tab keeps offering "Use it?" until you
  choose, instead of only showing the known printer's connection error.
- OrcaSlicer's Print, Send and Device tab check the certificate pin of a printer in the address book under its
  identity too; a different certificate is logged and shown there, not refused (the address is the user's own).
  When the tab then uses that remembered printer, a session that is already open must have presented the pinned
  certificate, or it is closed at once and offered as a different printer.
- An address where something answers but port 18910 refuses at once (a Kobralink bridge, say) is reported as
  "something answers at this address but it is not a Kobra X in LAN mode", with where the address came from and
  what to check, and every attempt follows the growing delay.
- Badge, banner, Status card and camera show one connection state; the banner says when the next automatic try
  is. While the printer is not connected every printer control is off, including the jog step buttons, and the
  camera gives the same reason instead of "Select a printer first".
- Saving Settings tries the connection again at once with a fresh retry delay; a new address stops the old
  address's connection.
- Stock table: the spool pictures are fixed 40 px squares that never set the row height, rows stay compact at any
  width (a narrow page scrolls the table sideways in its own area), and nothing runs onto the note below.
- The Spoolman card says "No Spoolman address" instead of "Spoolman: Spoolman not configured: ...".
- A printer that answers on its address but whose MQTT session cannot be opened no longer sends the tab into a
  loop. Each status the plugin publishes every second made the page say hello again, the hello cut the retry delay
  short, and the page went "Connecting" and back to "unreachable" every 10 s with a new connection attempt each time,
  forever. Now only Retry (and Find certificate or a print job) tries again at once; otherwise the attempts follow
  the growing delay of 2 s up to 60 s, the page shows one steady error, and Retry answers as soon as that attempt
  fails instead of after 10 s.
- The connection error says what failed: no answer on the MQTT port, the TLS/MQTT login timed out, the printer
  closed the connection during the login or right after it opened, the printer refused the login, or a TLS
  certificate problem.
- Find certificate says when OrcaSlicer refused to let the plugin read Anycubic Slicer Next's folder, instead of
  "no slicer files to scan".
- The Device tab's status pushes carry a `sequence_id`, so OrcaSlicer no longer logs
  "command_handle_response, error reponse." for each one.

## [0.2.0] - 2026-11-15

Fixes and features from a code audit. They were checked against the repository's test fakes and page
tests only and have not been tried on a printer yet.

### Added

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
- Find certificate pairs a certificate with its key whatever line endings the slicer's files use (CR,
  CR CR LF, blank lines inside a block); before, such a block was refused and no pair was found.
- The test suite runs on Windows: the camera tests wait for the fake stream instead of assuming its
  timing and check processes without sending Ctrl+C to the test runner; the certificate, MQTT and
  permission tests no longer assume LF files, POSIX descriptors or a private temp folder.

## [0.1.0] - 2026-11-14

The first release, published to Orca Cloud by hand. The plugin is in development.

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
