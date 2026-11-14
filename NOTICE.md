# Notice

kobracontrol is licensed under the GNU General Public License v3.0 only (see [LICENSE](LICENSE)).

## Upstream projects

Parts of kobracontrol's protocol code are ported from two GPL-3.0 projects:

- [KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release), copyright viewit and KX-Bridge
  contributors.
- [Kobralink](https://github.com/NatHacks/Kobralink), by NatHacks.

Per-module provenance:

| Module | From KX-Bridge | From Kobralink |
|---|---|---|
| `aes.py` | nothing (written from FIPS-197 and SP 800-38A) | nothing |
| `mqtt.py` | TCP keepalive options, tolerated empty TLS reads, one lock around socket reads and writes, skipping bad packets | protocol parameters (MQTT 3.1.1, clean session, keepalive 60, QoS 0) |
| `certs.py` | the `cloud_mqtt` library location, TLS context settings | the PEM scan and its patterns, file extensions, size limit, choosing the `AnycubicSlicer` certificate, matching its key |
| `kobra.py` | preparation states and frozen progress, terminal-state resets, stale reply rejection, single guarded handshake, waiting for `file/report` answers, `buried/report`, failed `multiColorBox` reports, camera URL rotation | credential recovery, topics and message envelope, reply matching, command helpers, upload, print payload, report handling |
| `ace.py` | multi-ACE numbering, empty-slot handling, feed activity, drying state and presets, material normalisation, RFID vendor matching, `setInfo` payload | slot aggregation and modes, usable-slot rule, automatic and assigned slot mapping, ACE unit aggregation |

Modules not listed are adapted from [u1control](https://github.com/bloodf/u1control) (GPL-3.0-only,
same author) or written for kobracontrol.

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
