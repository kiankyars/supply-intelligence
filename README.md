# AI Supply Intelligence

**Rights:** This repository has no project-wide license. See
[Rights and attribution](RIGHTS.md) before reuse or redistribution.

This package reconciles quarterly AI-system output against the resources needed to produce, ship,
install, and commission complete platforms. A single-platform engine converts every resource into
system-equivalent capacity and takes the binding minimum. A portfolio engine allocates shared pools
across platforms once, then carries each platform's constrained output through later stages. A
manufacturing engine converts logic and HBM wafer starts into binned dies, good stacks, finished
accelerator packages, and complete-system equivalents. A data-center operational engine subtracts
site load and commitments from a hash-pinned gross power envelope, then reconciles power-supported
racks against quarterly commissioning throughput. A chain linker replaces overlapping placeholders
with frozen manufacturing, supplier-resolved system-assembly, and operational results and requires
an explicit allocation when the model narrows from a broader supply flow to one site. Its v2 link
preserves exact hash-pinned source draws rather than refitting source quantiles. The assembly
engine reconciles non-overlapping ODM tray and rack scopes locally, then consumes required component
pools once. An append-only claim ledger stores hash-verified
source snapshots and bitemporal claim revisions, then diffs what was known at two cutoffs.
The supplier earnings bridge carries a frozen physical result through inventory, recognition timing,
company EPS, consensus discrepancies, and a long/short research queue.
The native forecast registry freezes linked-chain distributions, all raw draws, target scopes, and
future outcome tests before period end without attaching an actual or score.
The outcome review requires a pending, observed, scope-mismatched, or unobservable disposition for
every frozen metric and scores only comparable observed evidence.
The calibration layer scores later outcomes against hash-pinned forecast vintages while keeping any
recalibration proposal proof-gated and ineligible for automatic use.
An SEC filings adapter captures official per-CIK submissions feeds, emits accession-stable
`not_capacity` event claims, diffs only genuinely new filings against an immutable predecessor,
preserves explicitly selected primary documents, and builds offset-addressable literal-hit review
indexes. A reviewed authoring gate emits a ledger-ready claim only while its pinned exact text slice
and source hashes still match; the interpretation remains human and subject to downstream scope
gates.

The checked examples use NVIDIA documentation for disclosed GB200 and GB300 rack configurations.
Capacity, yield, demand, allocation, economics, and consensus inputs remain synthetic. All checked
dashboards label those values as demonstration data.

## Run the checked scenario

From this directory:

```sh
python3 -m supply_intelligence validate \
  --scenario examples/gb200-nvl72-illustrative-2026q3.json

python3 -m supply_intelligence reconcile \
  --scenario examples/gb200-nvl72-illustrative-2026q3.json \
  --output-dir releases/2026-07-17-gb200-illustrative
```

Open
[`releases/2026-07-17-gb200-illustrative/dashboard.html`](releases/2026-07-17-gb200-illustrative/dashboard.html)
for the first-read view. The same release includes the scenario, full result JSON, audit CSVs, and a
hash manifest.

Run the shared-resource portfolio:

```sh
python3 -m supply_intelligence validate-portfolio \
  --portfolio examples/gb200-gb300-shared-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-portfolio \
  --portfolio examples/gb200-gb300-shared-illustrative-2026q3.json \
  --output-dir releases/2026-07-17-gb200-gb300-shared-illustrative
```

Open
[`releases/2026-07-17-gb200-gb300-shared-illustrative/dashboard.html`](releases/2026-07-17-gb200-gb300-shared-illustrative/dashboard.html)
to inspect platform allocations, resource utilization, inter-stage inventory, bottleneck
probabilities, and source lineage.

Run the wafer-to-package manufacturing conversion:

```sh
python3 -m supply_intelligence validate-manufacturing \
  --scenario examples/blackwell-wafer-hbm-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-manufacturing \
  --scenario examples/blackwell-wafer-hbm-illustrative-2026q3.json \
  --output-dir releases/2026-07-17-blackwell-manufacturing-illustrative
```

Open
[`releases/2026-07-17-blackwell-manufacturing-illustrative/dashboard.html`](releases/2026-07-17-blackwell-manufacturing-illustrative/dashboard.html)
to trace logic and HBM flows into package output. Product topology comes from NVIDIA and Micron
technical documents. Wafer starts, die geometry, process yields, binning, supplier allocation, and
package capacity remain synthetic, so this release is not an estimate of actual Blackwell output.
TSMC's reported company-wide 2Q26 wafer shipments appear only as a nonbinding scale control. They are
not treated as Blackwell capacity or allocation evidence.

Run the supplier-resolved HBM conversion:

```sh
python3 -m supply_intelligence validate-hbm-suppliers \
  --scenario examples/hbm-suppliers/blackwell-supplier-portfolio-illustrative-2026q3.json \
  --source-root .

python3 -m supply_intelligence reconcile-hbm-suppliers \
  --scenario examples/hbm-suppliers/blackwell-supplier-portfolio-illustrative-2026q3.json \
  --source-root . \
  --include-capacity-draws \
  --output-dir releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws
```

Open the
[`supplier HBM dashboard`](releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/dashboard.html)
to inspect non-overlapping capacity scopes, qualification, allocation, supplier concentration, and
counterfactual criticality. Supplier names exercise a realistic topology, but all supplier capacity,
yield, qualification, allocation, and demand ranges are synthetic. The output is not an estimate of
actual market share, Blackwell production, or HBM tightness.

Replace the aggregate manufacturing HBM branch with that frozen supplier result:

```sh
python3 -m supply_intelligence reconcile-hbm-manufacturing-link \
  --manufacturing-scenario releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence/scenario.json \
  --hbm-result releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/result.json \
  --hbm-capacity-draws releases/2026-07-19-blackwell-hbm-supplier-portfolio-illustrative-v3-draws/capacity_draws.csv \
  --link-recipe examples/hbm-suppliers/blackwell-manufacturing-draw-material-cleared-reticle-geometry-link-illustrative-2026q3.json \
  --include-output-draws \
  --output-dir releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws
```

The [supplier-HBM manufacturing dashboard](releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/dashboard.html)
shows the one-count replacement, source hashes, topology checks, and three-branch minimum. Its
canonical manufacturing result also feeds the checked
[assembly-to-site continuation](releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative/dashboard.html).
The draw-level link preserves the source HBM tails and within-draw supplier allocation, but does not
assert dependence with logic or packaging. Package starts are explicitly defined as material-cleared,
so interposer and substrate placeholders are removed rather than counted again. That scope remains a
synthetic definition, not capacity evidence. `manufacturing_draws.csv` retains every finished-package
and complete-system draw for the downstream chain. See the
[link contract](docs/hbm-manufacturing-link.md).

Run the supplier-resolved ODM and component assembly conversion:

```sh
python3 -m supply_intelligence validate-system-assembly \
  --scenario examples/system-assembly/gb200-nvl72-odm-assembly-illustrative-2026q3.json \
  --source-root examples/system-assembly

python3 -m supply_intelligence reconcile-system-assembly \
  --scenario examples/system-assembly/gb200-nvl72-odm-assembly-illustrative-2026q3.json \
  --source-root examples/system-assembly \
  --output-dir releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative
```

The [assembly dashboard](releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/dashboard.html)
shows local compute-tray-versus-rack reconciliation for three generic ODM scopes, six component
pools, shadow capacity, and exact stage-scoped coverage. NVIDIA topology is hash-pinned; every
throughput, yield, qualification, allocation, component-capacity, and demand range is synthetic.
See the [system-assembly contract](docs/system-assembly.md).

Run the gross-to-net power and commissioning conversion:

```sh
python3 -m supply_intelligence validate-datacenter-operational \
  --gross-import examples/datacenter-openai-abilene-operational-2026q3-import.json \
  --scenario examples/datacenter-openai-abilene-net-operational-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-datacenter-operational \
  --gross-import examples/datacenter-openai-abilene-operational-2026q3-import.json \
  --scenario examples/datacenter-openai-abilene-net-operational-illustrative-2026q3.json \
  --include-capacity-draws \
  --output-dir releases/2026-07-19-abilene-operational-illustrative-v2-draws
```

Open
[`releases/2026-07-19-abilene-operational-illustrative-v2-draws/dashboard.html`](releases/2026-07-19-abilene-operational-illustrative-v2-draws/dashboard.html)
to audit the gross-to-net bridge, power-versus-commissioning bottleneck probability, shadow capacity,
and source lineage. NVIDIA's approximate 120 kW NVL72 rack power is reported. Every Abilene load,
reservation, allocation, compatibility, and commissioning input remains synthetic, so this release
is not an estimate of actual site headroom or deployments.

Run the current three-source package-to-assembly-to-site chain:

```sh
python3 -m supply_intelligence validate-linked-chain \
  --base-scenario examples/gb200-nvl72-illustrative-2026q3.json \
  --link-recipe examples/gb200-to-abilene-odm-assembly-draw-linked-reticle-geometry-illustrative-2026q3.json \
  --manufacturing-result releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/result.json \
  --manufacturing-draws releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/manufacturing_draws.csv \
  --assembly-result releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/result.json \
  --assembly-draws releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/capacity_draws.csv \
  --operational-result releases/2026-07-19-abilene-operational-illustrative-v2-draws/result.json \
  --operational-draws releases/2026-07-19-abilene-operational-illustrative-v2-draws/capacity_draws.csv

python3 -m supply_intelligence reconcile-linked-chain \
  --base-scenario examples/gb200-nvl72-illustrative-2026q3.json \
  --link-recipe examples/gb200-to-abilene-odm-assembly-draw-linked-reticle-geometry-illustrative-2026q3.json \
  --manufacturing-result releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/result.json \
  --manufacturing-draws releases/2026-07-19-blackwell-manufacturing-supplier-hbm-linked-illustrative-v6-reticle-geometry-output-draws/manufacturing_draws.csv \
  --assembly-result releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/result.json \
  --assembly-draws releases/2026-07-19-gb200-nvl72-odm-assembly-illustrative/capacity_draws.csv \
  --operational-result releases/2026-07-19-abilene-operational-illustrative-v2-draws/result.json \
  --operational-draws releases/2026-07-19-abilene-operational-illustrative-v2-draws/capacity_draws.csv \
  --output-dir releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative
```

Open
[`three-source chain dashboard`](releases/2026-07-19-gb200-reticle-geometry-supplier-hbm-odm-assembly-to-abilene-draw-linked-illustrative/dashboard.html).
The recipe removes only constraints covered by each frozen source. Stage-scoped assembly coverage
preserves later site installation while preventing tray, NIC, DPU, switch, power-shelf, and cooling
resources from being counted twice. A synthetic complete-rack shipment share creates the site scope
transition. Exact source marginals and within-source row structure survive one deterministic
per-source permutation; the model does not claim cross-source dependence. The release removes market
views that are invalid for that subset.

Compare two frozen results after a new source or assumption revision:

```sh
python3 -m supply_intelligence compare-releases \
  --previous-result path/to/previous/result.json \
  --current-result path/to/current/result.json \
  --output-dir path/to/revision-alerts
```

The comparison alerts on input bases outside prior ranges, changed units or evidence posture,
material median-output revisions, and bottleneck probability shifts. The alert release pins both
source results by hash.

Ingest and query the checked official-source controls:

```sh
python3 -m supply_intelligence ingest-claims \
  --database state/claims.sqlite3 \
  --pack examples/ingestion/2026-07-19-official-controls-pack.json

python3 -m supply_intelligence query-claims \
  --database state/claims.sqlite3 \
  --valid-at 2026-06-30 \
  --known-at 2026-07-19T19:00:00Z
```

The pack stores short normalized observations, their exact hashes, and reported-versus-derived claim
posture. TSMC's company-wide wafer shipments remain a nonbinding scale control; they are not evidence
of Blackwell allocation or capacity. See the [claim-ledger contract](docs/claim-ledger.md).

Assess that source against a product-specific manufacturing target:

```sh
python3 -m supply_intelligence assess-manufacturing-claim \
  --snapshot releases/claim-cycles/official-controls/20260719T190000Z-official-controls-9784ceec7b/current_snapshot.json \
  --selection examples/claim-selections/tsmc-2026q2-shipments-as-blackwell-wafer-starts.json
```

The checked assessment rejects it as a constraint on seven scope dimensions. A separate checked
selection accepts the same claim only as a nonbinding scale control. TSMC backend and tester
shortage statements and Micron HBM4 ramp signals are likewise stored without converting them into
throughput.

Build the checked evidence-coverage release:

```sh
python3 -m supply_intelligence build-manufacturing-evidence-coverage \
  --recipe examples/coverage/blackwell-manufacturing-evidence-coverage-2026-07-19.json \
  --source-root . \
  --output-dir releases/manufacturing-evidence/blackwell-2026q3/20260719T210000Z-blackwell-evidence-coverage
```

Open the
[`manufacturing evidence dashboard`](releases/manufacturing-evidence/blackwell-2026q3/20260719T210000Z-blackwell-evidence-coverage/dashboard.html)
to see the 21 ranked synthetic inputs, one scope-rejected constraint claim, one scale control, and
eight directional signals. The recipe independently pins the target-scope catalog so a selection
cannot redefine a scenario input to make an incompatible claim pass.

Build the first checked evidence replacement without changing the frozen predecessor:

```sh
python3 -m supply_intelligence validate-manufacturing-revision \
  --recipe examples/revisions/blackwell-wafer-format-2026-07-19.json \
  --source-root .

python3 -m supply_intelligence build-manufacturing-revision \
  --recipe examples/revisions/blackwell-wafer-format-2026-07-19.json \
  --source-root . \
  --output-dir releases/2026-07-19-blackwell-manufacturing-wafer-format-evidence
```

The [revised manufacturing release](releases/2026-07-19-blackwell-manufacturing-wafer-format-evidence/dashboard.html)
moves nominal Blackwell logic-wafer diameter from synthetic to derived posture using three
hash-pinned official-source observations. Its numerical value remains 300 mm, all capacity outputs
remain identical, and the evidence queue falls from 21 to 20 synthetic inputs. The separate
[alert release](releases/alerts/2026-07-19-blackwell-wafer-format-evidence/dashboard.html) reports
only that posture change. See the [replacement contract](docs/manufacturing-revision.md).

Stack a bounded reticle-geometry revision on that release:

```sh
python3 -m supply_intelligence build-manufacturing-revision \
  --recipe examples/revisions/blackwell-reticle-geometry-2026-07-19.json \
  --source-root . \
  --output-dir releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence
```

The [reticle-geometry release](releases/2026-07-19-blackwell-manufacturing-reticle-geometry-evidence/dashboard.html)
uses NVIDIA's reticle-limit description and ASML's 26 mm by 33 mm full-field specification to replace
die width and height with derived intervals. It leaves 18 inputs synthetic and raises P50 complete
system equivalents 0.77% versus the wafer-format predecessor. This is a bounded inference, not a
teardown measurement; the [alert release](releases/alerts/2026-07-19-blackwell-reticle-geometry-evidence/dashboard.html)
records the two posture changes.

Run the checked supplier earnings bridge:

```sh
python3 -m supply_intelligence validate-earnings \
  --source-result releases/2026-07-17-blackwell-manufacturing-illustrative/result.json \
  --scenario examples/blackwell-supplier-earnings-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-earnings \
  --source-result releases/2026-07-17-blackwell-manufacturing-illustrative/result.json \
  --scenario examples/blackwell-supplier-earnings-illustrative-2026q3.json \
  --output-dir releases/2026-07-19-blackwell-supplier-earnings-illustrative
```

Open the
[`supplier earnings dashboard`](releases/2026-07-19-blackwell-supplier-earnings-illustrative/dashboard.html)
to audit physical-to-revenue line items, company bear/base/bull cases, consensus gaps, and the ranked
research queue. Real supplier names exercise the topology, but every economics, consensus, price,
valuation, and ranking input is synthetic. All rows remain `wait_for_proof`.

Freeze the checked pre-outcome native forecast:

```sh
python3 -m supply_intelligence validate-forecast-registry \
  --registry examples/calibration/blackwell-linked-chain-native-forecast-registry-2026q3.json \
  --source-root .

python3 -m supply_intelligence build-forecast-registry \
  --registry examples/calibration/blackwell-linked-chain-native-forecast-registry-2026q3.json \
  --source-root . \
  --output-dir releases/forecast-vintages/2026-07-19-blackwell-linked-chain-native-vintage-v2
```

Open the
[`native forecast registry`](releases/forecast-vintages/2026-07-19-blackwell-linked-chain-native-vintage-v2/dashboard.html)
to inspect five Q3 forecasts, their 20,000 exact source draws, pre-registered events, maturity gates,
and future evidence contracts. All forecasts remain `pending_period_end`, with zero outcomes and
zero scores. This is a real pre-outcome native-model freeze, but its source remains synthetic and is
not a market estimate or evidence of model skill. See the
[native forecast contract](docs/forecast-vintages.md) and
[canonical forecast release index](docs/forecast-release-index.md).

Freeze the checked pre-period outcome review:

```sh
python3 -m supply_intelligence validate-forecast-outcome-review \
  --review examples/calibration/blackwell-linked-chain-outcome-review-preperiod-2026q3.json \
  --source-root .

python3 -m supply_intelligence build-forecast-outcome-review \
  --review examples/calibration/blackwell-linked-chain-outcome-review-preperiod-2026q3.json \
  --source-root . \
  --output-dir releases/forecast-outcome-reviews/2026-07-19-blackwell-linked-chain-preperiod
```

The
[`pre-period outcome review`](releases/forecast-outcome-reviews/2026-07-19-blackwell-linked-chain-preperiod/dashboard.html)
covers every frozen metric and correctly emits five pending dispositions, zero evidence records, and
zero scores. A later review cannot leave an overdue metric pending; it must attach a comparable
actual, preserve scope-mismatched evidence without scoring it, or explicitly record unobservability.
See the [outcome review contract](docs/forecast-outcomes.md).

Run the checked calibration scorecard:

```sh
python3 -m supply_intelligence validate-calibration \
  --dataset examples/calibration/blackwell-manufacturing-calibration-synthetic-2026-07-19.json \
  --source-root .

python3 -m supply_intelligence build-calibration-scorecard \
  --dataset examples/calibration/blackwell-manufacturing-calibration-synthetic-2026-07-19.json \
  --source-root . \
  --output-dir releases/calibration/2026-07-19-blackwell-manufacturing-synthetic-scorecard
```

Open the
[`forecast calibration dashboard`](releases/calibration/2026-07-19-blackwell-manufacturing-synthetic-scorecard/dashboard.html)
to inspect interval coverage, bias, quantile loss, threshold-event Brier scores, and source-family
error. The six outcomes are synthetic scoring fixtures, not realized Blackwell production. All
metric classes remain below the minimum history required to propose parameters, while overall and
source-family views are diagnostic only. Proposals are never applied automatically.

Run the checked external-guidance benchmark:

```sh
python3 -m supply_intelligence validate-guidance-backtest \
  --case examples/backtests/micron-fy2026q3-guidance-backtest.json \
  --source-root .

python3 -m supply_intelligence build-guidance-backtest \
  --case examples/backtests/micron-fy2026q3-guidance-backtest.json \
  --source-root . \
  --output releases/backtests/2026-07-19-micron-fy2026q3-guidance
```

Open the
[`Micron FQ3 guidance dashboard`](releases/backtests/2026-07-19-micron-fy2026q3-guidance/dashboard.html)
to compare seven metrics from Micron's March 18 guidance with its June 24 reported results. All
seven outcomes were above the disclosed ranges or approximate points. This is a reconstructed
external benchmark, not a native forecast: the disclosure preceded quarter-end, but the normalized
artifact was captured after the outcome and is permanently ineligible for model calibration.
Management ranges are not probability quantiles, both observations share one company source family,
and financial surprise does not validate physical AI production. See the
[reported-guidance backtest contract](docs/guidance-backtest.md).

Run the checked scheduled cycle with a local durable notification sink:

```sh
python3 -m supply_intelligence run-claim-cycle \
  --job examples/ingestion/official-controls-cycle.json \
  --database state/claims.sqlite3 \
  --outbox state/notifications.sqlite3 \
  --state-dir state/claim-cycles \
  --release-root releases/claim-cycles \
  --run-at 2026-07-19T19:00:00Z \
  --notification-sink state/claim-alerts.jsonl
```

The command is interval-gated and lock-protected, freezes the prior snapshot, writes a hash manifest,
and advances its checkpoint only after the cycle succeeds. JSONL delivery is at least once and uses
stable event IDs for deduplication.

Run the tests with:

```sh
python3 -m unittest discover -s tests -v
```

## Reconciliation model

For resource `r` in Monte Carlo draw `i`:

```text
system_capacity[r, i]
  = nominal_capacity[r, i]
  × effective_yield[r, i]
  × platform_allocation[r, i]
  ÷ units_per_system[r, i]
```

Each stage includes every upstream constraint:

```text
packages → servers → racks → shipped → installed → operational
```

The stage output equals the lowest sampled system capacity among the resources required by that
point. Bottleneck probability measures how often a resource sets that minimum. Estimates that share
a `correlation_group` reuse the same triangular quantile draw.

The engine allocates shipped systems to customer cohorts after applying demand caps. It calculates
supplier revenue and gross profit at the chosen recognition stage, then compares those results with a
separate consensus input. The opportunity table ranks research candidates. It does not approve a
position.

For a portfolio, weighted progressive filling allocates each stage's shared capacity subject to each
platform's BOM and priority weight. The next stage can allocate no more than the prior stage produced.
The policy prevents double counting; its weights do not infer contractual priority.

## Estimate contract

Each numeric input carries:

- low, base, and high values;
- unit and posture: reported, derived, modeled, or synthetic;
- methodology, confidence, and last-updated date;
- one or more evidence IDs;
- evidence that would confirm or falsify the estimate;
- an optional correlation group.

The loader rejects missing evidence, invalid ranges, invalid ratio bounds, unit mismatches, duplicate
IDs, and malformed dates. See [the data contract](docs/data-contract.md) for the full schema.

## Current boundary

The portfolio engine handles multiple platforms and one quarter per scenario. The checked portfolio
shares HBM, packaging, substrates, tray assembly, rack integration, logistics, installation, power,
and commissioning capacity across GB200 and GB300. Those pool sizes and allocation weights are
synthetic. A separate supplier-resolved HBM model now converts non-overlapping supplier wafer pools
through qualification and customer allocation into package equivalents. A hash-pinned replacement
then removes the aggregate HBM branch and carries the supplier pool through manufacturing and the
package-to-site chain. Its checked capacity and allocation inputs are still synthetic and are not
evidence of real supplier output or share.

The [supplier-resolved assembly model](docs/system-assembly.md) now reconciles unique ODM compute-tray
and rack scopes locally before consuming six server/rack component pools. Its standalone release
preserves every draw, and its stage-scoped coverage prevents those modeled resources from surviving
in the three-source chain. Only the NVIDIA topology is sourced; all assembly capacities and generic
ODM identities remain synthetic.

The [data-center atlas](https://github.com/kiankyars/datacenter-atlas) remains the source for
downstream power and commissioning evidence. The
[data-center power bridge](docs/datacenter-adapter.md) now imports pinned site-level critical IT MW
and readiness evidence. It refuses to treat gross campus capacity as vacant or platform-allocated
power. Its checked command uses a directly versioned selected-row fixture, so it runs from a clean
clone without assuming that a sibling Atlas payload exists. The fixture retains the historical
source manifest hash but is not a complete or current Atlas release. The separate
[operational conversion](docs/datacenter-operational.md) now performs the required deductions and
reconciles power-supported racks with commissioning throughput. Its checked site-specific inputs are
synthetic, so it is not yet eligible to replace the portfolio's energized-power or commissioning
pools.

The [semiconductor atlas](https://github.com/kiankyars/semiconductor-atlas) stores upstream facility,
project, capability, capacity-basis, and constraint claims. The strict
[atlas adapter](docs/atlas-adapter.md) imports only explicitly selected, hashed, quarter-total
capacity slices without collapsing announced, installed, qualified, and economically usable bases.
The current open atlas seed has no capacity claims, so the checked portfolio still uses synthetic
manufacturing pools.

The checked manufacturing pack now performs direct wafer, die, HBM stack, package, and system
conversion. It keeps reported product topology separate from synthetic process inputs. A checked,
replay-safe revision has replaced the nominal logic-wafer diameter with a scope-matched derived
claim without changing output. A stacked revision replaces die width and height with bounded derived
reticle-geometry intervals, leaving 18 process and capacity inputs synthetic. The next upstream step
is exact-quarter, capacity-basis-preserving supplier evidence for influential wafer-start, yield,
binning, HBM, and package inputs, plus evidence-backed cross-source dependence beyond the
manufacturing boundary.

The claim ledger now supports atomic, idempotent ingest, strict revision supersession, bitemporal
queries, retractions, source-level diffs, interval-gated cycles, a durable notification outbox, local
JSONL delivery, and acknowledgement state. Structured claim dimensions and the manufacturing gate
now decide whether a selected claim can serve as a constraint, scale control, or directional signal.
It does not autonomously interpret prose, extract XBRL, send to external channels, or perform
controlled historical rebuilds.

The [linked-chain contract](docs/linked-chain.md) can now feed frozen manufacturing,
system-assembly, and site-operational distributions into one minimum-feasible-chain run. It
preserves each source result and draw ledger by hash, rejects topology or summary mismatches, and
records the deterministic independent cross-source permutation. The older v1 quantile-to-triangular
mapping remains replayable for summary-only sources. The checked link remains illustrative because
its site allocation and source throughput inputs are synthetic. Coverage guards require both
absorbed package materials and exact server/rack stage resources to be removed once.

The [native forecast contract](docs/forecast-vintages.md) now freezes five linked-chain metrics and
their complete draw ledger before 2026-Q3 ends. It fixes later outcome scopes and evidence tests but
contains no actuals or scores. The [calibration contract](docs/calibration.md) scores coverage, bias,
pinball loss, and Brier loss only after realized evidence exists. Its checked scorecard outcomes are
synthetic. A separate checked Micron benchmark proves hash-pinned, time-ordered ingestion of real
guidance and reported financial outcomes, but it is an after-outcome external reconstruction and
cannot establish model skill. The new native vintage must mature, and later evidence must match its
scope, before any backtest can run; its synthetic source keeps it ineligible for evidence-backed
calibration.

- [Methodology](docs/methodology.md)
- [Scenario data contract](docs/data-contract.md)
- [Semiconductor Atlas adapter contract](docs/atlas-adapter.md)
- [Data Center Atlas power bridge](docs/datacenter-adapter.md)
- [Gross-to-net power and commissioning contract](docs/datacenter-operational.md)
- [Frozen-result linked-chain contract](docs/linked-chain.md)
- [Source snapshot and bitemporal claim ledger](docs/claim-ledger.md)
- [SEC filing-event ingestion adapter](docs/sec-filings-adapter.md)
- [Manufacturing claim-scope gate](docs/manufacturing-claim-gate.md)
- [Manufacturing evidence coverage](docs/manufacturing-evidence-coverage.md)
- [Manufacturing evidence replacement](docs/manufacturing-revision.md)
- [Supplier-resolved HBM portfolio](docs/hbm-supplier-portfolio.md)
- [Supplier HBM to manufacturing link](docs/hbm-manufacturing-link.md)
- [Supplier-resolved system assembly](docs/system-assembly.md)
- [Supplier earnings and consensus bridge](docs/earnings-bridge.md)
- [Native forecast vintages](docs/forecast-vintages.md)
- [Canonical forecast release index](docs/forecast-release-index.md)
- [Forecast outcome reviews](docs/forecast-outcomes.md)
- [Forecast calibration and backtesting](docs/calibration.md)
- [Reported-guidance historical benchmark](docs/guidance-backtest.md)
- [Build order and coverage gaps](docs/roadmap.md)
