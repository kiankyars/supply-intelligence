# Data Center Atlas adapter fixture

This immutable fixture contains only the capacity, entity, and evidence rows used by the checked
OpenAI Abilene adapter example. It exists so the Supply Intelligence data-center bridge can be
validated from a clean clone without assuming that a sibling repository has generated release
payloads on disk.

The rows were selected from the historical Data Center Atlas release recorded at
`2026-07-18T02:00:00Z`. The fixture manifest retains that release's manifest SHA-256 as lineage, but
the full upstream release is not bundled here. This directory is therefore not a replacement Data
Center Atlas release and must not be used as a current atlas snapshot. The retained upstream hash is
an asserted lineage record; Supply Intelligence alone cannot cryptographically prove selected-row
membership in that upstream release without its full payload.

The 421 MW base value and interval are an Epoch AI modeled gross site envelope under CC BY 4.0. They
are not metered load, unused capacity, tenant allocation, or evidence of installed or operational
GB200 systems. See `manifest.json` for byte and hash pins.
