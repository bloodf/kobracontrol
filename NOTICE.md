# Notice

kobracontrol is licensed under the GNU General Public License v3.0 only (see [LICENSE](LICENSE)).

## Upstream projects

Parts of kobracontrol's protocol code are ported from two GPL-3.0 projects:

- [KX-Bridge](https://gitea.it-drui.de/viewit/KX-Bridge-Release), copyright viewit and KX-Bridge contributors.
- [Kobralink](https://github.com/NatHacks/Kobralink), by NatHacks.

Per-module provenance:

| Module | From KX-Bridge | From Kobralink |
|---|---|---|
| `aes.py` | nothing (written from FIPS-197 and SP 800-38A) | nothing |
| `mqtt.py` | TCP keepalive options, tolerated empty TLS reads, one lock around socket reads and writes, skipping bad packets | protocol parameters (MQTT 3.1.1, clean session, keepalive 60, QoS 0) |
| `certs.py` | the `cloud_mqtt` library location, TLS context settings | the PEM scan and its patterns, file extensions, size limit, choosing the `AnycubicSlicer` certificate, matching its key |
| `kobra.py` | preparation states and frozen progress, terminal-state resets, stale reply rejection, single guarded handshake, waiting for `file/report` answers, `buried/report`, failed `multiColorBox` reports, camera URL rotation | credential recovery, topics and message envelope, reply matching, command helpers, upload, print payload, report handling |
| `ace.py` | multi-ACE numbering, empty-slot handling, feed activity, drying state and presets, material normalisation, RFID vendor matching, `setInfo` payload | slot aggregation and modes, usable-slot rule, automatic and assigned slot mapping, ACE unit aggregation |

Modules not listed are adapted from [u1control](https://github.com/bloodf/u1control) (GPL-3.0-only, same author) or written for kobracontrol.

## Anycubic Cloud (MIT-licensed sources)

`cloud.py`, the opt-in Anycubic Cloud connection, ports small parts of two MIT-licensed OrcaSlicer plugins.
Their notices are kept here as their licence asks:

- [OrcaCubic](https://github.com/cathome1/OrcaCubic) by cathome1: the request signature and the MQTT login
  (RSA PKCS#1 v1.5 with the standard library). Not taken: its G-code rewriting and its fall-back to the first
  online printer.
- [anycubic-plugin](https://github.com/Bob-41/anycubic-plugin) by Bob-41: the token exchange, finding the token in
  Anycubic Slicer Next's logs, the broker's CA and verified TLS, the upload steps, the order ids, and the look at
  the printer and its active job before every order (its protocol notes, `mqtt_auth_protocol.md`). Not taken:
  the Agora camera, the paho-mqtt dependency, the local bridge.

```
MIT License

Copyright (c) 2026 cathome1

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

```
MIT License

Copyright (c) 2026 Anycubic Cloud Print Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Model data

The model table (`profiles.py`, [docs/models.md](docs/models.md)) is facts gathered from public sources: model codes
from [anycubic_ha_local](https://github.com/chrisfore/anycubic_ha_local) and [Rinkhals](https://github.com/jbatonnet/Rinkhals),
bed sizes from Anycubic Slicer Next's machine profiles, temperature maxima from Anycubic's published specifications.
The Kobra 3 and Kobra S1 Max report payloads in `tests/test_models.py` are re-typed, with addresses and ids replaced,
from Rinkhals' MQTT notes and from anycubic_ha_local's test fixtures (MIT licence, copyright 2026 Chris Fore).

## Interoperability

The Anycubic LAN protocol was reverse-engineered by those projects for interoperability. kobracontrol uses it only to talk to a printer that the user owns, on the user's own network.

## What kobracontrol carries from Anycubic

- Anycubic Slicer Next's TLS client certificate and key (`CN=AnycubicSlicer`): a shared client identity, the same in
  every copy of Anycubic Slicer Next, which the printer requires on its LAN MQTT port. Bundled so the plugin needs no
  setup; a copy from the user's own install can replace it (Find certificate).
- For the opt-in Anycubic Cloud only (`cloud.py`): the request-signing values and the MQTT broker's public key that
  every copy of Anycubic Slicer Next carries, and Anycubic's public root CA certificate, used to verify the broker.

## Printer photo

Printer photo: Anycubic product image. The status card shows a cut-out of Anycubic's Kobra X product photo
(`ui/src/assets/kobra-x.webp`, with the spool mask and shading made from it); it is not covered by the GPL licence
of the code.

## Affiliation and trademarks

kobracontrol is independent. It is not affiliated with, made by or supported by Anycubic. Anycubic, Kobra, OrcaSlicer, Spoolman and other names are trademarks of their owners.
