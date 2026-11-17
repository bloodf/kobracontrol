"""Read-only checks of a sliced G-code before it goes to the Kobra X, and of the printer preset that writes it.
Nothing here changes a file or a preset. Free of the `orca` module.

What the printer takes from a G-code file: its `file/fileDetails` answer on firmware 2.0.2.8 (tests/kobra_captures.py)
carries the picture as a PNG (`thumbnail`, `png_image`), the printer model, each filament's type, colour and weight,
the layer height, temperatures and speeds. OrcaSlicer writes the picture after the header block
(`; thumbnail begin WxH <len>` for PNG; `; thumbnail_JPG begin`, `_QOI`, ... for the other formats) and its settings
between `; CONFIG_BLOCK_START` and `; CONFIG_BLOCK_END` near the end of the file, unless the printer preset's "Skip
G-code config block" (`gcode_skip_config_block`) is on. That the screen needs those two blocks is inferred from that
answer: a file without them has not been tried on a Kobra X, so the warnings say "probably"."""

import re

from i18n import lazy

HEAD = 1024 * 1024   # the thumbnail block follows the header block at the top
TAIL = 256 * 1024    # after the config block come only the filament statistics
THUMBNAIL = re.compile(rb"^;[ \t]*(thumbnail(?:_\w+)?) begin ", re.M)
CONFIG_END = b"; CONFIG_BLOCK_END"
TRUE = ("1", "true")

NO_CONFIG = lazy("The G-code has no settings block at its end. The Kobra X screen probably reads the filament and print "
                 "details from it. Likely cause: Skip G-code config block is on. Turn it off in Printer settings > Basic "
                 "information > Advanced and slice again.")
NO_THUMBNAIL = lazy("The G-code has no preview picture, so the Kobra X screen probably shows the file without one. Set G-code "
                    "thumbnails in Printer settings > Basic information > Advanced, for example to 300x300/PNG, and slice "
                    "again.")
NOT_PNG = lazy("The G-code's preview picture is not a PNG, and the Kobra X screen probably shows only PNG pictures. Use "
               "/PNG sizes in Printer settings > Basic information > Advanced > G-code thumbnails, for example "
               "300x300/PNG, and slice again.")
PRESET_SKIPS_CONFIG = lazy("Skip G-code config block is on in this printer preset. The Kobra X screen probably reads the "
                           "filament and print details from that block. Turn it off in Printer settings > Basic "
                           "information > Advanced.")
PRESET_NO_PNG = lazy("This printer preset writes no PNG preview picture (G-code thumbnails: %s). The Kobra X screen "
                     "probably shows only PNG pictures. Set G-code thumbnails in Printer settings > Basic information > "
                     "Advanced, for example to 300x300/PNG.")


def inspect(source, size):
    """The problems (lazy texts: tr() them) of a readable, seekable G-code stream of `size` bytes. Reads at most
    HEAD + TAIL bytes and never writes."""
    head = source.read(HEAD)
    if size > HEAD + TAIL:
        source.seek(size - TAIL)
        tail = source.read(TAIL)
    else:
        tail = head + source.read()
    problems = []
    if CONFIG_END not in head and CONFIG_END not in tail:   # BBL-style files carry the block at the top
        problems.append(NO_CONFIG)
    tags = set(THUMBNAIL.findall(head))
    if not tags:
        problems.append(NO_THUMBNAIL)
    elif b"thumbnail" not in tags:
        problems.append(NOT_PNG)
    return problems


def writes_png(thumbnails):
    """Whether OrcaSlicer's `thumbnails` value ("32x32/PNG, 300x300/PNG") has a PNG size. A size without a format
    takes `thumbnails_format`, PNG by default, and counts as PNG."""
    sizes = [s.strip() for s in str(thumbnails).split(",") if s.strip()]
    return any("/" not in s or s.rsplit("/", 1)[1].strip().upper() == "PNG" for s in sizes)


def preset_problems(skip_config_block, thumbnails):
    """[(lazy text, values)] for a printer preset's serialized `gcode_skip_config_block` and `thumbnails`; a value
    OrcaSlicer did not give (None) is not judged."""
    problems = []
    if str(skip_config_block).strip().lower() in TRUE:
        problems.append((PRESET_SKIPS_CONFIG, ()))
    if thumbnails is not None and not writes_png(thumbnails):
        problems.append((PRESET_NO_PNG, (str(thumbnails).strip() or "-",)))
    return problems
