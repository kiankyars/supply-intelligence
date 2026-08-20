# Supply Intelligence — Blackwell Constraint Pulse v1

The Blackwell Constraint Pulse is a weekly 2026-Q4 evidence product. It answers three questions:

- what changed in Blackwell manufacture, shipment, and data-centre energization;
- which synthetic model inputs now have an evidence-backed replacement candidate; and
- what remains unknowable.

The first production [upstream release lock](../contracts/blackwell-constraint-pulse-v1/upstream-releases.lock.json)
is intentionally empty. Data Center Atlas and Semiconductor Atlas do not yet have compatible,
immutable public release assets to pin. An empty lock is valid and produces missing assessments and
the non-estimate result; it is not permission to invent release metadata or read either sibling
working directory.

## Pre-change baseline

Before the feature branch was created, the worktree was clean at main commit
`6d287e9bae400a54d05f8f8ae15687eb80dedbfb`. The baseline command was:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

It ran 209 tests with 209 passes, zero failures, zero errors, and zero skips. `unittest` reported
20.196 seconds and observed wall time was 20.35 seconds. This is the pre-change main baseline, not
the later feature-branch integration suite; post-implementation results and any increased test count
must be reported separately.

## Production boundary

Production ingestion starts with `load_upstream_release_lock`. The only allowed upstream identities
and repositories are:

| `upstream_id` | exact `repository` |
| --- | --- |
| `datacenter_atlas` | `kiankyars/datacenter-atlas` |
| `semiconductor_atlas` | `kiankyars/semiconductor-atlas` |

The lock has exactly four top-level fields:

```json
{
  "format": "ai-supply-upstream-release-lock.v1",
  "product": "blackwell-constraint-pulse",
  "target_quarter": "2026-Q4",
  "upstreams": []
}
```

When an upstream release exists, its entry has exactly `upstream_id`, `repository`, `release_tag`,
`asset`, and `manifest`. Entries are unique and sorted by `upstream_id`. The nested objects pin:

| Object | Exact fields | Contract |
| --- | --- | --- |
| `asset` | `name`, `url`, `bytes`, `sha256` | A simple `.zip` name; positive byte count; lowercase SHA-256; and the exact URL `https://github.com/<repository>/releases/download/<release_tag>/<name>` with no query, fragment, credentials, port, redirect-to-latest alias, or local path. |
| `manifest` | `path`, `sha256`, `schema_version` | `path` is exactly `manifest.json`; the hash pins its raw bytes; `schema_version` is exactly `ai-supply-upstream-claim-release.v1`. |

There is no `release_dir` input. Production code never reads `../datacenter_atlas` or
`../semiconductor_atlas`. Test fixtures are small, explicitly synthetic bundles and are not
production evidence.

## Download and content-addressed cache

`fetch_locked_release` obtains only the exact locked GitHub asset URL. Before any write, it verifies
both the locked byte count and SHA-256. A valid object is atomically stored at:

```text
<cache-root>/objects/sha256/<first-two-hex>/<asset-sha256>
```

Every cache hit is re-read and reverified from one opened regular-file descriptor. Cache directory
components are opened or created descriptor-relative with no-follow flags; the final object is
published with an exclusive hard link, never a replacing rename. This keeps concurrent path swaps
and pre-existing objects outside the ingestion boundary. A cache root whose lexical or resolved
path contains `datacenter_atlas` or `semiconductor_atlas` is rejected, as are symlinks and
non-regular cache objects. `fetch_and_load_locked_release` can populate and validate the cache;
pulse release assembly uses `load_cached_release` and therefore builds from already verified
content-addressed objects only.

The locked ZIP contains exactly two safe, unique, regular members: `manifest.json` and
`claims.json`. The manifest has exactly these fields:

```text
format, schema_version, upstream_id, repository, release_tag,
comparison, as_of_date, recorded_at, files
```

Its `format` is `ai-supply-upstream-claim-release-manifest.v1`; its `schema_version` and identity
fields must match the lock. `files` contains only a `claims.json` descriptor with exact `bytes` and
`sha256` fields. Those bytes are verified before JSON parsing. The claims document then uses
`format: ai-supply-upstream-claims.v1` and a `claims` array.

`comparison` is null for an initial release. Otherwise it has exactly `release_tag`,
`manifest_sha256`, and `claims_sha256` naming the different prior immutable public release against
which the Atlas producer says each `change_status` was computed. A `revised` or `removed` claim is
invalid without that producer-declared basis. These fields are integrity-protected by the locked
current release, but v1 does not lock, download, or replay the prior asset. The pulse therefore
labels every change as upstream-reported, carries the declaration into lineage and changed rows,
and explicitly says that the comparison was not locally replayed. It does not invent a comparison
from local working trees or present a producer status as an independently verified diff.

This is an immutable asset boundary, not merely a download cache: release tag, asset URL and name,
asset size and hash, schema version, and manifest hash all have to agree before claims are visible to
the pulse.

## Claim contract and classifications

Each upstream claim names an `id`, `target_id`, `claim_kind`, `intended_use`, `change_status`,
`summary`, optional numerical `value`, `posture`, `period`, `time_basis`, `attribution_basis`, sorted
`gate_supports`, `range_basis`, and `evidence`. A numerical value is an explicit
`low`/`base`/`high` range with one unit. `range_basis` is either `exact` (all three values must be
identical) or `bounded_interval` (evidence-supported lower bound, central estimate, and upper bound;
not probabilistic quantiles). Each audit requirement lists its accepted bases, so percentile ranges
or differently defined intervals cannot enter component-wise minimum arithmetic. Non-missing claims
carry evidence records with a valid host-bearing HTTPS source URL, publisher, publication and
retrieval timestamps, and a content SHA-256. Evidence timestamps must not extend past the upstream
release's recorded cutoff.

Each `gate_supports` record is a typed categorical assertion with exactly `gate_id`, `assertion`,
`period`, `time_basis`, `attribution_basis`, `posture`, and `evidence_ids`. The evidence IDs must be
non-empty references to the parent claim's evidence records. Supports are sorted and unique by gate
ID. A bare gate name is insufficient: assertion text, `2026-Q4` period, gate-specific time and
attribution bases, and reported/derived posture must exactly match the frozen audit contract, and the
parent target must itself resolve to one unambiguous numerical constraint from a required upstream.

Every assessed claim, and every generated absence for a required target, receives exactly one of
the following classifications:

| Classification | Meaning |
| --- | --- |
| `numerical_constraint` | A numerical constraint claim from a fresh release matches the required upstream, unit, accepted range basis, `2026-Q4` period, time basis, attribution basis, reported/derived posture, and suitable evidence. |
| `scale_control` | The claim is explicitly declared as a nonbinding scale control. It can provide context but cannot pass a numerical gate. |
| `directional_evidence` | The claim is qualitative, directional, or intended as a signal. It can explain change but cannot pass a numerical gate. |
| `incompatible` | The target is unknown or a numerical claim fails one or more scope, unit, period, time-basis, attribution, posture, or evidence checks. |
| `missing` | The upstream explicitly reports the claim as missing or removed, the required release is absent, or a verified release contains no claim for the required target. |

The decision order is deterministic: explicit missing or removal first; then an unknown target;
then directional or signal evidence; then scale control; finally numerical constraint eligibility.
No claim is placed in more than one class.

## Integrity failure versus evidence absence

Integrity and compatibility are separate failure domains.

An invalid lock, non-canonical URL, unavailable pinned download, size or hash mismatch, tampered
cache object, unsafe or unexpected ZIP member, manifest drift, identity mismatch, claims-byte drift,
invalid JSON/schema, invalid pulse configuration, or divergent existing release directory aborts
the build before a release is written. The system does not reinterpret an unverifiable pinned asset
as merely missing and does not heal a tampered cache object by refetching it.

A valid zero-entry lock, an absent upstream lock entry, an explicit missing claim, or a valid but
semantically incompatible claim is representable evidence state. The pulse emits deterministic
`missing` or `incompatible` assessments, records blockers, and keeps the estimate closed. This
allows a weekly pulse to report honest absence without weakening the integrity boundary.

## Evidence gates

A numerical manufacture, shipment, energization, or overall supply-to-site result is allowed only
when all applicable gates pass:

1. Both Atlas releases are present in the lock and load as verified cache objects.
2. Every active synthetic input marked `required_for_numerical_result` has exactly one
   `numerical_constraint` claim for its target. Zero candidates and multiple candidates both block
   the stage.
3. Every stage-level gate target has exactly one `numerical_constraint` claim. A passing claim must
   match the audit's required upstream, unit, accepted range basis, `2026-Q4` period, exact time
   basis, exact attribution basis, reported/derived posture, freshness, and evidence requirement.
4. Every required categorical gate passes. A categorical gate is supported only by a typed
   `gate_supports` assertion on an unambiguous `numerical_constraint` parent. Its assertion, period,
   time basis, attribution basis, reported/derived posture, parent evidence references, and required
   upstream must all match exactly. Missing, unrelated, incompatible, conflicting, or bare support
   declarations block the gate. Every upstream named by the gate must contribute valid support.
   Stage and `cross_stage` gates apply.
5. All three stages — `manufacture`, `shipment`, and `energization` — pass before the overall
   supply-to-site gate passes.

For a passing stage, its gate-target ranges are combined as the component-wise minimum
low/base/high range in the shared `system` unit. The overall result is the corresponding minimum
across the three passing stage ranges. The output is `exact` only when every contributing value is
exact; otherwise it remains an explicitly non-percentile `bounded_interval`. Scale controls,
directional evidence, synthetic values,
partially matched scope, unsupported attribution, incompatible units, and unsupported postures
never enter that arithmetic.

When a stage or the overall supply-to-site gate does not pass, its estimate is exactly:

```text
no evidence-backed estimate.
```

The period is part of the required string.

## Synthetic inputs and protected unknowns

The synthetic-input audit remains the authoritative inventory of current ranges and their required
claim type, unit, upstream, attribution basis, time basis, and gate. A single passing numerical claim
creates a `replacement_status` of `eligible_candidate_not_applied`. It does not mutate the source
scenario, overwrite the audit range, or turn `current_posture: synthetic` into fact.

The v1 inventory is frozen to source commit
`6d287e9bae400a54d05f8f8ae15687eb80dedbfb`, source quarter `2026-Q3`, 107 active input IDs,
one diagnostic ID, and active-ID-set SHA-256
`4e4291d3e5fba63b6bf92a448fa4a576ef86e00cf09eb137acb25f47670ce5c2`. The active transitive
leaves are:

| Source layer | Active numeric/range leaves |
| --- | ---: |
| logic/package manufacturing | 9 |
| supplier-resolved HBM | 32 |
| ODM/component system assembly | 49 |
| data-centre operational conversion | 7 |
| retained factory/logistics/installation base constraints | 9 |
| selected-site chain allocation link | 1 |
| **Total** | **107** |

The supplier-HBM platform demand range is retained as one diagnostic-only row because the linked
chain consumes the pre-demand `customer_allocated_stacks` pool. The 14 final linked wrapper
estimates are not counted again, and the superseded aggregate-HBM branch is inactive. The schema
also freezes three direct stage targets and eight required categorical gates for material/component
coverage, supplier/ODM/component identity and non-overlap, operational deduction non-overlap,
site-shipment attribution, and cross-source dependence. Changing the self-declared counts or hash
cannot make an incomplete catalog valid because those values and the required gate ID sets are
hard-pinned by the v1 loader. The entire canonical catalog semantics — current ranges and sources,
units, stages, upstream mappings, attribution and time bases, accepted postures, gate descriptions,
categorical support contracts, and protected-unknown policies — are additionally pinned to SHA-256
`b01bc728b58d9cc92aa8e36ad184988ad9db32a3a376d6c0879c7e7f26d035f4`. Rewriting a row while
preserving its ID therefore fails validation.

Yield, utilization, allocation, demand, capacity, and economics remain explicitly unknown unless a
suitable claim passes the applicable gates. The pulse publishes these as protected unknowns with
`status: unknown_unless_suitable_evidence_is_gated`. Missing evidence is never filled from a model,
a prior-period range, a gross scale control, or a sibling repository's working tree.

## Deterministic weekly release

`load_blackwell_pulse_config` accepts exactly `format`, `pulse_id`, `target_quarter`, `week_ending`,
and `recorded_at`. The format is `ai-supply-blackwell-constraint-pulse-config.v1`. `week_ending` must
be a Sunday from 2026-10-01 through 2026-12-31, the ID must be
`blackwell-constraint-pulse:<week-ending>`, and the explicit recorded cutoff cannot precede that
Sunday. No wall-clock value is introduced during a build, and an upstream release recorded after
the cutoff or carrying an `as_of_date` after the week-ending cutoff is rejected.

A verified release is fresh for one weekly pulse only when its `as_of_date` falls in 2026-Q4 and is
no more than seven days before `week_ending`. A stale but otherwise valid release remains visible as
`verified_stale`; its numerical claims classify as `incompatible` with
`stale_upstream_release`, so the weekly product is still emitted with the exact non-estimate rather
than silently treating old evidence as current. Upstream lineage exposes manifest as-of and recorded
timestamps, verified claims hash, freshness, age in days, and the producer-declared comparison.
`questions.what_changed_basis` records that prior comparison assets were not locally replayed;
each changed row uses an `upstream_reported_*` basis and carries the same limitation.

`build_blackwell_pulse_release_documents` serializes JSON with sorted keys, fixed indentation,
UTF-8, and a final newline. Assessments, blockers, classifications, replacements, unknowns, changes,
and upstream lineage are stably sorted. Given byte-identical config, lock, audit, and verified cache
objects, the release bytes are identical.

The immutable release contains exactly:

- `README.md`;
- `claim-classifications.json`;
- `pulse-config.json`;
- `pulse.json`;
- `synthetic-input-audit.json`;
- `upstream-releases.lock.json`; and
- `manifest.json`.

The copied config, audit, and lock preserve their exact source bytes. Upstream payloads are not
republished. `claim-classifications.json` uses
`ai-supply-blackwell-claim-classifications.v1` and provides a count for all five classes plus the
sorted assessments. `pulse.json` uses `ai-supply-blackwell-constraint-pulse.v1` and includes the
three answers, claim assessments, stage and categorical gate results, blockers, upstream lineage,
lineage hashes, limitations, and `supply_to_site_estimate`.

`manifest.json` uses `ai-supply-blackwell-constraint-pulse-release.v1` and has exactly these fields:

```text
format, pulse_id, product, target_quarter, week_ending, recorded_at,
supply_to_site_estimate, input_hashes, files
```

`input_hashes` contains `pulse_config_sha256`, `synthetic_input_audit_sha256`,
`synthetic_input_audit_semantic_sha256`, and `upstream_release_lock_sha256`. `files` pins the byte
count and SHA-256 of every payload except the manifest itself. `write_blackwell_pulse_release` writes
through a no-follow, descriptor-relative temporary directory, fsyncs every file and the directory,
and publishes with the platform's atomic no-replace rename (`renameatx_np` with exclusion and
no-follow/beneath flags on macOS). It then fsyncs the opened parent directory. A concurrent or
pre-existing destination is never overwritten: it is accepted only when its exact regular-file set
and every byte match the deterministic replay. A failure after publication but before the final
parent sync is reported as commit-uncertain and is safely resolved by retrying the same build.

## Remaining Atlas dependencies

Each upstream entry must remain absent until that project publishes a real, immutable, compatible
GitHub release asset. The lock can be updated one release at a time, but the overall numerical gate
remains closed until both verified releases are present. A usable Semiconductor Atlas release must
provide appropriately scoped Blackwell manufacture and shipment claims for the audit targets. A
usable Data Center Atlas release must provide appropriately scoped energization and site-availability
claims. In both cases, a public total, nameplate value, directional statement, or gross MW figure is
not enough unless its unit, period, time basis, attribution basis, posture, and evidence satisfy the
exact target contract.

After each public release exists, a reviewed lock update must record its real tag, canonical asset
URL and name, exact asset byte count and SHA-256, schema version, and exact manifest SHA-256. The
asset must then be downloaded into the content-addressed cache and fully verified. Until that
happens, the weekly product correctly reports `no evidence-backed estimate.` and preserves every
synthetic input and protected unknown.
