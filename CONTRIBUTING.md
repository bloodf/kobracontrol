# Contributing

Thanks for helping. Bug reports, logs and pull requests are all welcome. The plugin is in
development.

## Reporting a problem

Open an issue with:

- the kobracontrol version (Settings page of the Kobra Control tab) and the OrcaSlicer version
- the printer firmware version
- what you did, what you expected and what happened
- the plugin log: `<OrcaSlicer data folder>/log/python_*.log`

Leave out the printer's MQTT credentials, the client certificate and anything else private.

## Set up

You need Python 3.12 or newer. The plugin uses only the standard library, so there is nothing to
install.

```sh
git clone https://github.com/bloodf/kobracontrol
git clone https://github.com/bloodf/spooler     # next to it, for the joint tests
cd kobracontrol
python3 scripts/build.py                        # writes dist/kobracontrol_any.whl
python3 -m unittest discover -s tests
```

Page tests need Node and Chrome or Chromium (`CHROME=...`). Run headless Chrome with
`--use-mock-keychain --password-store=basic`.

To try a build in OrcaSlicer: **File > Plugins > Install local plugin**, pick
`dist/kobracontrol_any.whl`, then **Activate**. Python errors and `print()` output go to
`<OrcaSlicer data folder>/log/python_*.log`.

## Layout

```text
src/kobracontrol/      plugin sources
src/kobracontrol/ui/   the tab page and icons
scripts/build.py       builds the single-file plugin
tests/                 unit tests, a fake `orca` module and a fake Kobra X (HTTP and MQTT over TLS)
ui/                    the Vue 3 + PrimeVue project for the tab
assets/                README, store and social images
docs/                  reference documentation
```

## Rules for code

- **Standard library only.** No dependencies.
- **Only `plugin.py` imports `orca`.** Keep everything else testable without OrcaSlicer.
- **No printer traffic on OrcaSlicer's threads.** Use the service worker or `run_off_thread`.
- **Anything that moves the printer, heats it or deletes files asks first** in the UI.
- **No certificate or key in the repo or the wheel.** The client certificate comes from the user's
  own Anycubic Slicer Next installation.
- **Protocol facts come from a source.** Check a topic or endpoint against
  [Kobralink](https://github.com/NatHacks/Kobralink) or the printer before using it, and list it in
  `docs/protocol.md`. Do not copy code from projects with an incompatible licence (the plugin is
  GPL-3.0-only).
- Keep functions small and files focused. Comment only what isn't obvious from the code.

## Tests

Write the test first. Every change needs a test that fails without it. `tests/fakes.py` has a fake
`orca` module and a fake Kobra X. The page is a Vue 3 + PrimeVue project in `ui/`: change it there,
then `cd ui && npm ci --ignore-scripts && npm run build && npm test`. Run the whole suite before you
open a pull request.

## Commits and pull requests

- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(ace): ...`, `fix(mqtt): ...`, `docs: ...`, `test: ...`.
- One topic per pull request. Describe what changed, how you tested it, and whether you tried it on a
  real Kobra X.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`.

## Assets

Images live in `assets/` and the UI icons in `src/kobracontrol/ui/`. Screenshots inside images are
real renders of the built page (`node ui/tests/page/shots.mjs`), not edited by hand. Fonts stay with
their licence files.

## License

By contributing you agree that your work is released under the [GPL-3.0-only](LICENSE) license.
