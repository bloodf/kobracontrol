# Changelog

All notable changes are listed here, in the [Keep a Changelog](https://keepachangelog.com/) format.

## [Unreleased]
### Added
- **Check everything.** Settings > Requirements has one button that checks every connection and permission Kobra Control depends on: the printer on the network, its login, the Anycubic certificate, OrcaSlicer's printer agents, Spoolman and Anycubic Cloud. Each shows as works, problem or not set up, and each problem says in plain words what to do. Where OrcaSlicer's permission is what is missing (the printer's address or Spoolman's), **Allow** shows OrcaSlicer's dialog right there and checks again, so there is no hunting through menus after an update. The printer is only asked for its status: nothing pauses, moves, heats or feeds. Asked for by Er_Nando_Blando.

### Changed
- **Smaller Dashboard alerts that stay closed.** Each alert is one line, with **Details** to read the rest, and closes with one click. A closed alert stays closed while its problem lasts, also when a status poll briefly clears it; a new or different problem shows again. "The printer is printing" stays closed for the session once closed, as its reasons change with the print's phases. Errors (printer unreachable, Spoolman bookings that failed) open with their full text and actions. Reported by Er_Nando_Blando.
## [0.12.4] - 2026-11-24
### Changed
- **Spooler reads the ACE slots from Kobra Control instead of connecting to the printer itself.** Kobra 3 and S1 printers accept one LAN connection at a time, so with both plugins on the same printer one of them kept losing it ("Can't reach the printer" in Spooler during prints). Kobra Control now lists the printers it is connected to, with their ACE and spool holder slots, in the presence file it already shares with Spooler; Spooler 0.33.4 and later shows those slots and leaves the printer to Kobra Control. Reported by @Er_Nando_Blando.

## [0.12.3] - 2026-11-24
### Fixed
- **Switching between two Anycubic printer presets switches printers.** With a printer connected, picking another preset still announced the first printer to OrcaSlicer, so the Device tab and Print stayed on it until OrcaSlicer restarted. The selected preset's own address now comes first. Reported by @antonyoatec (#82).
- **A preset's new address wins over the one remembered for it.** A preset saved as a copy while connected to one printer kept that printer even after its address was changed to another one. Kobra Control now remembers the preset's address together with the printer and stops using the old printer once the preset's address changes. Addresses remembered by older versions work as before. Reported by @antonyoatec (#82).
- **Stopping a print no longer shows "Stop print failed".** Some Kobra X firmware answers a stop that worked with code 10601 ("user initiated"); Kobra Control showed that as a refusal and kept the alert. It now counts as a stop, and the print shows as cancelled, not as an error. Reported by Er_Nando_Blando.
- **Spoolman is asked for once, when OrcaSlicer starts.** Kobra Control never asked OrcaSlicer for access to Spoolman (its own or the one Spooler uses), so booking filament use failed with "audit permission required". The Spoolman address in use is now remembered and requested with the printer's at the next start: restart OrcaSlicer once after updating and allow it. Reported by Er_Nando_Blando.
### Changed
- README: how to give a preset its printer's address when OrcaSlicer hides the print host button, and why to leave **Settings > Printer address** blank with more than one printer.

## [0.12.2] - 2026-11-23

### Fixed
- Opening a slot's preset choices no longer expands its card and dashboard row. The choices float above or below the preset line, stay inside the viewport, and scroll when needed.

### Added
- Stock inventory can be grouped by material, manufacturer or location, with collapsible groups, spool counts and remaining-weight totals. Search and spool linking work inside each group.

Version 0.12.1 was held before Orca Cloud publication. This release includes its fixes below. Reports of disappearing spools, unavailable printing and texture-plugin conflicts remain unresolved pending affected-session logs.

## [0.12.1] - 2026-11-23

### Fixed

- **All seven filament sources reach OrcaSlicer's sync with their own presets.** The Device tab's filament presets (Spooler's, from `profiles.json`) are read by the status thread itself instead of waiting for OrcaSlicer's UI thread, so a delayed or stale refresh no longer leaves slots on the Generic preset. A unit's slots are numbered by the index the printer reports for them, not by their place in the report, so a shuffled report keeps each spool, tray and print slot together.
- **The preset's Change button stays inside each filament card.** With four ACE columns or three holders the score and **Change** ran out of the narrow card; they now wrap inside it.
- **The spool picker's search is fuzzy.** Type part of a brand, a name or a material in any case, with or without accents, or just its letters in order ("pmat" finds "Polymaker Matte"). An id ("12" or "#12") finds only that spool, not #120.

## [0.12.0] - 2026-11-22

### Added

- **See and change the preset each slot reports.** Each slot card shows the OrcaSlicer preset the slot is reported as in OrcaSlicer's Device tab (the one its sync from AMS loads), with a score and the reasons (material, manufacturer, made for this printer), and marks it when another preset fits better. **Change** picks another preset for that material and remembers it for what the slot holds (its Spoolman spool, else its RFID tag or SKU, else its manufacturer and material); **Automatic** forgets it. A preset linked in Spoolman still comes first, then your pick, then Spooler's, then the Generic one. Picks are kept in `matches.json`, shared with Spooler and U1 Control when Spooler is installed.
- **Open Filament Database presets (off by default).** Turn on **Open Filament Database** in Settings > Spoolman and a slot card's **Change** list also offers the community presets from the [Open Filament Database](https://openfilamentdatabase.org) for the slot's manufacturer and material, marked "OFD, untuned". Picking one installs it: through Spooler when Spooler is installed and the slot has a Spoolman spool, otherwise into Kobra Control's own preset bundle (`kobracontrol_ofd`), never into your own presets. The slot then reports it, so OrcaSlicer's sync from AMS loads it instead of "Generic PLA". The list is read at most once a day and kept for offline use; while the option is off Kobra Control never contacts OFD.
- **Kobra prints in Spooler's history.** Each print Kobra Control books in Spoolman is also listed in `kobracontrol/prints.json` in OrcaSlicer's data folder (the last 200), so Spooler 0.33.0 and later show them in its print history and Stats tab. The filament use is still booked once, by Kobra Control.

### Changed

- Shared Orca UI foundation 5.10.0. Internal: the filament matching code is now shared with Spooler and U1 Control; presets are picked exactly as before.

## [0.11.0] - 2026-11-21

### Added

- **More Anycubic printers over the LAN (experimental).** Besides the Kobra X, Kobra Control now drives the Kobra 3, Kobra 3 V2, Kobra 3 Max, Kobra S1, Kobra S1 Max and Kobra 4, which use the same LAN mode. The printer says which model it is when Kobra Control logs in. Only the Kobra X has been tried with Kobra Control so far: the page marks the other models "experimental" and asks for testers. The list, the limits and their sources are in [docs/models.md](docs/models.md).
- **Temperature limits follow the model.** The highest nozzle and bed temperatures you can set, in the tab and in OrcaSlicer's Device tab, are the printer model's own (a Kobra 3 bed stops at 110 °C, a Kobra S1 Max nozzle at 350 °C). The plugin enforces them itself too.
- **An unknown model is read-only.** A printer that reports a model code Kobra Control has no profile for shows its status and files, but heating, moving, filament and printing stay off, with a notice that names the code. Pause, resume and stop still work.
- **"Another app holds the printer".** The Kobra 3 and Kobra S1 families accept one app at a time over the LAN. When one of them keeps refusing the login, Kobra Control now says that Anycubic Slicer Next, Home Assistant or Kobralink is probably connected and waits for **Retry** instead of trying again forever.
- Printer presets for all of these models are recognised: the address hint, the setup hints and the G-code preset checks work for a Kobra 3 or Kobra S1 preset as they do for a Kobra X one, and a file sliced for another model gets the usual warning.

- **Anycubic Cloud, opt-in (experimental).** For printers without a LAN mode (the Kobra 2 series) or kept on Anycubic's cloud: turn on Settings > Anycubic Cloud, sign in with the account Anycubic Slicer Next is signed in to (found in its logs) or a pasted token, and choose the printer. The tab and OrcaSlicer's Print then show its status and print, pause, resume and stop through Anycubic's servers. Before every order Kobra Control reads the printer and its job again and refuses when that order no longer fits. Over the cloud nothing heats, moves or feeds, and pause and resume ask first. The sign-in is kept in `cloud.json` in the plugin's storage folder, readable only by you, and never logged. This uses Anycubic's unofficial app interface: Anycubic can change or block it, and it may be against Anycubic's terms. The README and SECURITY.md say what goes where. Parts are ported from OrcaCubic and Bob-41's anycubic-plugin (both MIT; see NOTICE.md). It has not been tried on a real printer yet.

### Changed

- **A new default Dashboard layout.** On the left, the print, then the filament slots, then the console; on the right, the controls, then the temperatures over the printer's facts beside the camera over the moves. A Default layout you never arranged gets it; layouts you saved stay exactly as you saved them.
- The README and SECURITY.md no longer promise "no cloud": Kobra Control still talks only to your printer and Spoolman unless you turn Anycubic Cloud on.
- Texts say "the printer" or "an Anycubic printer" where they used to say "Kobra X". The printer agent is now called "Anycubic (kobracontrol)"; its id stays `kobracontrol`, so existing printer presets keep working. The script **Check Kobra X connection** is now **Check printer connection**.

## [0.10.2] - 2026-11-21

### Fixed

- **ACE slots no longer vanish a few seconds after they show.** Kobra Control asks the printer for its ACE every 5 seconds, and some firmware (seen on 1.1.5.1) sometimes answers without it; each such answer wiped the slots ("The printer reports no filament slots", "Print head only, no ACE connected"). An answer with no boxes now changes nothing, as in KX-Bridge and Kobralink.
- **A report about one box or one slot no longer hides the others.** A printer report that names only the ACE, only the spool holder or only one edited slot updated that much and dropped the rest, so the Filament widget could show one filament while the ACE held four. Each report now updates the boxes and slots it names and keeps the rest.

### Changed

- **Setting up the upload bridge is quicker.** The Dashboard's "The Kobra X doesn't speak OctoPrint" notice now also offers the other way out, keeping the OctoPrint physical printer and pointing it at Kobra Control, with a button to the upload bridge's settings. There the address (`127.0.0.1:8765`) has a **Copy** button next to the API key's.
- The README and the Orca Cloud listing say step by step where the plugin list (**Plugins**) is on each system and that **Activate** is the first column of the plugin list, and how to turn the plugin off or remove it. The Portuguese README gets the OctoPrint answer.

## [0.10.1] - 2026-11-21

### Changed

- Shared UI 5.6.2.

### Fixed

- **Send no longer overwrites the file being printed.** Sending a plate under the name of the file the printer is printing (or has paused) is refused and nothing is uploaded, as the upload bridge already did.
- **A jog no longer runs twice.** When another command held the queue and the page had already said a move's outcome is unknown, the late move still ran after the next one. A move that waited longer than the page does is now dropped, and nothing is sent.
- A temperature report that leaves out a target no longer shows that heater as off while it heats.
- A light report without a brightness, or a refused light command, no longer resets the light to off at 80 %.
- A finished feed reported without a slot number is no longer acknowledged as slot 1.
- An ACE slot reported with a negative number no longer stops OrcaSlicer's Device tab from updating.

## [0.10.0] - 2026-11-21

### Added

- **7 filament sources: the spool holder and the ACE.** When the printer reports its spool holder (the print head's own feeder, next to the ACE), its 3 positions show beside the ACE's 4 slots, grouped as **ACE 1** and **Spool holder** on the Filament widget, the Stock tab and the print setup. OrcaSlicer's Device tab and Print dialog get them as two units named the same way, the ACE first (A1-A4), the holder after it (B1-B3), and a print sends each filament to the right place on the printer: holder position n is print slot n, ACE slot n is print slot 4 + n. A slot's number (its Spoolman location "S<n>") is now the same as OrcaSlicer's tray and Spooler's: ACE 1-4, spool holder 5-7.
- **Your own dashboard.** **Edit layout** on the Dashboard: drag a widget to move it, drag its edges or corners to resize it (it snaps to the grid and keeps a sensible least size), remove it, or add one from the list of every widget: Status, Filament, Controls, Temperatures, Camera, Move, Printer, Console and a Files shortcut. Widgets with settings have a gear: the camera's picture shape, how many console lines show, which readings the Temperatures widget shows. The keyboard works too: arrow keys move a widget, Shift and the arrow keys resize it, Delete removes it. **Save layout** keeps it. Make named layouts, switch between them, rename, delete or reset one to the default. They are saved in Kobra Control's settings, so they come back after a restart. Each widget fits its content to its size: the camera keeps its shape, a taller console shows more lines, a small Temperatures widget is compact. The camera and the console can be maximised. A narrow window shows the widgets in one column.
- **The default dashboard in two halves**, as on U1 Control: the print over the filament on the left; the controls over the temperatures and the printer's facts beside the camera and the moves, on the right; the console across the bottom. Denser slot cards (a smaller spool beside the name, tighter spacing), the print head's three slots and an ACE's four on one row where there is room. Rows now grow to fit their content, so nothing is cut off at any window width and both halves always end level. A Default never arranged gets this layout; arranged layouts stay exactly as saved. Shared UI 5.6.0.
- **Console** widget, in the default layout: what the page sent to the printer, what came back (errors marked) and the printer's state changes, newest last. The Kobra X takes no typed G-code, so there is nothing to type.
- **Setup hints on the Dashboard.** A Kobra X preset that does not use the kobracontrol printer agent yet gets the two steps to print from OrcaSlicer's own Print and Send (with **Don't show again**). A Kobra X preset set up as an OctoPrint physical printer is called out: the Kobra X has no OctoPrint server, so OrcaSlicer only says "Could not connect to OctoPrint".
- The README says where **Activate** is after subscribing on Orca Cloud, and answers the OctoPrint and Stock tab questions.

### Changed

- Shared UI 5.6.1.
- Shared UI 5.4.0 (the dashboard grid).
- Shared Orca UI foundation 5.0.8 (Vue 3.5.46, lucide-static 1.77.0); no visible change.

### Fixed

- A job from OrcaSlicer goes to the printer it names (the print's printer address, as OrcaSlicer's **Multi-device** tab sends it), not to the printer the agent is connected to.
- The ACE and the spool holder are asked for every 5 seconds, as KX-Bridge and Kobralink do, not only when Kobra Control connects. A Kobra X on firmware 1.1.5.1 showed "The printer reports no filament slots" with 4 spools in its ACE; a printer that answers the first request without its ACE now shows the slots as soon as it reports them.
- **The Stock tab no longer waits for ever on "Waiting for Spooler's stock list…".** Released Spooler versions share their stock list only with U1 Control, so the tab never got one. When Spooler shares no list (not installed, stopped, or such a version), the tab now lists the spools straight from Kobra Control's Spoolman (the one set in Settings, or the one Spooler uses) and says so; linking a spool to a slot works the same. Without any Spoolman address it says what to set instead of waiting.
- **Spools no longer vanish a few seconds after opening the tab.** When OrcaSlicer selected the printer (a device or preset event), the page asked the plugin again and cleared the Spoolman spools; the new read was refused while the first one was still out, and the first one's answer was dropped, so the list stayed empty until the next refresh. The spools now stay for the same printer and are cleared only for another one.
- **Print and Send find the printer on OrcaSlicer 2.5.x.** The printer agent now announces the selected preset's printer as soon as OrcaSlicer starts it, under the id OrcaSlicer looks for (`host:port`), and at once rather than queued. Before, a Kobra X preset with no printer address had no printer in the Device tab, and an address once saved under another printer agent (an OctoPrint physical printer, a Moonraker preset) stayed hidden from kobracontrol, so Print could not find the printer although the tab and the camera worked.
- **Retract is offered only where it acts.** The printer unloads the filament in the print head whichever slot is asked, so with one slot loaded, Retract on another slot unloaded the loaded one while the question named the other. Retract is now only on the loaded slot (any slot that holds filament when none is loaded), and a screen reader says why it is off elsewhere.
- **A print sent with no tray chosen books its grams on the right spool.** OrcaSlicer prints from the highest loaded slot when a filament's own slot is empty; the usage was booked only for a filament whose number matched a loaded slot, so a one-colour print from a single spool in slot 3 booked nothing.
- An ACE that leaves out each slot's number no longer has its slots addressed as 5-8 when loading, unloading or editing the second ACE; a slot is numbered by its place in the unit.
- A slot colour reported with fractions no longer breaks the print setup and the Stock tab.
- A project whose slice info holds an infinite number no longer fails to open in the print setup.
- **Settings says when a value was not saved.** A Spoolman address that is not http:// or https:// (or a bridge port out of range) was dropped while Settings said "Saved". Now nothing is saved and Settings says which setting is not valid.
- After switching printers, a status from the printer before the switch no longer shows for a moment.
- The printer connection no longer drops and reconnects for ever when OrcaSlicer has more than 1023 files and sockets open.
- Reading a file's details while the file list refreshes can no longer fail with "dictionary changed size during iteration".

## [0.9.2] - 2026-11-20

### Fixed
- A Kobra X found on the network is no longer connected to or remembered until you choose it. Before, opening a Kobra Control tab could connect by itself to the only Kobra X on the network, even with another printer's preset selected, and save its address and certificate. Now the tab lists the printer with **Use this one** (or **Allow and use** when OrcaSlicer must allow the address first), and OrcaSlicer's network dialog appears only after that click.
- A printer's address is remembered only for a printer preset whose Printer Agent is kobracontrol. Under another agent's preset (a Snapmaker U1, for example) the printer you choose is used for that session, and an address saved there by an earlier version is no longer used.
- Deleting one file or time-lapse no longer says "They are removed from the printer". The confirmation now reads "Deleting from the printer can't be undone." in every language.
- Activating the plugin no longer makes OrcaSlicer ask for the Python audit event "open" with no file named. The tab icon module is now loaded with the plugin, so OrcaSlicer no longer sees a write to its Python cache without a path, which it can only show as a permission prompt with no target.
- The upload bridge saves its key and the uploads it receives through file paths, so OrcaSlicer can show which file a prompt is about.

## [0.9.1] - 2026-11-20

### Changed
- The page ships in the plugin as a plain `kobracontrol/app.html` file next to the code, instead of a compressed, base64-encoded block inside a Python file. Nothing changes in OrcaSlicer.

## [0.9.0] - 2026-11-19

### Changed
- New look, on the shared Orca UI foundation 5.0.7: the pages use OrcaSlicer's own greys and its teal for the
  main action, and the plugin's violet is left for its mark and the line under the open tab. Colour now only says
  something: an icon's subject, a state, a level, a heater's phase, a filament's own colour.
- Dashboard: the printer's name, address and firmware are the page's first line, with **Rename**. The print is one
  compact block across the top with the small printer picture, the percentage, the times and its actions. Only the
  actions that apply are shown: **Pause** while it prints, **Resume** while it is paused, none with no print; **Stop
  print** is outlined red and still asks first. Under it, the filament slots and one **Controls** module (Temperature:
  nozzle and bed; Machine: fan, speed mode, light); beside them the camera, **Move** and the **Printer** panel.
- A slot card is neutral, with a thin strip of the filament's colour across its top. Level bars are green, amber when
  low and red when almost empty.
- The camera keeps a 16:9 box whether it is off, starting, failed or live, so turning it on no longer moves the page.
- Why a control is off is said once, in one banner under the page header ("The printer is printing. Moves are
  available while the printer is idle or paused. ..."), instead of in a line under each module. What a module needs
  explained is behind its (i).
- The README and Orca Cloud pictures show the new look, in English and Brazilian Portuguese. The README's Dashboard
  picture shows the whole page.

### Added
- **Stock** tab: Spooler's spool stock left the Dashboard for its own tab, with the spool count on it. Choose the slot
  once on the left (every slot, with the spool that is in it), then **Link to Slot N** on a spool's row; a spool already
  in that slot reads **Linked**. Every link still checks the spool in Spoolman and asks first. The spool chooser in each
  slot card stays on the Dashboard.
- **Files** is a file browser: select one file or several (click, the checkboxes, Shift and Ctrl/Cmd, Ctrl/Cmd+A, the
  keyboard), and **Delete** removes the selection in one go after one question that lists the names. Sort by any
  column; the list opens newest first. One selected file shows its picture, details, the slot of each filament and the
  print options, with **Start printing**.
- Time-lapses are a second list in the same browser (**Print files** | **Time-lapses** over the table), with the same
  multi-select and **Delete** (the printer takes one video per message, so they go one after the other). If only
  some could be deleted, it says how many are left, and those stay selected.
- The Kobra X has no folders to file prints in and no way to move or rename a file over the local network, so the Files
  tab shows no folder tree and no **Move to**. A switch over the list changes between the printer's two lists, **Print
  files** and **Time-lapses**. `docs/protocol.md` lists what the printer's file messages allow.
- In a narrow window the details of the selected file sit under the list and scroll in their own share of the height,
  so the list stays on screen.
- A file list that could not be read says so in place of the table, with **Try again**; it is never shown as an empty
  list. The printer is asked for its files when the Files tab is opened, and for the time-lapses when their list is.
- Print setup window: why an option is locked, and what Auto feed does, are behind an (i) in the option's box.
- The camera shows the whole picture, with bars at the sides when it is not 16:9, instead of cropping it.

### Removed
- The per-row **Print** and **Delete** buttons of the Files tab (select the file instead) and its sort menu (use the
  column headers).

### Fixed
- A spool assigned to an ACE slot in Spooler now shows in Kobra Control without reconnecting: the tab re-reads
  Spoolman every 30 s while it is visible (Settings > Spoolman > **Refresh Spoolman every**: 10 to 300 s, or off),
  and at once when Spooler says it changed a link. Hidden, it pauses; after failed reads it waits longer, up to
  5 minutes, and says "Spoolman unreachable, retrying". A link made in Kobra Control shows in Spooler's open tab at
  once.
- A printer renamed in Kobra Control's Settings now links with Spooler both ways: Kobra Control reads the
  printer-model location Spooler writes, and tells Spooler the name it uses.

## [0.8.1] - 2026-11-19

### Fixed
- The print setup window no longer opens blank on Windows when the plate image is large; it opens without the
  picture.

## [0.8.0] - 2026-11-18

### Changed
- Settings is split into pages: a list of pages beside the open one, or in a narrow window the list first and one page
  at a time with a Back button. Settings opens on the page you used last, and a page that needs attention is marked in
  the list. Every "Open Settings" link opens the page it is about (Connection, Camera, Spoolman, Requirements), and the
  print setup's "Plugin settings" opens Print defaults.

### Fixed
- The spool picture shows how much filament is left. An ACE slot without a Spoolman spool is drawn at the percentage
  the ACE reports (before, it was drawn at a made-up level). A loaded slot with no known amount shows a full reel in its
  colour with a small "?" badge, so it no longer looks like an empty slot, which keeps the bare reel. The print setup's
  slot picker also draws each slot as a spool at its level (Spoolman's, else the ACE's) and reads the amount out to
  screen readers.

## [0.7.1] - 2026-11-18

### Added
- **Upload bridge** (opt-in, off by default): OrcaSlicer's OctoPrint host type (Upload, Upload and Print) reaches
  the Kobra X through Kobra Control on 127.0.0.1. Every request needs an API key the plugin makes (Settings, with
  Copy, New key and the OrcaSlicer steps). Upload and Print never starts by itself: the tab shows the waiting print
  with Start and Don't print, and refuses while the printer is busy. Loopback only, rate and size limited.

- **Kobra Control — print setup.** When you press Print in OrcaSlicer's dialog for a Kobra X, a Kobra Control window
  opens before anything is sent. It starts from OrcaSlicer's choice, so it works as a second confirmation step.
  - The window shows:
    - the print task's name, which you can edit and which becomes the file name on the printer;
    - the plate with its time and filament use;
    - one chip per filament, with the slot it prints from;
    - the printer with its state and slot colours, and a button to read the slots again;
    - the print options as checkboxes: auto-leveling, vibration compensation, time-lapse, flow calibration and ACE
      auto feed;
    - "Remember these options for this printer";
    - Cancel and Start print.
  - A filament's chip opens a row of spool discs, one per slot, each showing its colour, material and linked Spoolman
    spool. You can only choose a slot with the same material family. A different kind in the same family (PLA in a
    PLA Silk slot) needs "Use these slots anyway", and a different colour is pointed out. Slots are matched by
    material and colour when OrcaSlicer's choice can't be used.
  - What you leave in the window is exactly what is sent. Cancel sends nothing, and the window gives up after 15
    minutes.
  - A "Plugin settings" link switches the Kobra Control tab to Settings.
- Settings > Print defaults: "Show print setup before sending" (on by default) and "Remember these options for this
  printer".
- The camera in the Kobra Control tab no longer needs `ffmpeg`. The plugin reads the printer's video stream
  (H.264 in FLV) and the page plays it with the webview's own video player, at the printer's full 1280x720 and
  10 fps. Playback was checked with a recording of a real Kobra X stream in Chrome (as in WebView2 on Windows)
  and in WebKit (as on macOS); Linux has not been tried. It reconnects when the stream drops and follows the
  printer when the stream address changes. `ffmpeg` is now optional: it is only used for an RTSP stream or
  when the webview can't play H.264 (possible on Linux without the GStreamer codecs).
- **G-code checks before sending.** OrcaSlicer's Print and Send through kobracontrol read the plate's G-code first
  (only its first 1 MB and last 256 kB, never changing it) and warn when the settings block at its end is missing or
  when it has no PNG preview picture. The Kobra X screen probably reads the filament and print details and the
  picture from those blocks. The warning, an OrcaSlicer notification, names the setting to change (Skip G-code config
  block, G-code thumbnails); the Print dialog's last line points to it. It never stops the print. Check Kobra X
  connection names the same settings when the selected Kobra X printer preset has them, read on OrcaSlicer's main
  thread. New texts in all six languages. See `docs/setup.md`, section 7. Checked with the repository's tests and sample G-code files; not tried on
  a Kobra X.
- **Settings > Requirements** lists what Kobra Control needs and can't install itself: ffmpeg (the tab's camera),
  Anycubic Slicer Next (optional, only for Find certificate), OrcaSlicer's "Use printer agents instead of print
  hosts" (Print, Send and the Device tab) and Spoolman (optional, spool links). Each row says whether it was found,
  what needs it and how to install it on macOS, Windows and Linux, with a Check again button. The check runs once
  on a thread of its own after the tab opens and again only on Check again or a Settings save.
- Polish (pl) translation. Thanks to @xtronets for asking (u1control#20).
- A Spoolman spool (or its filament) can name your own OrcaSlicer filament preset in the extra field `orca_filament_preset`. When it is a standalone user preset compatible with the printer, the Device tab reports its `filament_id`, so OrcaSlicer's sync from AMS loads it for that ACE slot; a preset that inherits from another can't be loaded by sync and keeps the usual preset. A name that isn't one of your compatible presets shows a notice once.

### Changed

- The plugin icon is the new brand tile: the Kobra Control tab in OrcaSlicer shows the purple tile instead of the
  old line drawing.
- With the print setup turned off, OrcaSlicer's choice is used as before. A filament sent to a slot of another
  material is now refused there too.
- Spools are drawn with the photo spool again.
- The page fills the whole tab at every height, also after the window is resized: no more grey under a short page.
- Settings are tabs: one section at a time, and the save bar stays on screen at any window height.
- Notifications appear bottom-left and each one can be closed; warnings and notices on the page can be dismissed.
- Notifications wait while OrcaSlicer is in another tab or app; errors stay until closed. A closed warning comes back when
  its problem clears and later returns, and a closed out-of-date warning stays closed while the status stays out of date.
- The README, its Portuguese version and the Orca Cloud description show what was verified on the printer, with the
  firmware and the date, and what the plugin can access: each OrcaSlicer permission, what is sent where, and that
  there is no telemetry.
- The status card shows a photo of the Kobra X in place of the small printer icon. Its four spools take the colour
  of the Spoolman spool linked to each slot (bands for a multi-colour spool), else the colour the ACE reports, and an
  empty slot shows a bare reel; the wound texture stays. The feeding slot and its tube glow and the toolhead display
  shows its number. Screen readers hear each slot's colour and material. Printer photo: Anycubic product image.
- Without ffmpeg the camera is not started at all (it used to look for ffmpeg every second while on), and if ffmpeg disappears mid-session the camera stops after one report: its button is
  off with the reason. Without an Anycubic Slicer Next install, Find certificate searches only a path typed in.
  Without Spoolman, refreshing and linking spools are off.

### Fixed
- Publishing to Orca Cloud: the wheel carries the 1.1 MB page compressed (zlib + base64), as Spooler does, instead of as readable text in a Python file. Orca Cloud's automated permission review timed out repeatedly on U1 Control 0.12.1, which shipped its page that way. The wheel now holds 1.2 MB of Python instead of 1.8 MB; the page, the icon and everything the plugin does are unchanged.
- OrcaSlicer's "sync from AMS" no longer turns every ACE slot into "Generic PLA". The Device tab sent an empty filament id for every tray, because OrcaSlicer's plugin API doesn't show a preset's `filament_id`, and OrcaSlicer reads an empty id as Generic PLA. A ACE slot linked to a Spoolman spool now reports the id of that spool's Spooler preset (from Spooler's `profiles.json`; Spooler's presets are standalone copies now, which OrcaSlicer's sync can load), so sync loads that preset. Any other loaded ACE slot reports the Generic preset of its real material, also for materials such as "PLA+", "PETG HF". The links are read from Spoolman when the printer connects, so this works without opening the tab.
- The camera stayed on "Starting the camera…" after Turn on when "Turn the camera on when the page opens" was off
  (the default): that option also blocked the camera itself. It now only decides whether the page turns the camera
  on by itself.
- OrcaSlicer could fail to start, or crash, after Kobra Control was installed and a Kobra X printer preset was
  edited: the plugin read the printer preset while OrcaSlicer was still loading its presets. It now reads only its
  own files while loading and asks about the preset's printer address later, once OrcaSlicer is up.
- OrcaSlicer could close by itself at start-up, or while the Device tab was open, if one of the status updates
  Kobra Control hands to it failed. Such a failure is now written to the log and OrcaSlicer keeps running.
- The README and setup guide name the OrcaSlicer preference by its real label, "Use printer agents instead of
  print hosts", and say to restart OrcaSlicer after ticking it.

### Notes

- The safety rules stay:
  - Flow calibration and time-lapse can only be on when their Kobra Control setting is on.
  - Auto-leveling is locked off while its setting is off.
  - While the printer is busy, the window says that settings can't change during a print, and Start print stays off.
  - The plugin checks the slots and the confirmed warnings again before it sends.
- OrcaSlicer has no hook to replace its own Print dialog (SelectMachineDialog), so the user sees two dialogs:
  OrcaSlicer's first, then Kobra Control's.
- The purge and bed-wait add-on is not part of this release.

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
