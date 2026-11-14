# Brand and image set prompt

Paste the prompt below into an image model (ChatGPT with image generation or similar). Ask for the
assets one at a time if it tries to cram everything into one image. Ask for SVG code for the mark,
wordmark, icons, diagrams and anything with text, so they stay sharp.

Where each asset goes in this repo:

| Asset | File |
|---|---|
| Symbol / app icon | `assets/kobracontrol-icon.svg` (and `.png`) |
| Tab icon (24x24) | `src/kobracontrol/ui/icon.svg` |
| README hero, light and dark | `assets/readme/kobracontrol-hero-light.*`, `assets/readme/kobracontrol-hero-dark.*` |
| Feature icons | `assets/features/feature-*.svg` |
| How it works diagram | `assets/diagrams/how-it-works-{light,dark}.*` |
| Works with Spooler | `assets/diagrams/kobracontrol-works-with-spooler-{light,dark}.*` |
| Orca Cloud frames and main images | `assets/orca-cloud/*` (each under 2 MB) |
| Install steps | `assets/install/kobracontrol-install-0{1..4}.*` |
| Social images | `assets/social/kobracontrol-social-{wide,square,vertical}.*` |
| Main image and its 900x900 square crop | `assets/orca-cloud/kobracontrol-main.*`, `assets/orca-cloud/kobracontrol-main-square.*` |
| 512x512 store tile | `assets/orca-cloud/kobracontrol-tile.*` |

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
drying), camera, files, and Spoolman spool tracking. Setup finds a certificate in the
user's own Anycubic Slicer Next installation. Audience: hobbyist and prosumer makers who
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
   one SVG each, consistent: direct LAN printing, Device tab, ACE slots and drying,
   camera, files, Spoolman, certificate setup.
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
   2 "Find the certificate" / "Press Find certificate in the Kobra Control tab."
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
