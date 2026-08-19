# Canonical forecast release index

This index identifies the accepted forecast lifecycle artifacts without changing any frozen bytes.
All paths are repository-relative and directly versioned.

| Role | Path | Status |
| --- | --- | --- |
| Exact-draw source | `releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative/` | Frozen source for the native vintage |
| First native build | `releases/forecast-vintages/2026-07-19-blackwell-linked-chain-native-vintage/` | Historical predecessor; retained, not canonical |
| Native forecast vintage | `releases/forecast-vintages/2026-07-19-blackwell-linked-chain-native-vintage-v2/` | Canonical immutable vintage |
| Pre-period review | `releases/forecast-outcome-reviews/2026-07-19-blackwell-linked-chain-preperiod/` | Canonical immutable pre-period disposition review |

The first native build and v2 have identical registry, result, forecast, outcome-contract, replay,
source-result, source-manifest, and source-draw bytes. Their dashboards differ; v2 is the release
pinned by the outcome review and is therefore canonical.

## Lifecycle gate

- Target-period cutoff: `2026-09-30`.
- Earliest outcome observation: `2026-10-01`.
- Expected evidence date: `2026-12-31`.
- Revision-window end: `2027-03-31`.

As of `2026-08-18`, all five metrics remain `pending_period_end`, with zero outcomes and zero scores.
The source is synthetic and remains ineligible for evidence-backed model calibration. After the
period ends, create a new outcome review that pins the canonical v2 vintage. Never revise the
vintage or pre-period review in place, and never substitute capacity announcements, construction
progress, or directional statements for scope-matched realized quantities.
