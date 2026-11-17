# Releasing

A release is a GitHub release for the tag `vX.Y.Z`. Publishing the release runs
`.github/workflows/publish-orcacloud.yml`, which repeats the CI checks on the tagged commit, builds the wheel,
attaches `kobracontrol_any.whl` and `SHA256SUMS` to the GitHub release, and publishes the same wheel to Orca Cloud.

Orca Cloud only accepts the GitHub OIDC token of a run triggered by a published release (audience `orcacloud`,
HTTP 201 is success), so a tag push or a manual run does not publish. No secret is stored in the repository.

## What the workflow enforces

- The tag is `vX.Y.Z` (numeric) and equals `version` in `pyproject.toml`; `scripts/build.py --release-tag` checks it
  again.
- `ui/` is rebuilt with `npm ci --ignore-scripts && npm run build`, and the run fails if
  `src/kobracontrol/ui/app.html` or `ui/build.json` differ from the commit.
- The whole suite runs with `WORKERS=1`: `python -m unittest discover -s tests`, with Node 24 and Chrome.
- `dist/SHA256SUMS` matches the wheel, and the wheel's metadata and `VERSION` equal the version.
- `CHANGELOG.md` has a non-empty section for the version. It becomes the GitHub release notes (when they are empty)
  and the Orca Cloud changelog; `scripts/release_notes.py` cuts the copy sent to Orca Cloud and adds a link to the
  release page.

## Steps

1. On `main`, the commit to release has `pyproject.toml`, `ui/package.json` and `ui/package-lock.json` at the new
   version and a dated changelog section. Run the local gates below.
2. Tag exactly that commit and push the tag: `git tag vX.Y.Z <commit> && git push origin vX.Y.Z`.
3. Publish the release, which starts the workflow:
   `python3 scripts/release_notes.py X.Y.Z --limit 0 | gh release create vX.Y.Z --verify-tag --title "Kobra Control X.Y.Z" --notes-file -`
4. Wait for the "Publish to Orca Cloud" run to finish. Re-running a run that already published is safe.

A 401 from the publish step means the repository is not connected to the plugin on Orca Cloud (Edit plugin > GitHub
publishing), or the run was not triggered by a published release. A version error means the tag is not higher than
the version Orca Cloud lists.

## Local gates

```sh
(cd ui && npm ci --ignore-scripts && npm run build)    # must leave src/kobracontrol/ui/app.html and ui/build.json unchanged
git diff --exit-code -- src/kobracontrol/ui/app.html ui/build.json
WORKERS=1 python3 -m unittest discover -s tests        # needs node on PATH and Chrome (or CHROME=...)
python3 scripts/build.py --release-tag vX.Y.Z          # dist/kobracontrol_any.whl, dist/SHA256SUMS
```

## The Orca Cloud listing

The listing at <https://cloud.orcaslicer.com/p/59c786285255> is kept by hand; the workflow publishes only the wheel
and the changelog. The description is [orca-cloud-description.md](orca-cloud-description.md), in English and
Portuguese. The images are in `assets/`, all PNG and all under 2 MB:

| Listing slot | File (`-en`, and `-pt-BR` for the Portuguese listing) | Size |
|---|---|---|
| Plugin icon / store tile | `assets/orca-cloud/kobracontrol-tile.png` | 512x512 |
| Main (cover) image | `assets/orca-cloud/kobracontrol-main-en.png` | 1600x900 |
| Square thumbnail, where the listing asks for one | `assets/orca-cloud/kobracontrol-main-square-en.png` | 900x900 |
| Gallery 1, "Send prints over your local network" | `assets/orca-cloud/kobracontrol-feature-01-lan-en.png` | 1600x900 |
| Gallery 2, "Keep an eye on your print" | `assets/orca-cloud/kobracontrol-feature-02-status-en.png` | 1600x900 |
| Gallery 3, "Manage the filament in each slot" | `assets/orca-cloud/kobracontrol-feature-03-ace-en.png` | 1600x900 |
| Gallery 4, "Choose files before you print" | `assets/orca-cloud/kobracontrol-feature-04-files-en.png` | 1600x900 |

The description also embeds the four gallery images from `raw.githubusercontent.com` on `main`, so they show there
once the commit that adds them is merged.

The GitHub social preview (Settings > General > Social preview) is `assets/social/kobracontrol-social-preview-en.png`
(1280x640). The README heroes are `assets/readme/kobracontrol-hero-{light,dark}-{en,pt-BR}.png` (1600x900).

### Rebuilding the images

The generated originals, each with an empty panel, are in `assets/marketing/source/`.
`scripts/marketing_images.py` renders the built page with the mock printer of `ui/tests/page/shots.mjs`, pastes each
screenshot into its panel, exports the sizes above and rewrites the `exports` list of
`assets/marketing/asset-manifest.json` (source file, operation, size, bytes, date). Run it again when the page
changes, then look at every image at full size:

```sh
uv run --no-project --with pillow scripts/marketing_images.py   # needs node and Chrome, as the page tests do
```

The camera picture in the status images is a crop of the cover artwork fed to the mock camera. No printer, camera or
network is involved. The tab icon inside OrcaSlicer is the same tile, scaled to 64x64 in
`src/kobracontrol/ui/icon.png`; export it again when the tile changes (`tests/test_tab_icon.py` checks they match).
