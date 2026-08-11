# Data contracts

The loaders accept single-platform `ai-supply-scenario.v1` documents, shared-resource
`ai-supply-portfolio.v1` documents, wafer-to-package `ai-supply-manufacturing.v1` documents, and
supplier-resolved `ai-supply-hbm-supplier-portfolio.v1` documents, and gross-to-net
`ai-supply-datacenter-operational.v1` documents. Supplier-resolved server and rack assembly uses
`ai-supply-system-assembly.v1`. The separate claim ledger accepts
`ai-supply-ingest-pack.v1` source and revision packs. Forecast scoring accepts
`ai-supply-calibration-dataset.v1` documents.

## Top-level objects

| Key | Purpose |
| --- | --- |
| `scenario` | Quarter, freeze dates, draw count, seed, and synthetic posture |
| `platform` | Platform identity and package, server, and rack conversion factors |
| `evidence` | Source ledger referenced by every estimate |
| `constraints` | Resource capacity and BOM inputs by production stage |
| `allocations` | Customer shares and demand ceilings |
| `supplier_economics` | Revenue and gross-margin bridge by supplier |
| `consensus` | Comparable supplier revenue estimates |
| `opportunity_factors` | Confidence, liquidity, timing, catalyst, and diligence fields |

The loader requires at least one `accelerator_package` constraint so each later stage has an upstream
capacity bound.

## Portfolio objects

| Key | Purpose |
| --- | --- |
| `scenario` | Quarter, freeze dates, draw count, seed, and synthetic posture |
| `platforms` | Platform BOM conversion factors, demand ranges, and allocation weights |
| `resource_pools` | Capacity and yield available once across every platform |
| `requirements` | Per-platform consumption of each shared resource per complete system |
| `evidence` | Source ledger referenced by every estimate |

Portfolio capacity units must match requirement units. Every resource pool needs at least one
requirement, every platform needs a package-stage requirement, and a platform-resource pair can
appear only once. The allocation policy is fixed to weighted progressive filling in version 1.

## Manufacturing objects

| Key | Purpose |
| --- | --- |
| `scenario` | Quarter, freeze dates, draw count, seed, and synthetic posture |
| `logic.wafer` | Logic wafer starts, wafer geometry, die dimensions, and scribe width |
| `logic` | Defect density, clustering, wafer-sort yield, and performance-bin share |
| `hbm.wafer` | HBM memory wafer starts and die geometry |
| `hbm` | Known-good-die yield, dies per stack, stack yields, capacity, and placements |
| `package` | Assembly starts, final yield, logic dies per accelerator, and accelerators per system |
| `references` | Reported external totals used as nonbinding scale controls |
| `evidence` | Source ledger referenced by every estimate |

Fixed physical topology fields must be positive integers with identical low, base, and high values.
Units are explicit: `die/stack`, `stack/accelerator`, `die/accelerator`, and
`accelerator/system`. Logic and HBM wafer flows need distinct IDs. Every numeric input uses the
common estimate contract and must resolve to an evidence record in the same document.

The manufacturing release writes conversion outputs, bottleneck probability, input estimates,
evidence, the original scenario, and a hash manifest. A synthetic scenario may mix reported or
derived topology with synthetic process inputs, but the dashboard and release README retain the
synthetic warning.

A manufacturing reference fixes its period, comparison target, estimate, and whether it is usable as
product capacity. Company-wide, cross-node, cross-customer, or prior-period totals must set
`usable_as_product_capacity` to `false`. The engine reports the modeled target as a share of the
reference but never changes package output from a nonbinding control.

## Supplier-resolved HBM objects

| Key | Purpose |
| --- | --- |
| `scenario` | Quarter, valid and known cutoffs, draw count, seed, and synthetic posture |
| `platform` | Customer, HBM generation, stack topology, and accelerator-package demand |
| `suppliers` | Supplier-specific wafer, yield, qualification, and allocation flows |
| `evidence` | Claim records referenced by every estimate |
| `source_files` | Exact local source bytes and expected SHA-256 digests |

Every supplier has a unique `capacity_scope_id`; duplicates are rejected before simulation. A
`supplier_hbm3e_compatible` wafer-start basis applies platform qualification and customer allocation
as separate reductions. A `platform_allocated` basis must fix both shares at one so already-allocated
starts cannot be discounted twice. Fixed topology fields are positive integers, estimate units are
validated, and an evidence-backed scenario cannot contain synthetic estimates.

Every non-synthetic evidence record must resolve to at least one source file below the requested
source root whose exact bytes match its declared SHA-256. Missing bytes, path escapes, or hash drift
fail loading. `ai-supply-hbm-supplier-result.v1` reports each conserved supplier flow, aggregate
package equivalents and demand sufficiency, concentration, criticality, and a synthetic-input
research queue. `ai-supply-hbm-supplier-release.v1` copies the exact normalized sources and hashes
all release artifacts. Version 2 additionally writes every aggregate and per-supplier capacity draw
to `capacity_draws.csv` and records its schema and row count in the manifest. See the
[supplier HBM contract](hbm-supplier-portfolio.md).

`ai-supply-hbm-manufacturing-link.v1` hash-pins one manufacturing scenario and one supplier HBM
result, names the aggregate HBM wafer flow to remove, fixes `customer_allocated_stacks` as the import
metric, and declares the P10/P50/P90-to-triangular mapping. Version 2 also pins the capacity-draw
bytes and count and requires `source_capacity_draws_deterministic_permutation`. The loader requires
matching quarters, ordered source times, exact HBM topology, and unique supplier capacity scopes. It
recomputes aggregate and supplier summaries from the draws and verifies stack, demand, and package
conservation. It rejects an HBM wafer-start reference that would outlive the removed aggregate flow.
Version 3 additionally declares whether package assembly starts are `material_cleared_starts` and
names every resource kind absorbed by that definition. The declaration posture must match the
source assembly-start posture and includes its own method and confirm-or-falsify tests. It is a
semantic coverage claim, not evidence of material capacity.
The resulting canonical `ai-supply-manufacturing-result.v1` carries an embedded
`ai-supply-hbm-manufacturing-lineage.v1`; replay-safe link releases preserve every source byte and
hash, with release version 3 recording the material-coverage basis. Release version 4 additionally
writes `manufacturing_draws.csv`, including every logic, HBM, package-attempt, finished-package, and
complete-system draw, and records its fields and row count in the manifest. See the
[supplier HBM manufacturing link](hbm-manufacturing-link.md).

## Supplier-resolved system assembly objects

| Key | Purpose |
| --- | --- |
| `scenario` | Quarter, freeze dates, draw count, seed, and synthetic posture |
| `platform` | Fixed accelerator-per-tray and tray-per-rack topology plus rack demand |
| `odms` | Non-overlapping supplier tray and rack-integration capacity flows |
| `components` | Required server- and rack-stage component pools and per-rack BOM quantities |
| `coverage` | Exact stage and resource-kind selectors absorbed by complete-rack output |
| `evidence` | Claim records referenced by every estimate |
| `source_files` | Exact local source bytes and expected SHA-256 digests |

Every ODM owns unique tray and rack capacity-scope IDs. Every component pool owns another unique
scope. `nameplate_input` applies yield, qualification, and allocation; `sellable_output` must fix
yield at one; `platform_allocated` must also fix qualification and allocation at one. The engine
reconciles tray and rack output inside each ODM before summing supplier contributions, so unused
capacity is not silently transferable between factories.

Component capacity units must match the numerator of fixed positive-integer `units_per_rack`
estimates. Coverage selectors must exactly equal the modeled ODM throughput and component pairs.
Non-synthetic evidence requires hash-matched source bytes below the declared source root.

`ai-supply-system-assembly-result.v1` reports supplier and component flows, complete racks,
accelerator-package equivalents, concentration, bottleneck probabilities, shadow capacity, exact
coverage, and an evidence queue. `ai-supply-system-assembly-release.v1` always preserves every draw
in `capacity_draws.csv`, copies exact normalized source bytes, hashes all payloads, and rejects a
different or incomplete existing output directory. See the
[supplier-resolved assembly contract](system-assembly.md).

## Estimate object

Every numeric field uses the same structure:

```json
{
  "low": 0.62,
  "base": 0.70,
  "high": 0.78,
  "unit": "ratio",
  "posture": "synthetic",
  "methodology": "Illustrative effective yield used to exercise the engine.",
  "confidence": 0.35,
  "last_updated": "2026-07-17",
  "evidence_ids": ["synthetic:capacity"],
  "confirming_evidence": "Known-good-output data support the range.",
  "falsifying_evidence": "Qualification data place yield outside the range.",
  "correlation_group": "front-end"
}
```

Validation requires finite values with `0 <= low <= base <= high`. Ratio estimates cannot exceed
one. Each estimate must reference an evidence record in the same scenario.

## Constraint object

A constraint contains:

- `resource_kind` and a readable `resource_name`;
- the first `stage` that needs the resource;
- a `capacity_basis` that defines the numerator;
- `capacity`, `effective_yield`, `platform_allocation`, and `units_per_system` estimates;
- notes that state remaining modeling gaps.

`capacity.unit` must match `units_per_system.unit`. Yield and platform allocation use `ratio`.

## Shared resource and requirement objects

A portfolio resource records its production stage, capacity basis, capacity estimate, and effective
yield. A requirement links one platform to one resource and supplies the units consumed per complete
system. The portfolio engine samples the pool once per draw. It does not create a platform-specific
copy of shared capacity.

## Evidence object

Evidence records contain an ID, source kind, title, URL, publisher, retrieval timestamp, and optional
publication time, source family, license, excerpt, and content hash. Retrieval timestamps need a time
zone.

Synthetic values still need evidence records. Use a `urn:synthetic:` URL and state that the value is a
demonstration input. This keeps synthetic assumptions visible in the same lineage graph as reported
claims.

## Atlas import object

`ai-supply-atlas-capacity-import.v1` contains one reusable estimate, its copied evidence records, and
lineage to a pinned Semiconductor Atlas release. Its selection document fixes the quarter, capacity
basis, quantity semantics, claim IDs, aggregation policy, cutoffs, and confirm/falsify tests. Forecast
imports also fix a vintage and parameter fingerprint.

See [the adapter contract](atlas-adapter.md) for the source-file and failure rules.

## Data-center power import object

`ai-supply-datacenter-power-import.v1` contains a gross site critical IT MW estimate, copied capacity
and status evidence, selected site records, and release lineage. It always declares that the estimate
is not net incremental capacity. Current load, reservations, platform allocation, and compatible
cooling and density headroom must be supplied before it can become a portfolio resource pool.

See [the power bridge](datacenter-adapter.md) for the selection and failure rules.

## Data-center operational object

`ai-supply-datacenter-operational.v1` pins one gross power-import file by SHA-256, selected site IDs,
and upstream atlas manifest hash. It supplies four explicitly non-overlapping MW deductions, a
target-platform share, rack critical-IT MW, target-quarter commissioning slots, and a completion
ratio. Every local estimate uses the common estimate object and resolves to scenario evidence.

The loader rejects drift in the source file, site set, atlas manifest, capacity semantics, or blocked
availability posture. An evidence-backed scenario cannot contain synthetic estimates. A synthetic
scenario always produces `usable_as_operational_capacity: false`.

`ai-supply-datacenter-operational-release.v2` additionally preserves every gross-to-net power,
commissioning, and operational-rack draw in `capacity_draws.csv`. Its manifest records the exact
field order and row count, and populated-directory writes remain exact-replay only.

See [the operational contract](datacenter-operational.md) for the equations and checked-run boundary.

## Linked-chain recipe

`ai-supply-chain-link.v1` and `ai-supply-chain-link.v2` pin a base complete-system scenario and
frozen manufacturing and operational results and may pin a system-assembly result. Each capacity
link names one source metric, its target constraint semantics, unit conversion, and every base
constraint it replaces. Optional platform allocation uses the common estimate object. A
manufacturing link can declare
`require_source_coverage`; the source result must name those resource kinds as absorbed, and every
matching base constraint must be included in the replacement list. A system-assembly link uses
`require_source_coverage_selectors` with exact stage and resource-kind pairs. Its required set must
equal the source coverage, and every matching base constraint must be removed. A configured assembly
source cannot be consumed without one such handoff.

The linker requires a common quarter, later transaction time, matching platform topology, unique
constraint replacements, complete required-coverage replacement, and valid evidence references. A
v1 recipe records that source P10, P50, and P90 become triangular low, mode, and high parameters. A
v2 recipe additionally pins one draw CSV and expected count per source. It requires contiguous
zero-based draw indexes and finite nonnegative values and recomputes the linked metric's P10, P50,
P90, mean, minimum, and maximum against the frozen result. Repeated links to one source metric reuse
one permuted tuple. Separate deterministic permutations preserve each source marginal and
within-source row structure but assume no measured cross-source dependence.

`ai-supply-linked-chain-release.v2` copies all source draw files byte for byte and emits
`chain_draws.csv` for every constraint, stage, and physical output. The manifest pins source-draw
hashes, chain-draw fields, and count. A recipe can clear market views when a scope transition makes
them invalid.

See [the linked-chain contract](linked-chain.md) for the checked source-to-site transition.

## SEC filing-event objects

`ai-supply-sec-filings-watch.v1` declares inclusive filing dates, watched SEC form names, and unique
entity IDs and ten-digit CIKs. `ai-supply-sec-filings.v1` records normalized selected accessions and
the exact hash and byte count of each per-CIK submissions source. The adapter rejects mismatched CIKs,
unequal recent-filing columns, duplicate accessions, unsafe primary-document paths, and a requested
window that needs an uncaptured supplemental history file.

`ai-supply-sec-filings-release.v1` preserves the watch and raw source bytes, JSON and CSV events, and
a predecessor-relative addition set. When additions exist, it emits an `ai-supply-ingest-pack.v1`
whose claims are accession-stable disclosure events with `capacity_basis: not_capacity`. Existing
metadata must match the hash-verified predecessor; corrections fail closed for reviewed revision.

`ai-supply-sec-filing-selection.v1` pins that event-release manifest and selects unique accessions
with review reasons and optional expected document hashes. `ai-supply-sec-filing-documents-release.v1`
then preserves each exact SEC primary document plus the source manifest, selection, review queue,
dashboard, and full hash manifest. Document capture creates evidence bytes, not an extracted numeric
claim.

`ai-supply-sec-filing-text-index.v1` pins a filing-document manifest plus unique literal terms,
context length, and a per-term hit cap. `ai-supply-sec-filing-text-release.v1` copies exact raw
documents, writes deterministic normalized visible text, and records each literal match with offsets
into that text. Script and style content is excluded, unsupported media or encoding fails, and
truncated hits remain counted. The index is a review queue, not claim extraction.

`ai-supply-sec-reviewed-claims.v1` pins a text-release manifest, reviewer, transaction time, and one
common-ledger claim object per exact normalized-text interval. The author cannot supply evidence;
`ai-supply-sec-reviewed-claims-release.v1` attaches the pinned raw filing, copies the corresponding
normalized text, validates the common claim schema, and emits a directly ingestible pack. Review
time cannot precede retrieval, and all source, text, and release hashes are rechecked. The exact
anchor audits source location but does not validate interpretation or make a claim eligible as a
model input.
See [the SEC filing-event adapter](sec-filings-adapter.md).

## Revision alert object

`ai-supply-revision-alerts.v1` compares two frozen results with the same scenario ID and result
format. The current `recorded_at` cannot precede the prior result, and changed content needs a later
transaction timestamp. Each alert has a deterministic ID, type, severity, stable result path, and
the prior and current values needed to audit the trigger.

Version 1 detects added or removed estimates, unit and posture changes, current bases outside prior
ranges, median output changes above a configured relative threshold, changed binding constraints,
and bottleneck probability changes above a configured absolute threshold. The release includes JSON,
CSV, a dashboard, source-result lineage, and a hash manifest.

## Source snapshot and claim-revision objects

An ingest pack hash-pins exact content files and labels each capture as raw source, normalized
observation, structured export, or model result. Content paths must stay under the pack directory,
retrieval time cannot follow transaction time, and every claim must cite at least one source
snapshot with an evidence role and independence group.

Claim valid time uses an inclusive `valid_from` and exclusive `valid_to`. `recorded_at` is the
transaction time shared by the pack. A new revision must supersede the latest revision for that key
at a strictly later transaction time. Retractions append a null-valued revision rather than deleting
history. One SQLite transaction covers every source, revision, evidence edge, and ingest-run row.

Each claim includes structured dimensions for entity scope, geography, period, production stage,
capacity basis, and quantity semantics. Product, process node, customer, technology, and qualifier
are optional dimensions. They participate in revision identity and downstream compatibility checks.

`ai-supply-claim-snapshot.v1` returns the latest asserted revision valid on a date and known by a
timestamp. `ai-supply-claim-diff.v1` compares two known-time cutoffs for one valid date. See the
[claim-ledger contract](claim-ledger.md) for commands and failure rules.

`ai-supply-claim-cycle.v1` fixes the valid date, baseline known time, minimum interval, ordered pack
paths, and expected pack hashes for one scheduled job. Its checkpoint identifies the last frozen
snapshot and every processed pack hash. Cycle releases retain exact inputs, both snapshots, the diff,
notification event IDs, and a hash manifest.

The notification outbox stores `ai-supply-notification.v1` payloads with pending, delivered, or
acknowledged state. The same alert payload always maps to the same event ID. Local JSONL delivery is
at least once and relies on event-ID deduplication after a crash between sink flush and status update.

## Manufacturing claim selection

`ai-supply-manufacturing-claim-selection.v1` pins a claim snapshot hash, valid and known cutoffs,
revision ID, expected claim dimensions, allowed postures, target path, target dimensions, and unit
conversion. `constraint_input` requires exact target-dimension compatibility and a numeric point or
low/base/high range. `scale_control` and `directional_signal` require an explicit nonbinding rationale
and never emit a constraint estimate. See the [manufacturing claim gate](manufacturing-claim-gate.md).

`ai-supply-manufacturing-target-catalog.v1` independently fixes a source-scenario input path, unit,
and required claim dimensions. `ai-supply-manufacturing-evidence-coverage-recipe.v1` pins that
catalog, a complete manufacturing release, and ordered claim cases. The resulting
`ai-supply-manufacturing-evidence-coverage.v1` retains every synthetic input and gate decision while
marking all source replacements false. See the
[manufacturing evidence-coverage contract](manufacturing-evidence-coverage.md).

`ai-supply-manufacturing-revision-recipe.v1` pins a frozen source scenario, the independent target
catalog, a later as-of and transaction time, and one or more snapshot-selection pairs. Each pair
also supplies the evidence kind, title, and optional excerpt needed to carry immutable snapshot
metadata into the scenario evidence ledger.

Only an exact-scope `constraint_input` assessment may enter a revision, and only when the selected
source estimate is synthetic. The target path, dimensions, and normalized unit must match the
catalog. The resulting `ai-supply-manufacturing-revision-result.v1` preserves the previous and
revised estimate, claim revision, source snapshot IDs, input hashes, and whether numeric values
changed. Its manufacturing release contains the complete predecessor and claim lineage. See the
[manufacturing evidence-replacement contract](manufacturing-revision.md).

## Supplier earnings bridge

`ai-supply-earnings-bridge.v1` hash-pins one physical manufacturing result and maps selected physical
metrics through supplier attribution, component conversion, inventory, recognition timing, price,
FX, and gross margin. Each company adds a rest-of-company bridge, expenses, tax, diluted shares,
same-quarter consensus, a dated market snapshot, and explicit opportunity diligence fields.

The result exposes probabilistic company financials, deterministic bear/base/bull cases, consensus
discrepancies, and a long/short research rank. Synthetic source or financial inputs force
`wait_for_proof`. See the [supplier earnings bridge](earnings-bridge.md).

## Reported-guidance backtests

`ai-supply-guidance-backtest-case.v1` pins one
`ai-supply-reported-guidance-observation.v1` and one
`ai-supply-reported-outcome-observation.v1` by relative path and SHA-256. The case fixes entity,
fiscal period, as-of date, transaction timestamp, and an ordered metric selection. Both observations
must match that identity exactly. Selected metric label, class, accounting basis, and unit must also
match.

Guidance must be published before period end; the outcome must be published after period end and by
the case as-of date. Retrieval must follow publication, capture must follow retrieval, and capture
must not follow the case transaction timestamp. `management_range` retains low, midpoint, and high;
`approximate_point` requires identical values.

`ai-supply-guidance-backtest-result.v1` reports range coverage, midpoint-minus-actual error,
actual-to-midpoint ratio, interval miss, and a width-normalized error. It never maps management
guidance to P10/P90 and never emits pinball or Brier scores. The benchmark flags are fixed to
`native_model_forecast: false` and `eligible_for_model_calibration: false` because the contract is
for reconstructed external baselines. `ai-supply-guidance-backtest-release.v1` copies the case and
both observations, writes score and evidence CSVs, renders a dashboard, and hashes every file. See
the [reported-guidance backtest contract](guidance-backtest.md).

## Calibration datasets

`ai-supply-forecast-registry.v1` is the pre-outcome side of the calibration lifecycle. It pins one
native linked-chain source release by manifest, result, and raw-draw hashes, then fixes physical
metrics, scope dimensions, quarter-end cutoffs, maturity dates, evidence tests, and optional
threshold events. `ai-supply-forecast-registry-result.v1` recomputes every six-field distribution
from the frozen draw ledger, reports calendar maturity, and exposes zero outcomes and zero scores.
Time alone never makes a registry scoreable. `ai-supply-forecast-registry-release.v1` preserves the
original recipe, path-remapped replay recipe, source release manifest, result, complete draws,
forecast and outcome-contract CSVs, dashboard, and hash manifest. See
[native forecast vintages](forecast-vintages.md).

`ai-supply-forecast-outcome-review.v1` pins a registry release and assigns every frozen forecast one
of `pending`, `observed`, `not_comparable`, or `unobservable`. Observed rows require hash-pinned
evidence and receive interval, pinball, and exact-event scores. Mismatched and unobservable rows keep
their evidence or search rationale but never receive an invented actual. An overdue row cannot
remain pending. `ai-supply-forecast-outcome-review-result.v1` and
`ai-supply-forecast-outcome-review-release.v1` preserve complete disposition coverage, scores,
evidence, registry lineage, and replay paths. See [forecast outcome reviews](forecast-outcomes.md).

`ai-supply-calibration-dataset.v1` lists hash-pinned forecast vintages, evidence, and realized
outcomes as of one recorded timestamp. Version 1 accepts manufacturing results only. Every forecast
selection fixes its relative path below `source_root`, SHA-256, result format, and scenario ID.

An outcome fixes a forecast metric, metric class, period, actual value and unit, posture, observation
date, source family, evidence IDs, method, revision risk, and an optional threshold event. Periods and
units must match the frozen forecast. Non-synthetic quarterly outcomes must be observed after the
quarter ends, use reported or derived posture, and cite publication-dated, content-hashed evidence
from the same source family. Every forecast must be frozen before its outcome, and all evidence must
have been retrieved by the dataset timestamp.

`ai-supply-calibration-result.v1` exposes outcome scores and summaries by metric class and source
family. Only metric classes can propose shared calibration parameters, and not with fewer than ten
outcomes. Overall and source-family summaries remain diagnostic. Even a qualifying proposal is
holdout-only and never eligible for automatic application. Raw errors are aggregated only for
single-unit groups. See [forecast calibration and backtesting](calibration.md).

`ai-supply-calibration-release.v1` preserves the exact dataset and forecast files, outcome and group
CSVs, evidence, dashboard, full result, and a byte-and-SHA manifest. A separate replay dataset changes
only forecast paths so the release can be recomputed in isolation. Exact output replay is idempotent;
different or incomplete existing output is rejected.

## Opportunity object

Each opportunity row supplies numeric factors and the PM diligence fields needed to keep a screen
result from reading like a recommendation:

- actionability;
- variant wedge and what the comparator already reflects;
- why the evidence window matters now;
- first rejection and the proof needed before investment work;
- a thesis-kill condition;
- the next research step.

The engine sets synthetic candidates to `wait_for_proof`.
