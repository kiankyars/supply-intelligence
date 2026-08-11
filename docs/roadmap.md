# Build order and coverage gaps

The first release proves the scenario contract, reconciliation math, audit bundle, and dashboard. The
following work converts the demonstration into a global production model.

## 1. Shared-resource portfolio solver: executable foundation complete

The portfolio engine now allocates shared pools across platforms once per Monte Carlo draw and
preserves stage-specific holdback inventory. The checked GB200 and GB300 pack covers aggregate HBM,
packaging, interposers, substrates, ODM tray assembly, rack components, cooling, logistics,
installation, power, and commissioning. Its capacity, demand, yield, and priority ranges are
synthetic.

Next, replace progressive-allocation weights with source-backed reservations where evidence exists,
add customer and regional partitions, and extend the platform set:

Initial platform set:

- NVIDIA GB200 and GB300 rack variants;
- NVIDIA B200 and B300 HGX or partner systems;
- AMD MI350-series platforms;
- Google TPU and Amazon Trainium systems where public BOM evidence supports a model;
- major Chinese accelerator platforms with a separate export-control and evidence posture.

## 2. Manufacturing evidence packs

Replace the checked synthetic ranges in this order:

1. TSMC leading-edge wafer allocation, gross die per wafer, defect density, and sellable bin mix;
2. HBM wafer starts, stack configuration, known-good-die yield, stack yield, and supplier allocation;
3. CoWoS and other packaging lines by process, interposer size, tool set, and qualified output;
4. ABF substrates, thermal materials, connectors, power shelves, NICs, DPUs, switches, optics, and cables;
5. ODM assembly, rack qualification, freight, installation, and commissioning.

Each pack needs source-specific rights, bitemporal claim history, and a source-family identifier so
syndicated reports do not count as independent evidence.

Use the repository's `semiconductor_atlas` claim store for facility, project, production-unit,
capability, capacity-basis, and constraint history. The reconciliation adapter should accept only the
forecast vintage and capacity basis selected for a run.

The consumer-side adapter contract is now executable. It verifies atlas release hashes, preserves
capacity bases, requires explicit claim selection, and rejects the atlas's current end-of-quarter
capacity forecast as a substitute for quarterly output. The next upstream requirement is a
manifest-pinned `quarterly_output_forecast.csv` or exact-quarter canonical output claims.

## 3. Direct wafer and HBM stack math: executable foundation complete

The checked manufacturing pack now converts logic and HBM wafer starts through gross die geometry,
negative-binomial logic yield, wafer sort, performance binning, HBM known-good-die yield, stack
assembly, stack final test, advanced-package starts, and final package yield. It reports finished
accelerator packages, complete-system equivalents, shadow inventory, and binding probability.

The product topology is reported or derived from primary technical documents. The capacity,
geometry, allocation, and process-yield inputs remain synthetic. Before treating the output as a
market estimate, replace those ranges with supplier evidence, add package cross-sections and
supplier-specific HBM BOMs, model reticle stepping and repair, and reconcile the resulting package
output into the shared-resource portfolio.

The claim ledger now stores structured scope, geography, period, stage, capacity-basis, and
quantity-semantics dimensions. The strict manufacturing gate demonstrates that TSMC's 2Q26
company-wide wafer shipments fail seven dimensions required for 2026-Q3 Blackwell wafer starts,
while remaining valid as a nonbinding scale control. Current TSMC backend and tester shortage
disclosures and Micron HBM4 ramp signals have been ingested as directional evidence, not fabricated
throughput.

The release emits `evidence_gaps.csv`, which ranks the remaining synthetic inputs by current-run
output influence and confidence. This is a sourcing queue, not proof that low-ranked inputs are
correct.

The checked evidence-coverage release now joins that queue to ten frozen claim assessments and an
independent target-scope catalog. It reports zero applied replacements, one rejected constraint
test, one accepted scale control, and eight accepted directional signals. This makes the evidence
boundary executable and visible; it does not supply the still-missing product-quarter quantities.

The first reviewed replacement is now executable and checked. A hash-pinned claim combines NVIDIA's
Blackwell 4NP disclosure with TSMC's 12-inch and 300 mm manufacturing disclosures to replace the
nominal logic-wafer diameter's synthetic posture. The revision preserves the original release,
reduces the sourcing queue from 21 to 20 inputs, and leaves all numerical outputs unchanged. The
stacked reticle-geometry revision then combines NVIDIA's reticle-limit description with ASML's
26 mm by 33 mm full-field specification to replace width and height with explicitly derived,
falsifiable intervals. It leaves 18 synthetic inputs and raises median complete-system equivalents
by 0.77%; it is not a teardown measurement. The remaining high-influence gaps are package assembly
yield and the logic wafer-start, edge/scribe, defect-density, sort-yield, and performance-bin inputs;
no public directional statement is promoted to a numeric capacity or yield range for those fields.

The supplier-resolved HBM foundation is also executable. It assigns SK hynix, Micron, and Samsung
distinct capacity scopes, keeps platform qualification separate from customer allocation, conserves
shadow stacks, and reports concentration and counterfactual supplier criticality. Exact normalized
source bytes are hash-pinned. The checked supplier capacities, yields, allocations, and demand remain
synthetic. The checked link now removes the aggregate HBM branch, imports this frozen result once,
and carries the canonical manufacturing output into the package-to-site chain. Its draw contract
preserves the exact HBM marginal and within-draw supplier allocation. The current package-start basis
explicitly absorbs interposers and substrates, and the chain linker removes those placeholders or
fails closed; this prevents double counting but leaves their direct capacities as evidence gaps.
With those duplicate placeholders removed, server and rack assembly became the next upstream
bottlenecks; the supplier-resolved foundation in the next section now models that handoff explicitly.
Exact manufacturing output draws now propagate through the generic full-chain solver. The remaining
distribution gap is evidence-backed cross-branch dependence rather than marginal preservation. The
next evidence step remains real, exact-quarter supplier capacity, yield, qualification, and
customer-allocation sourcing, followed by direct packaging-material and server/rack throughput
evidence.

## 4. Supplier-resolved server and rack assembly: executable foundation complete

The assembly engine now assigns unique compute-tray and rack-integration scopes to each ODM, applies
yield, platform qualification, and customer allocation at both stages, and reconciles them locally
before summing supplier output. It then consumes six non-overlapping component pools once: NICs,
DPUs, NVLink switch trays, management switches, power shelves, and rack-side cooling integration.
Every draw and unused tray, rack slot, or component remains in the release.

Hash-pinned NVIDIA documentation supports the DGX GB200 NVL72 BOM topology. The generic ODM labels
and all capacity, yield, qualification, allocation, component, and demand ranges are synthetic. The
checked run's median 299 complete racks and 98.26% ODM bottleneck probability are diagnostics of
those inputs, not estimates of actual production.

The complete-rack output carries exact stage-and-resource coverage selectors. The full-chain linker
removes all matching server and factory-rack constraints, preserves later site installation, and
rejects any incomplete handoff. The checked three-source continuation now moves from material-cleared
packages to component-cleared racks before applying the synthetic site share. It hash-pins and
consumes every exact assembly draw, preserving the standalone marginal and within-source row
structure.

Next, replace generic ODM scopes with sourced site and line identities, line-cycle and shift data,
serialized WIP and shipments, first-pass yield, platform qualification, customer allocation, and
supplier-specific component output. Add cable, connector, storage, control-plane, external fabric,
transformer, and backup-power BOMs where their output point belongs in this layer. Preserve assembly
dependence with manufacturing through sourced common factors rather than assuming independent
permutations.

## 5. Data-center gross-to-net conversion: executable foundation complete

Map shipped systems to region and customer, then consume critical IT MW from the data-center atlas by
quarter. Add facility readiness, cooling topology, transformer delivery, backup power, network
availability, and commissioning status. A shipped rack stays outside operational supply until the site
can power and accept it.

The gross-envelope import is executable and checked against the Abilene site in the open seed. The
operational engine now hash-pins that import, subtracts four non-overlapping unavailable-power
categories, applies a target-platform share and NVIDIA rack-power conversion, and reconciles the
result against quarterly commissioning slots and completion. It reports zero-headroom risk,
bottleneck probability, and power or commissioning shadow capacity.

The checked operational inputs remain synthetic. Replace them with metered load, reservation and
allocation ledgers, electrical and cooling compatibility maps, delivery and acceptance schedules,
and rack-level operational handoffs before treating this connected output as evidence-backed. Then add
regional and customer partitions so the same MW cannot support multiple platform or customer pools.

## 6. Frozen-result chain linking: executable foundation complete

The checked linker now replaces overlapping manufacturing and operational placeholders, checks
platform topology and source hashes, adds an explicit shipped-stage site allocation, and reconciles
the resulting chain to one minimum. Required source-coverage declarations make absorbed package
materials fail closed unless all matching base constraints are removed. Version 2 hash-pins every
source draw ledger, recomputes all six selected-metric summary fields, uses one deterministic
permutation per source, and preserves all linked constraint, stage, and physical-output draws. The
checked exact-draw continuation shows the synthetic site allocation binding 92% of operational draws
and the illustrative operational source binding 8%.

Next, replace independent cross-source permutations with dependence supported by common causal
drivers or an estimated copula. Add customer and regional allocation ledgers, aggregate explicit
non-overlapping site operational pools for a global run, and connect the shared-platform portfolio
without assigning the same manufacturing or site capacity twice.

## 7. Ingestion and change detection: claim ledger and result alerts executable

The append-only SQLite ledger now ingests hash-verified source bytes and bitemporal claim revisions
atomically. It rejects path traversal, hash drift, evidence retrieved after transaction time, and
invalid supersession; exact replay is idempotent. Valid-time and known-time queries reconstruct prior
claim views, and deterministic claim diffs detect additions, revisions, and retractions. The checked
pack uses normalized official-source observations for NVIDIA rack power and TSMC company-wide wafer
shipments without treating the latter as product capacity.

The scheduled cycle runner adds interval gating, per-job locks, ordered pack hashes, frozen prior
snapshots, manifest-verified run releases, atomic checkpoints, and a strict new-backfill guard. A
durable local outbox deduplicates alerts, supports bounded at-least-once JSONL delivery, and records
acknowledgements.

The result comparison command issues deterministic, hash-pinned alerts when an estimate moves
outside its prior range, a median output moves materially, or the binding bottleneck distribution
changes.

The first idempotent public-disclosure adapter is now executable. It captures official SEC
submissions JSON by CIK, filters watched forms and dates, preserves exact source bytes, diffs
accessions against a hash-verified predecessor, and emits `not_capacity` filing-event claims only for
new accessions. It fails on incomplete recent history, changed prior metadata, or a disappeared
accession. A contact-bearing User-Agent is required at runtime and is never embedded in the watch.
An explicit accession selection can now capture and hash exact primary filing documents into a
review dashboard without interpreting them. A deterministic visible-text index can then run pinned
literal term sets, preserve normalized-text offsets and snippets, and count capped hits without
promoting them to claims. Reviewed claim authoring is now executable: a human-specified common-ledger
claim becomes an ingest pack only if its source manifest, raw filing, normalized-text hash, exact
character slice, review time, and claim schema still validate. The anchor proves source location,
not semantic correctness or model-input compatibility.

Next, add reviewed XBRL extraction and idempotent adapters for earnings materials, permits, job
postings, customs records, distributor
observations, freight, and satellite-derived construction events. External notification connectors,
controlled historical rebuilds, and automated scenario reruns remain to be built.

## 8. Earnings and market-data bridge

Build supplier revenue recognition from component consumption, contract timing, currency, and
inventory. Freeze current consensus, price, valuation, liquidity, positioning, and catalyst dates from
licensed sources. Keep an idea in `wait_for_proof` until exposure attribution and downside survive
review.

The checked engine now implements the physical-unit, inventory, recognition, FX, company earnings,
bear/base/bull, consensus-discrepancy, valuation-context, and long/short research-ranking contracts.
Its three-company release is fully synthetic and every row remains `wait_for_proof`. The next step is
to connect licensed consensus and market snapshots, source supplier-specific economics and
attribution, add positioning, and reconcile modeled lines to reported segment accounting.

## 9. Backtesting and calibration: executable foundation complete

Freeze historical scenarios before results, then compare predicted shipments, bottlenecks, supplier
revenue, and commissioning against later evidence. Track interval coverage, Brier scores, bias, and
source-family error. Recalibrate ranges from those results instead of narrowing them by judgment.

The version 1 calibration layer now hash-pins multiple forecast vintages and evidence-backed outcome
definitions, enforces transaction-time ordering, and scores interval coverage, P50 bias, quantile
loss, threshold-event Brier loss, metric classes, and source families. Mixed-unit groups expose only
normalized errors. Minimum-history groups can emit holdout-only parameters, but no proposal can
mutate a forecast. The replay-safe release retains exact inputs and hashes every dashboard and audit
surface.

The checked scorecard has six deliberately varied synthetic outcomes, not historical Blackwell
actuals. A separate checked Micron FY2026-Q3 benchmark hash-pins real pre-quarter-end management
guidance and later reported financial outcomes across seven metrics. It completes one external
financial-outcome adapter and release path, but it was reconstructed after the result, shares one
company source family, is not a native forecast, and is permanently excluded from calibration.

The first genuinely pre-outcome native registry is now frozen for 2026-Q3. It pins the full 20,000
linked-chain draws and five outcome contracts spanning packages, integrated racks, shipment,
installation, and operation. It contains no actuals or scores. The source scenario remains
synthetic, so this closes the transaction-time and raw-draw retention gap but does not establish
forecast skill or calibration eligibility.

The outcome-disposition adapter is also executable. It requires one pending, observed,
scope-mismatched, or unobservable row for every frozen metric; overdue rows cannot stay pending, and
only scope-matched observations can score. The checked pre-period review correctly retains five
pending rows and zero scores.

Next, preserve this immutable vintage through quarter end, then populate a new review with dated and
scope-matched physical evidence. Record explicit `unobservable` or `not_comparable` dispositions
when public evidence cannot satisfy a contract; do not substitute capacity announcements,
construction progress, or directional language. Freeze later evidence-backed vintages, model
outcome revisions explicitly, and run rolling or blocked holdouts before making any parameter
eligible.
