# Brand and image set prompt

This prompt made the vector set: the symbol, the tab icon, the feature icons, the diagrams and the install cards.
The README heroes, the Orca Cloud images, the store tile and the social preview no longer come from it: they are the
pictures in `assets/marketing/source/` (prompts and hashes in `assets/marketing/asset-manifest.json`), finished by
`scripts/marketing_images.py`; see [release.md](release.md).

Paste the prompt below into an image model (ChatGPT with image generation or similar). Ask for the
assets one at a time if it tries to cram everything into one image. Ask for SVG code for the mark,
wordmark, icons, diagrams and anything with text, so they stay sharp.

Where each asset goes in this repo:

| Asset | File |
|---|---|
| Symbol / app icon | `assets/kobracontrol-icon.svg` (and `.png`) |
| Tab icon (24x24) | `src/kobracontrol/ui/icon.svg`, replaced in 0.7.1 by the brand tile (`src/kobracontrol/ui/icon.png`, 40x40) |
| Feature icons | `assets/features/feature-*.svg` |
| How it works diagram | `assets/diagrams/how-it-works-{light,dark}.*` |
| Works with Spooler | `assets/diagrams/kobracontrol-works-with-spooler-{light,dark}.*` |
| Install steps | `assets/install/kobracontrol-install-0{1..4}.*` |

Deliverables 4, 8, 10 and 11 of the prompt (hero, store frames, social images and store tile) are kept below as
written, but their files were replaced.

## All Anycubic printers (2026-11-24)

Kobra Control drives more than the Kobra X (the Kobra 3 family, S1, 4 and, through Anycubic Cloud, the Kobra 2
Pro/Plus/Max), so the nine English pictures in `assets/marketing/source/` were edited again: the printer is a generic,
unbranded Kobra-family printer with a filament box (no Anycubic, Kobra X or ACE markings), and every line that named
the Kobra X names Anycubic instead. The Portuguese pictures and the tile were left as they were. Each picture was an
edit of its previous version, made with this prompt (`<LINE>` per picture below; the exact text of each is the
`exact_prompt` of its entry in `asset-manifest.json`):

```text
EDIT the attached image (an approved software marketing banner). Generate exactly one image with the same aspect
ratio as the attached image.

Edit instructions:
1. <LINE>
2. Replace the 3D printer and the filament box with a photorealistic generic Anycubic Kobra-family style desktop FDM
printer, same position and similar size: white and light-grey open-frame bed-slinger with a single upright gantry, a
moving build plate carrying the same multicolour printed ship, a small tilted touchscreen on the base, a top spool
holder with spools, next to a black multi-spool filament dryer box with a smoked lid and four coloured spools. The
machines carry no visible text, no model names, no badges, no letter marks and no logos at all: clean plain panels.
Keep unchanged: the app tile and the product name, every other line of copy exactly as it is now, the background,
theme, lighting, the six colour tiles bottom-left, the signature, and the large rounded EMPTY panel on the right at
exactly the same size and position with its thin border and perfectly uniform flat interior colour (no UI, no text,
no objects inside, nothing overlapping it). No extra words, no watermark, no other brand logos, no people.
```

| Picture | `<LINE>` |
|---|---|
| cover, main-square, social-preview, hero-dark, hero-light | Replace the small grey scope line under the headline with exactly this text, same font, size, colour and position: "Status, files, camera and print for Anycubic printers." (EXACT, verbatim, no extra characters). Ensure it appears once, perfectly legible and correctly spelled. |
| feature-01-lan | Replace the small grey line under the headline with exactly this text, same font, size, colour and position: "Prepare and send work to your Anycubic printer." (EXACT, verbatim, no extra characters). Ensure it appears once, perfectly legible and correctly spelled. |
| feature-02-status, feature-03-ace, feature-04-files | Keep every line of copy exactly as it is; change no text at all. |

---

```text
You are a senior brand designer. Create an original brand identity and image set for
"Kobra Control", an open-source plugin for OrcaSlicer (a 3D-printing slicer). The repository
name is "kobracontrol".

WHAT IT DOES AND FOR WHOM
Kobra Control connects OrcaSlicer 2.5+ directly to the Anycubic Kobra X, a multi-colour
3D printer fed by a filament box (ACE), over the local network. No cloud. It registers a
printer agent, so OrcaSlicer's own Print and Send dialogs and its Device tab work with the
printer: status, temperatures, pause, resume, stop, light, fan, speed, the filament slots,
camera. It also adds a "Kobra Control" tab with a dashboard, ACE slots (feed, retract,
drying), camera, files, and Spoolman spool tracking. The TLS client certificate is bundled,
so it connects out of the box. Audience: hobbyist and prosumer makers who
self-host tools. Personality: precise, calm, direct, "it just works". Not corporate, not
toy-like.

CONCEPT DIRECTION
Original. Express a direct link between slicer and printer: for example several coloured
filament strands from a multi-colour filament box converging into one nozzle, or two
endpoints joined by one straight line. Do NOT use a snake or cobra, and do not imitate the
logos, colours or icons of Anycubic, OrcaSlicer, Bambu Lab, Kobralink or Spoolman. The
printer may appear only as an abstract box with a nozzle, never as the real printer's
industrial design.

HARD CONSTRAINTS
- Flat vector, strictly geometric, 8 px grid, consistent stroke weights. No photorealism,
  no 3D, no glow, no noise, no AI-art texture, no people or robots, no invented UI.
- The symbol must stay recognisable at 16x16 px and 20x20 px.
- Must work on dark and light backgrounds, and in one colour.
- Text in images must be spelled exactly "Kobra Control" for the wordmark and "kobracontrol"
  for the repo name (lowercase). No other words unless I give them.
- Fonts must be free and open (Google Fonts); name them. Convert text to paths in SVG
  unless I say "live text".

PALETTE (family palette, use these values, do not invent others)
Primary (teal accent): #79d8c7 on dark, #00675b on light.
Dark: background #181c22, surface #222831, text #edf1f5, muted #b6c0cd, border #566273.
Light: background #f5f6f8, surface #ffffff, text #202731, muted #526171, border #ccd3dc.
Status (only where a state is shown): danger #b42318 light / #ffaaa4 dark; warning #805300
light / #f3cc70 dark; success #0b6b3a light / #7fdbab dark.
Filament accents, if the symbol uses several strands: pick 3 or 4 distinct hues that stay
clear of the teal, and state their hex codes. Check that every text and background pair
reaches WCAG AA contrast.

DELIVERABLES (each as its own image, exact sizes, transparent background unless stated)
1. Symbol / app icon, full colour, 1024x1024 on a rounded-square tile (corner radius about
   22%), tile colour from the palette. Also as clean SVG code: viewBox 0 0 256 256, no
   embedded raster, no external fonts, no scripts.
2. Symbol, single colour white on transparent, 1024x1024, plus SVG code.
3. Tab icon: monochrome line icon on a 24x24 grid, 1.5 px strokes, round caps and joins,
   no fills thicker than the stroke, readable at 20 px. SVG code with width="24"
   height="24" viewBox="0 0 24 24", stroke="#FEFEFE", fill="none".
4. README hero, 1600x640, two versions (background #181c22 and #ffffff): left the lockup,
   the line "Anycubic Kobra X control for OrcaSlicer" and the line
   "Direct LAN printing · ACE slots · Camera · Files · Spoolman"; right an empty rounded
   16:10 frame, thin border, labelled nothing (a screenshot goes there).
5. Feature icons, seven 96x96 tiles (rounded square, tinted palette background, no text),
   one SVG each, consistent. In this order, saved to these files:
   direct LAN printing (`assets/features/feature-direct-lan.svg`), Device tab
   (`feature-device-tab.svg`), ACE slots and drying (`feature-ace-slots.svg`), camera
   (`feature-camera.svg`), files (`feature-files.svg`), Spoolman (`feature-spoolman.svg`),
   secure local connection (`feature-secure.svg`).
6. How it works diagram, 1600x900, live text, light and dark. Boxes and arrows, left to
   right: "OrcaSlicer 2.5" -> "kobracontrol" -> "Kobra X". On the side, "Spoolman" and
   "Spooler (optional)" linked to "kobracontrol". Arrow labels exactly: "print & status",
   "ACE slots", "spools", "filament profiles". Footer: "Local network only · no cloud".
7. Works with Spooler, 1600x700, live text, light and dark: two lockup cards side by
   side, "kobracontrol" (our symbol) and "Spooler" (empty square frame, I will drop
   Spooler's own logo in), joined by a link glyph. Footer: "Spooler is optional.
   kobracontrol works on its own."
8. Orca Cloud store frames: five images, 1600x900 each, live text, headline and sub-line
   on the left 40%, an empty rounded 16:10 frame (thin border) on the right 60%:
   "Direct LAN printing" / "Print to the Kobra X from OrcaSlicer's own dialogs.";
   "Device tab" / "Status, temperatures and controls for the Kobra X.";
   "ACE slots" / "Filament slots, feed, retract and drying.";
   "Spoolman built in" / "Spools and usage next to the printer.";
   "Files and camera" / "Browse printer files and watch the print."
   Plus the main image (1600x900) and a square crop (900x900): lockup centred, the line
   "for Anycubic Kobra X · OrcaSlicer 2.5+". Each file under 2 MB.
9. Install steps, four cards 800x500, live text, same template: big step number in the
   primary colour, title, one line, empty rounded screenshot frame (bottom 60%):
   1 "Install" / "File > Plugins > Install local plugin, then Activate."
   2 "Turn on agents" / "Preferences > Developer > Experimental > Use printer agents."
   3 "Pick the agent" / "Set Printer Agent to kobracontrol in your printer preset."
   4 "Print" / "Press Print in OrcaSlicer."
10. Social images: (a) wide 1200x675, (b) square 1080x1080, (c) vertical 1080x1350 with the
    seven feature icons in a grid. Lockup, the line "Anycubic Kobra X control for
    OrcaSlicer" and the line "Free and open source".
11. Plugin store tile, 512x512: the app icon with generous padding on a palette background.

OUTPUT FORMAT
For every deliverable: the image, then (where asked) the SVG code in a code block, then one
line on how it is meant to be used. For each image also list the text strings present, the
hex codes used and the contrast ratios of text. Finish with a short brand guide: clear
space, minimum sizes, colour usage, and three things never to do with the logo.
```

## Screenshots

Any UI screenshot inside these images is a real render of the built page (`node ui/tests/page/shots.mjs`), not
generated art. The image model must not draw fake UI. Wherever a screenshot belongs (hero, store
frames, install cards, social images), leave a clearly marked empty rounded frame, with a thin
border and no content, at the stated position and 16:10 ratio, so the renderer can place the real
page there.
