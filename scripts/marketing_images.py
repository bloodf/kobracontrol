#!/usr/bin/env python3
"""Finish the listing and README images: put a real screenshot of the built page into the empty panel of each
generated picture in assets/marketing/source/, export the listing sizes, and record every export in
assets/marketing/asset-manifest.json.

    python3 scripts/marketing_images.py

Needs Pillow (not a plugin dependency: `uv run --no-project --with pillow scripts/marketing_images.py`), Node and Chrome
(CHROME=... as for the page tests). The screenshots come from ui/tests/page/shots.mjs with its mock printer; nothing
here talks to a printer or the network.
"""

import datetime
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "marketing" / "source"
MANIFEST = ROOT / "assets" / "marketing" / "asset-manifest.json"
PAGE = ROOT / "src" / "kobracontrol" / "ui" / "app.html"
MAX_BYTES = 2_000_000          # the listing takes images under 2 MB
TOLERANCE = 24                 # how far a pixel may be from the panel colour and still count as the empty panel
SCALE = 2                      # device pixel ratio of the screenshots
LANDSCAPE, SQUARE, SOCIAL = (0.74, 0.47), (0.74, 0.56), (0.77, 0.47)   # a point inside the empty panel, per layout

# The picture inside each panel: (scene of shots.mjs, page width in CSS px). The page is rendered at the panel's own
# aspect ratio, so nothing is cropped away.
# store-status is one column at this width, with the camera moved up under the print (shots.mjs): the print and the whole
# camera picture fill the panel.
DASH, LAN, STATUS, ACE, FILES = ("store-dash", 845), ("store-lan", 800), ("store-status", 860), ("store-ace", 800), ("store-files", 800)

# (source in assets/marketing/source, point in panel, (scene, width), theme, language, export, size)
JOBS = [
    ("cover-en", LANDSCAPE, DASH, "dark", "en", "orca-cloud/kobracontrol-main-en.png", (1600, 900)),
    ("main-pt-BR", LANDSCAPE, DASH, "dark", "pt_BR", "orca-cloud/kobracontrol-main-pt-BR.png", (1600, 900)),
    ("main-square-en", SQUARE, ("store-dash", 520), "dark", "en", "orca-cloud/kobracontrol-main-square-en.png", (900, 900)),
    ("main-square-pt-BR", SQUARE, ("store-dash", 520), "dark", "pt_BR", "orca-cloud/kobracontrol-main-square-pt-BR.png", (900, 900)),
    ("feature-01-lan-en", LANDSCAPE, LAN, "dark", "en", "orca-cloud/kobracontrol-feature-01-lan-en.png", (1600, 900)),
    ("feature-01-lan-pt-BR", LANDSCAPE, LAN, "dark", "pt_BR", "orca-cloud/kobracontrol-feature-01-lan-pt-BR.png", (1600, 900)),
    ("feature-02-status-en", LANDSCAPE, STATUS, "dark", "en", "orca-cloud/kobracontrol-feature-02-status-en.png", (1600, 900)),
    ("feature-02-status-pt-BR", LANDSCAPE, STATUS, "dark", "pt_BR", "orca-cloud/kobracontrol-feature-02-status-pt-BR.png", (1600, 900)),
    ("feature-03-ace-en", LANDSCAPE, ACE, "dark", "en", "orca-cloud/kobracontrol-feature-03-ace-en.png", (1600, 900)),
    ("feature-03-ace-pt-BR", LANDSCAPE, ACE, "dark", "pt_BR", "orca-cloud/kobracontrol-feature-03-ace-pt-BR.png", (1600, 900)),
    ("feature-04-files-en", LANDSCAPE, FILES, "dark", "en", "orca-cloud/kobracontrol-feature-04-files-en.png", (1600, 900)),
    ("feature-04-files-pt-BR", LANDSCAPE, FILES, "dark", "pt_BR", "orca-cloud/kobracontrol-feature-04-files-pt-BR.png", (1600, 900)),
    ("social-preview-en", SOCIAL, ("store-dash", 616), "dark", "en", "social/kobracontrol-social-preview-en.png", (1280, 640)),
    ("social-preview-pt-BR", SOCIAL, ("store-dash", 648), "dark", "pt_BR", "social/kobracontrol-social-preview-pt-BR.png", (1280, 640)),
    ("hero-dark-en", LANDSCAPE, DASH, "dark", "en", "readme/kobracontrol-hero-dark-en.png", (1600, 900)),
    ("hero-dark-pt-BR", LANDSCAPE, DASH, "dark", "pt_BR", "readme/kobracontrol-hero-dark-pt-BR.png", (1600, 900)),
    ("hero-light-en", LANDSCAPE, DASH, "light", "en", "readme/kobracontrol-hero-light-en.png", (1600, 900)),
    ("hero-light-pt-BR", LANDSCAPE, DASH, "light", "pt_BR", "readme/kobracontrol-hero-light-pt-BR.png", (1600, 900)),
]
# Plain screenshots for the README body: (scene, export stem), each in light and dark, English and Portuguese.
# Tall enough for the whole page: every slot, the controls and the printer panel; the file's details down to its print options.
PLAIN = [("store-status", "readme/kobracontrol-dashboard", (1280, 1600)), ("store-files", "readme/kobracontrol-files", (1280, 940))]
TILE = ("tile", "orca-cloud/kobracontrol-tile.png", 512)
CAMERA_CROP = (120, 378, 880, 805)   # the printer in cover-en, 16:9: the frame the mock camera shows in store-status


def source(name):
    return SOURCE / ("kobracontrol-workshop-%s.png" % name)


def find_panel(im, seed, min_fill=0.985):
    """The empty panel around `seed` (fractions of the image): its box and corner radius, read from the pixels.
    The panel is the connected area of one flat colour; its lighter frame stops the fill."""
    rgb = im.convert("RGB")
    at = (round(seed[0] * rgb.width), round(seed[1] * rgb.height))
    colour = rgb.getpixel(at)
    r, g, b = ImageChops.difference(rgb, Image.new("RGB", rgb.size, colour)).split()
    near = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v <= TOLERANCE else 0)
    ImageDraw.floodfill(near, at, 128)
    area = near.point(lambda v: 255 if v == 128 else 0)
    box = area.getbbox()
    x0, y0, x1, y1 = box
    filled = area.histogram()[255] / ((x1 - x0) * (y1 - y0))
    if filled < min_fill:
        raise SystemExit("the empty panel was not found cleanly (%.3f of %r filled)" % (filled, box))
    # radius: walk each corner's diagonal until the panel starts; on a quarter circle that is r * (1 - 1/sqrt(2))
    steps = []
    for cx, cy, dx, dy in ((x0, y0, 1, 1), (x1 - 1, y0, -1, 1), (x0, y1 - 1, 1, -1), (x1 - 1, y1 - 1, -1, -1)):
        k = 0
        while not area.getpixel((cx + dx * k, cy + dy * k)):
            k += 1
        steps.append(k)
    return box, round(sorted(steps)[1] / 0.2929)


def rounded_mask(size, radius, inset=0):
    big = Image.new("L", (size[0] * 4, size[1] * 4), 0)
    ImageDraw.Draw(big).rounded_rectangle((inset * 4, inset * 4, size[0] * 4 - 1 - inset * 4, size[1] * 4 - 1 - inset * 4), radius * 4, fill=255)
    return big.resize(size, Image.LANCZOS)


def shot_name(scene, theme, lang, width, height):
    return "kobra-%s-%s-%s-%dx%d.png" % (scene, theme, lang, width, height)


def take_shots(scenes, out):
    """Render the scenes with the repo's screenshot script (mock printer, headless Chrome)."""
    frame = out / "camera-frame.jpg"
    Image.open(source("cover-en")).convert("RGB").crop(CAMERA_CROP).resize((1280, 720), Image.LANCZOS).save(frame, quality=90)
    env = {**os.environ, "OUT": str(out), "PAGE": str(PAGE), "FRAME": str(frame), "SCENES": json.dumps([[*s, SCALE] for s in sorted(scenes)])}
    subprocess.run([os.environ.get("NODE", "node"), "tests/page/shots.mjs"], cwd=ROOT / "ui", env=env, check=True)


def save(im, rel):
    path = ROOT / "assets" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, optimize=True)
    note = ""
    if path.stat().st_size > MAX_BYTES:   # too heavy for the listing: 256 colours, dithered
        im.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG).save(path, optimize=True)
        note = "; reduced to 256 colours to stay under 2 MB"
    if path.stat().st_size > MAX_BYTES:
        raise SystemExit("%s is still over 2 MB" % rel)
    return path, note


def record(rel, src, operation, path):
    with Image.open(path) as im:
        size = "%dx%d" % im.size
    if "store-status" in operation:   # say so: no camera took that picture
        operation += "; the camera picture in it is a crop of kobracontrol-workshop-cover-en.png, not a camera capture"
    return {"file": "assets/" + rel, "source": src, "operation": operation, "size": size, "bytes": path.stat().st_size,
            "date": datetime.date.today().isoformat()}


def main():
    panels = {}
    scenes = set()
    for name, seed, (scene, width), theme, lang, _rel, _size in JOBS:
        box, radius = find_panel(Image.open(source(name)), seed)
        height = round(width * (box[3] - box[1]) / (box[2] - box[0]))
        panels[name] = (box, radius, (scene, theme, lang, width, height))
        scenes.add((scene, theme, lang, width, height))
    plain = [(scene, theme, lang, *size) for scene, _stem, size in PLAIN for theme in ("light", "dark") for lang in ("en", "pt_BR")]
    exports = []
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        take_shots(scenes | set(plain), out)
        for name, _seed, _what, _theme, _lang, rel, size in JOBS:
            (x0, y0, x1, y1), radius, scene = panels[name]
            art = Image.open(source(name)).convert("RGB")
            shot = ImageOps.fit(Image.open(out / shot_name(*scene)).convert("RGB"), (x1 - x0, y1 - y0), Image.LANCZOS, centering=(0.5, 0.0))
            art.paste(shot, (x0, y0), rounded_mask(shot.size, radius))
            path, note = save(ImageOps.fit(art, size, Image.LANCZOS), rel)
            exports.append(record(rel, "assets/marketing/source/" + source(name).name,
                                  "screenshot %s (%s, %s, %dx%d CSS px at %dx) pasted into the empty panel at x=%d y=%d %dx%d, corner radius %d; "
                                  "then %dx%d cover-cropped and scaled to %dx%d (Lanczos)%s"
                                  % (scene[0], scene[1], scene[2].replace("_", "-"), scene[3], scene[4], SCALE, x0, y0, x1 - x0, y1 - y0, radius,
                                     art.width, art.height, size[0], size[1], note), path))
        for scene, stem, size in PLAIN:
            for theme in ("light", "dark"):
                for lang in ("en", "pt_BR"):
                    rel = "%s-%s-%s.png" % (stem, theme, lang.replace("_", "-"))
                    path, note = save(Image.open(out / shot_name(scene, theme, lang, *size)).convert("RGB"), rel)
                    exports.append(record(rel, "ui/tests/page/shots.mjs", "screenshot %s (%s, %s, %dx%d CSS px at %dx) of the built page with the mock printer%s"
                                          % (scene, theme, lang.replace("_", "-"), *size, SCALE, note), path))
    # the tile: the rounded square alone, on a transparent ground, so it sits on light and dark pages alike
    name, rel, side = TILE
    art = Image.open(source(name)).convert("RGB")
    (x0, y0, x1, y1), radius = find_panel(art, (0.5, 0.2), min_fill=0.8)
    inset = 2   # inside the soft white edge of the generated square
    tile = art.crop((x0 + inset, y0 + inset, x1 - inset, y1 - inset)).convert("RGBA")
    tile.putalpha(rounded_mask(tile.size, radius - inset))
    path, note = save(tile.resize((side, side), Image.LANCZOS), rel)
    exports.append(record(rel, "assets/marketing/source/" + source(name).name,
                          "rounded square cropped at x=%d y=%d %dx%d (corner radius %d), ground outside it made transparent, scaled to %dx%d (Lanczos)%s"
                          % (x0 + inset, y0 + inset, tile.width, tile.height, radius - inset, side, side, note), path))
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    manifest["exports"] = exports
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", "utf-8")
    for e in exports:
        print("%-62s %-9s %8d" % (e["file"], e["size"], e["bytes"]))


if __name__ == "__main__":
    main()
