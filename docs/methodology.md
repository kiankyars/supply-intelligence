# Reconciliation methodology

Status: executable single-platform, shared-resource, manufacturing, and data-center operational
specification, 2026-07-19.

## Output boundary

One scenario represents one accelerator platform in one quarter. The platform defines the physical
unit that a customer can receive, such as a rack-scale system. Each constraint states the resource
capacity available during the quarter and the amount consumed by one complete system.

The model publishes six cumulative outputs:

1. accelerator packages produced;
2. complete servers assembled;
3. racks integrated;
4. systems shipped;
5. systems installed;
6. systems operational.

An upstream constraint remains active at each later stage. A rack cannot become operational if the
available HBM supports fewer racks than the commissioning team can accept.

## Capacity conversion

The engine samples four estimates for each resource:

```text
equivalent systems
  = nominal capacity × effective yield × platform allocation ÷ units per system
```

The `capacity_basis` records what the numerator means. A nameplate input requires a yield conversion.
A known-good or sellable output may use an identity yield when the source already includes process
loss. Platform allocation removes capacity reserved for other products or customers.

The input author must keep the units compatible. A constraint with capacity measured in HBM
terabytes must express its BOM requirement in HBM terabytes per system.

## Uncertainty

The first engine uses triangular distributions because public evidence often supports a range and a
most likely point without enough observations for a fitted distribution. Each draw samples the low,
base, and high range. Deterministic claims set all three values equal.

Estimates with the same `correlation_group` use the same triangular quantile in a draw. This mechanism
captures simple positive dependence, such as stronger front-end output and better die yield. It does
not represent a covariance matrix or negative correlation.

The release reports P10, P50, P90, mean, minimum, and maximum from the simulation. The input range
and the output quantiles answer different questions and remain separate in the audit files.

## Binding constraints

For each draw, the engine takes the lowest system-equivalent capacity available by a stage. It gives
the binding resource one bottleneck count. Exact ties split that count among the tied resources.
Dividing counts by the number of draws yields bottleneck probability.

This probability describes the current scenario. It does not measure the chance that the underlying
input assumptions are correct. Input confidence stays attached to the estimate record.

## Customer allocation

The engine samples a share and demand ceiling for each customer cohort. It assigns shipped systems
in proportion to sampled shares, caps customers at sampled demand, and redistributes residual supply
across customers that still have demand. Any remaining systems appear as `unallocated`.

The current algorithm does not model delivery priority, contractual seniority, export licenses,
regional substitution, or customer-specific platform variants.

## Shared-resource portfolio allocation

A portfolio starts with sampled demand and a sampled priority weight for every platform. At each
stage, weighted progressive filling raises platform output together until demand is met or a shared
resource is exhausted. Resource use equals platform output multiplied by that platform's sampled BOM
requirement. A platform blocked by one pool leaves residual capacity available to platforms that do
not consume that pool.

The output of one stage becomes the demand ceiling for the next:

```text
quarterly demand
  → package-constrained systems
  → server-constrained systems
  → rack-constrained systems
  → shipped
  → installed
  → operational
```

This sequencing preserves resource conservation and exposes holdback inventory between stages. It
does not infer product allocation from public evidence. Priority weights must carry their own source,
method, uncertainty, and falsification test.

## Direct wafer, die, HBM, and package conversion

The manufacturing engine starts with separate logic and HBM wafer flows. It approximates rectangular
gross dies per circular wafer as:

```text
usable diameter = wafer diameter - 2 × edge exclusion
effective die area = (die width + scribe) × (die height + scribe)

gross dies per wafer
  = π × (usable diameter / 2)² / effective die area
  - π × usable diameter / sqrt(2 × effective die area)
```

The edge-loss term is analytical. The model does not simulate an exact reticle stepping grid,
partial dies, layout phase, redundancy, or product-specific keep-out zones.

Logic random-defect yield uses a negative-binomial model:

```text
defect yield
  = (1 + defect density × die area in cm² / clustering alpha)^(-clustering alpha)

binned logic dies
  = wafer starts
  × gross dies per wafer
  × defect yield
  × wafer-sort yield
  × performance-bin share
```

HBM stays as a separate physical path:

```text
good HBM stacks
  = wafer starts
  × gross memory dies per wafer
  × known-good-die yield
  ÷ memory dies per stack
  × stack-assembly yield
  × stack final-test yield
```

Each branch is converted into accelerator-package equivalents. Package attempts equal the minimum
of binned-logic, good-HBM-stack, and advanced-package-start equivalents. Final package yield converts
attempts into finished accelerator packages, which are divided by accelerators per system. The
engine retains unused binned dies and good HBM stacks as shadow capacity and counts how often each
branch binds across Monte Carlo draws.

### Supplier-resolved HBM

The separate HBM supplier engine decomposes the aggregate memory branch before package assembly.
Each supplier owns one unique capacity scope, so wafer starts are consumed once. Supplier-compatible
starts pass through known-good-die, stack-assembly, final-test, platform-qualification, and
customer-allocation stages. Starts explicitly declared as already platform allocated must use
qualification and allocation shares of one, preventing double discounting.

The engine sums only customer-allocated stacks, divides by stack placements per accelerator, and
compares those package equivalents with platform demand. It retains unqualified stacks, qualified
stacks allocated elsewhere, and unused customer reservations separately. Per-draw allocated-stack
shares produce concentration HHI and largest-supplier share. Supplier criticality is a
counterfactual: the fraction of draws in which removing that supplier leaves package demand
uncovered. It measures modeled dependency, not a mutually exclusive allocation of bottleneck risk.

The checked supplier scenario uses reported topology and supplier-specific Micron wafer evidence
only within their documented scopes. All supplier production, yield, qualification, allocation, and
demand inputs remain synthetic, so the reported shares and shortage probabilities are diagnostics of
the scenario rather than market estimates.

The supplier-to-manufacturing adapter removes the aggregate HBM wafer flow before importing the
supplier portfolio's customer-allocated stack distribution. It verifies the source hashes, quarter,
recording order, capacity-scope uniqueness, and all stack-topology fields. Package attempts then take
the minimum of logic package equivalents, imported allocated stacks divided by placements per
accelerator, and package assembly starts. The old aggregate HBM inputs are neither sampled nor
reported in the linked result.

The current draw-level adapter verifies and imports every HBM capacity draw. A deterministic
permutation preserves the full HBM marginal and supplier allocation inside each draw without
claiming that the source draw index shares a random state with logic or packaging. The older v1
adapter remains replayable and maps P10, P50, and P90 to triangular low, mode, and high, truncating
tails. Neither adapter establishes real cross-branch dependence; that requires common causal factors
or an explicitly estimated copula.

### Supplier-resolved system assembly

The system-assembly engine keeps compute-tray and rack-integration scopes separate for each ODM.
Yield, platform qualification, and customer allocation are applied at each stage unless the declared
capacity basis is already net of them. One supplier's supported rack output is the local minimum of
its allocated tray equivalents and allocated rack-integration output. Only those local minima are
summed, so spare capacity is not assumed transferable across ODM factories.

The resulting ODM pool meets each required customer-allocated component pool in one global minimum.
The checked component set covers ConnectX-7 NICs, BlueField-3 DPUs, NVLink switch trays, management
switches, power shelves, and rack-side cooling integration. Unused trays, rack slots, and components
remain visible as shadow capacity. Per-draw contribution shares produce an ODM HHI, while local and
global bottleneck probabilities distinguish factory flow from a component shortfall.

Complete-rack coverage uses `(stage, resource_kind)` selectors rather than resource kind alone. This
keeps factory rack integration distinct from later site installation. The checked scope declaration
is synthetic: it prevents the same server and rack resource from constraining the chain twice, but
does not establish real supplier throughput. Exact assembly draws remain in the standalone release
and now pass through the v2 full-chain boundary without a quantile refit.

Reported product topology does not by itself validate process inputs. In the original checked
Blackwell pack, wafer starts, die dimensions, defect density, yields, binning, HBM allocation, and
package starts are synthetic. A later reviewed revision changes die width and height to derived
intervals by combining NVIDIA's reticle-limit description with ASML's standard maximum exposure
field. Those intervals are not measured die dimensions; the remaining production inputs stay
synthetic. The outputs demonstrate the conversion and audit chain, not actual supplier production.

Reported external totals can be attached as scale controls. The checked pack compares modeled
Blackwell logic wafer starts with TSMC's reported total 12-inch-equivalent wafer shipments for the
prior quarter. That comparison can expose an impossible order of magnitude, but it cannot allocate
wafer shipments by node, customer, or product. A control marked as unusable for product capacity does
not constrain or replace any scenario input.

The manufacturing release also ranks synthetic inputs for evidence replacement. The score multiplies
current-run influence by one minus input confidence. Branch inputs use the probability that their
branch binds package attempts; final assembly yield has full influence because it applies to every
attempted package. This score orders research inside one scenario. It does not estimate whether an
input is wrong, and a zero score does not prove that a source gap is immaterial in another scenario.

The evidence-coverage audit joins that ranked queue to frozen claim-gate assessments. Constraint
claims must also match a separately hash-pinned target catalog; scale controls and directional
signals remain outside numeric coverage. The audit reports candidate eligibility but never mutates
the frozen manufacturing scenario, so a reviewed scenario revision is still required before any
replacement can affect output.

The manufacturing revision layer performs that reviewed step. It accepts only a gate-passing claim
whose path, dimensions, and unit match the independent catalog and whose predecessor estimate is
synthetic. It writes a new scenario at a later transaction time and retains the exact predecessor,
claim snapshot, selection, and target catalog. A posture-only replacement is still meaningful:
frozen-result comparison should report the provenance change while numerical output and bottleneck
probability remain unchanged.

## Upstream atlas imports

The Semiconductor Atlas adapter verifies release hashes and imports only capacity claims explicitly
named by a selection file. It preserves the selected atlas capacity basis and follows claim
dependencies to source evidence. Multiple claims are summed only under an explicit non-overlap
rationale and attribution basis.

Reconciliation capacity is a flow during a quarter. A forecast of capacity available at quarter end
is a point-in-time state. The adapter treats those as different quantities and accepts a forecast only
when the upstream release exports `quarter_total` output with a pinned vintage and parameter hash.

## Downstream power envelopes

The Data Center Atlas bridge imports critical IT MW only for explicitly selected sites and stages. It
checks release hashes, source freshness, target dates, site scope, user labels, and readiness
evidence. The summed range remains a gross site envelope.

The operational engine now performs the next conversion explicitly:

```text
residual compatible MW
  = max(0, gross critical IT MW
           - current load
           - contracted reservations
           - other-platform commitments
           - rack-incompatible capacity)

power-supported racks
  = residual compatible MW × target-platform share ÷ rack critical-IT MW

operational racks
  = min(power-supported racks,
        target-quarter commissioning slots × completion ratio)
```

The four deductions need a non-overlap rationale to prevent silent double subtraction. The engine
reports both power and commissioning bottleneck probabilities, target MW stranded by commissioning,
completed commissioning throughput stranded by power, and draws in which deductions consume the
gross envelope.

This executable conversion is not evidence that site-specific inputs exist. The checked Abilene run
uses NVIDIA's reported approximate rack power but synthetic load, reservations, other-platform
commitments, rack compatibility, target share, commissioning slots, and completion ratio. It remains
ineligible for use as a portfolio capacity pool until those values are replaced with operator or
equivalent evidence.

## Frozen-result chain linking

The linked-chain engine replaces base constraints already represented by frozen source results. In
the current checked run, the direct manufacturing result defines assembly starts as material-cleared:
each start already has its required silicon interposer and package substrate issued. Its coverage
declaration names those absorbed resource kinds, and the linker requires every matching base
constraint to be removed alongside the logic-die, HBM, and package-throughput placeholders. This
prevents double counting; it does not provide independent interposer or substrate capacity evidence.
If assembly starts were tool-slot or theoretical-throughput capacity before material issue, those
constraints would instead remain separate. The site-operational link replaces separate power and
commissioning placeholders because its source already takes their minimum.

The current three-source continuation also imports component-cleared complete racks. Its
stage-scoped coverage must exactly match the assembly result and removes the modeled tray, NIC, DPU,
switch, power-shelf, and rack-cooling placeholders. Site installation remains because it occurs at a
later stage. A second use of the same complete-rack metric applies the selected-site shipment share,
so the scope transition is based on finished racks rather than upstream package capacity.

The manufacturing result covers a broader illustrative supply flow, while the operational result
covers one selected campus. A shipped-stage allocation constraint creates the required scope
transition:

```text
selected-site shipment capacity
  = frozen complete-rack capacity × selected-site allocation share
```

The selected-site share is synthetic in the checked run. Supplier economics, consensus, opportunity
ranking, and generic customer allocations are removed rather than applied to a mismatched scope.

The v2 linker requires raw source draws. It verifies each selected metric's P10, P50, P90, mean,
minimum, and maximum against the frozen result, then applies one deterministic permutation per
source engine. Multiple links to the same source reuse the same permutation, preserving the source
marginal, point masses, tails, and within-source row dependence. Separate source permutations avoid
assuming that independently generated row indexes share random state. They are nevertheless an
independence policy, not evidence of cross-engine causal dependence; common causal factors or an
estimated dependence model remain future work.

The v1 linker remains replayable for summary-only sources. It maps source P10, P50, and P90 to
triangular low, mode, and high and coordinates repeated metrics with a correlation group. That
mapping preserves a central range but discards source tails, point masses, and full dependence.

## Supplier economics

Each supplier line selects a recognition stage, units consumed per system, revenue per unit, and gross
margin. The engine multiplies those inputs within each draw. It aggregates multiple revenue lines for
the same supplier and ticker.

The consensus comparator uses a separate sourced range. The research score equals:

```text
absolute revenue revision
  × confidence
  × liquidity
  × timing
  × catalyst strength
```

The score orders research work. A candidate still needs current price, valuation, positioning,
downside, and a source-backed earnings bridge before an investor can underwrite a trade.

The dedicated earnings engine now provides that bridge structure. It hash-pins a manufacturing
result, converts physical units through attribution, inventory, recognition share, price, FX, and
gross margin, then adds rest-of-company revenue, expenses, tax, and diluted shares. Consensus remains
a separate dated comparator. Named bear/base/bull cases hold consensus fixed, while the probabilistic
engine samples both model and comparator ranges.

Its research rank multiplies absolute EPS discrepancy by confidence, evidence readiness, liquidity,
catalyst proximity, and downside resilience. Direction is descriptive, not prescriptive. Synthetic
source or market inputs force `wait_for_proof`, and the engine does not emit a price target.

## Forecast calibration

Calibration joins each realized outcome to one hash-pinned forecast metric frozen before the outcome
was observed. Evidence-backed outcomes require reported or derived posture, publication-dated and
content-hashed evidence, and a source-family match across every cited record. The engine reports
inclusive P10-to-P90 coverage, P50-minus-actual bias, P10/P50/P90 pinball loss, and optional threshold-
event Brier loss. Event probabilities use a documented triangular approximation with the three
reported quantiles as low, mode, and high; this loses tails and dependence and is not a substitute
for retained forecast draws.

Overall, metric-class, and source-family views use normalized errors for cross-unit comparison. Raw
errors appear only when a group shares one unit. Source-family grouping makes correlated evidence
errors visible instead of presenting syndicated observations as independent calibration wins.

An explicitly defined metric class needs at least ten outcomes before the engine calculates a median
actual-to-P50 multiplier and a non-narrowing P80 error-width multiplier. Overall and source-family
aggregates stay diagnostic so heterogeneous metrics never inherit one shared multiplier. Every
proposal requires a separate holdout and remains ineligible for automatic application. The checked
scorecard uses synthetic outcomes solely to verify this contract.

## External reported-guidance benchmark

A separate historical adapter scores company guidance against the later reported quarter. It keeps
metric basis and units fixed, requires guidance publication before period end and outcome publication
after period end, and pins both normalized observations by hash. Range coverage and midpoint error
are descriptive. Management ranges are not interpreted as P10/P90, so the adapter does not calculate
pinball or Brier scores.

This adapter does not backfill a native model prediction. Its result always records
`native_model_forecast: false` and `eligible_for_model_calibration: false`. The checked Micron case
was normalized after the outcome and uses one dependent company source family; it establishes a
replayable financial-outcome ingestion path only. Supplier financial surprise cannot validate
Blackwell units, HBM allocation, physical bottlenecks, or operational deployments.

## Audit requirements

Each estimate includes its method, evidence, update date, confidence, and observable confirm/falsify
tests. The release copies those inputs into `result.json` and `input_estimates.csv`. `evidence.csv`
preserves URLs, publishers, source families, publication dates, and retrieval times. `manifest.json`
records the byte length and SHA-256 digest of every release file.

The engine preserves synthetic values so reviewers can test the computation. The dashboard warns
readers before showing them.

## Source snapshots and claim time travel

The claim ledger separates immutable source capture from claim interpretation. A content digest and
retrieval timestamp identify the evidence available to an ingest run. A claim revision adds valid
time, transaction time, posture, scope, unit, method, confidence, and observable confirm/falsify
tests. Independence groups describe evidence lineage; they are not a numerical confidence model.

Queries apply two cutoffs:

```text
claim is visible
  = valid_from <= valid_at < valid_to, when valid_to exists
  and recorded_at <= known_at
  and the latest eligible revision is asserted
```

The ledger therefore reconstructs what the system would have returned before a later correction or
retraction. It does not convert a reported company total into product capacity. Capacity-basis,
allocation, quarter-flow, and model-compatibility checks remain the responsibility of downstream
adapters.

The manufacturing claim gate performs those compatibility checks explicitly. It compares entity,
period, stage, capacity basis, quantity semantics, product, node, customer, geography, posture, and
unit before emitting a constraint estimate. Nonbinding controls and qualitative signals remain
queryable but cannot enter the minimum-feasible-output calculation.

## Revision and bottleneck alerts

The alert engine compares two frozen results from the same scenario. It walks input estimates by
stable owner ID rather than list position. A range-breach alert fires when the new base falls outside
the prior low-to-high interval. Output alerts compare medians and bottleneck alerts compare both the
top binding constraint and absolute probability changes.

Defaults are a 10% relative change in output median and a 15 percentage-point change in bottleneck
probability. The release stores both thresholds and hashes both source result files. Alert severity
orders review work; it is not an investment recommendation or a probability that the new result is
correct.

Source-level claim diffs use the same separation of detection from judgment. They report added,
revised, or removed claims between transaction-time cutoffs and include both versions with evidence
metadata. A scheduled cycle compares against the prior release's hash-verified frozen snapshot,
rather than re-querying an old cutoff after new data arrives. This makes late backfills visible and
prevents a scheduled job from silently rewriting its previous view.

Notification events enter a durable local outbox. JSONL delivery flushes the event before marking it
delivered, which chooses at-least-once behavior over silent loss. Event IDs support downstream
deduplication. Acknowledgement records review state; it does not automatically rerun a scenario or
notify an external channel.
