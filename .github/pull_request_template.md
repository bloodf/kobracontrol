## What changed

## How I tested it

- [ ] `python3 -m unittest discover -s tests` passes
- [ ] `npm test` in `ui/` passes (if the page changed)
- [ ] Tried in OrcaSlicer 2.5 (which OS?)
- [ ] Tried on a real Kobra X (which firmware version?)

## Checklist

- [ ] New printer commands match what Kobralink or KX-Bridge send, and are listed in `docs/protocol.md`
- [ ] New page commands are in `docs/architecture.md`
- [ ] Anything that moves, heats or deletes asks first in the page
- [ ] `CHANGELOG.md` has a line for this change
