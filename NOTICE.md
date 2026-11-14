# Notice

kobracontrol is licensed under the GNU General Public License v3.0 only (see [LICENSE](LICENSE)).

## Upstream projects

Parts of kobracontrol's protocol code are ported from two GPL-3.0 projects:

- [KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release), copyright viewit and KX-Bridge
  contributors.
- [Kobralink](https://github.com/NatHacks/Kobralink), by NatHacks.

Per-module provenance: filled in when the code lands.

## Interoperability

The Kobra X LAN protocol was reverse-engineered by those projects for interoperability. kobracontrol
uses it only to talk to a Kobra X that the user owns, on the user's own network.

## What kobracontrol does not include

Unlike those projects, kobracontrol does not include Anycubic's TLS client certificate or key, in the
repository or in the wheel. It reads them locally from the user's own Anycubic Slicer Next
installation (or a file the user picks) and keeps a copy in the plugin's storage folder.

## Affiliation and trademarks

kobracontrol is independent. It is not affiliated with, made by or supported by Anycubic. Anycubic,
Kobra, OrcaSlicer, Spoolman and other names are trademarks of their owners.
