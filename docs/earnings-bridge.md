# Supplier earnings and consensus bridge

The earnings bridge converts one frozen physical manufacturing result into quarterly supplier line
items, total-company earnings, named bear/base/bull cases, consensus discrepancies, valuation
context, and a long/short research queue. It does not change the physical result and does not treat a
screen rank as a recommendation.

## Checked release

From `supply_intelligence/`:

```sh
python3 -m supply_intelligence validate-earnings \
  --source-result releases/2026-07-17-blackwell-manufacturing-illustrative/result.json \
  --scenario examples/blackwell-supplier-earnings-illustrative-2026q3.json

python3 -m supply_intelligence reconcile-earnings \
  --source-result releases/2026-07-17-blackwell-manufacturing-illustrative/result.json \
  --scenario examples/blackwell-supplier-earnings-illustrative-2026q3.json \
  --output-dir releases/2026-07-19-blackwell-supplier-earnings-illustrative
```

The checked pack uses real supplier names only to exercise the public-company topology. Its physical
source, supplier attribution, prices, inventory, recognition timing, company financials, consensus,
share prices, valuation context, and opportunity factors are all synthetic. The resulting MU and TSM
short-research directions and NVDA long-research direction are demonstration outputs, not forecasts
or investment views. Every row is locked to `wait_for_proof`.

## Frozen physical source

`ai-supply-earnings-bridge.v1` pins a source result by SHA-256, result format, scenario ID, and quarter.
Version 1 accepts `ai-supply-manufacturing-result.v1` and validates each selected source metric and
unit. It rejects source drift, a later source transaction time, quarter mismatch, or a
source-synthetic result attached to an evidence-backed earnings scenario.

Each physical metric's P10, P50, and P90 become triangular low, mode, and high parameters. One sampled
value per metric is reused across every supplier line in a draw. This prevents inconsistent reuse but
does not preserve raw manufacturing tails or cross-engine dependence.

## Physical output to recognized revenue

Each supplier line states its physical source metric, supplier attribution, component conversion,
beginning and ending inventory, revenue-recognition share, unit price, FX conversion, and gross
margin:

```text
attributed production
  = physical source units
  × component units per source unit
  × supplier-attributable share

available units
  = beginning inventory + attributed production

shipped units
  = max(0, available units - ending inventory)

recognized units
  = shipped units × current-quarter recognition share

line revenue in USD
  = recognized units × local unit price × USD per local currency

line gross profit
  = line revenue × line gross margin
```

Inventory is explicit so produced units do not automatically become same-quarter revenue. A service
line can use zero beginning and ending inventory, but its recognition share and price still need
evidence.

## Company earnings

The bridge aggregates physical-chain line items with a separately modeled rest of company:

```text
total revenue
  = AI-chain revenue + rest-of-company revenue

gross profit
  = AI-chain gross profit
  + rest-of-company revenue × rest-of-company gross margin

operating income
  = gross profit - operating expenses

pretax income
  = operating income - net nonoperating expense

net income
  = pretax income - max(0, pretax income) × tax rate

diluted EPS
  = net income / diluted shares
```

The current tax rule does not model loss carryforwards or tax benefits. Version 1 requires USD
reporting currency, while each line can carry a local currency and explicit FX estimate.

## Named cases and probabilistic result

Monte Carlo output reports P10, P50, P90, mean, minimum, and maximum. Correlated estimate groups reuse
the same quantile draw inside an iteration.

Named cases are separate deterministic audit views:

- bear uses the physical P10, low revenue drivers, high ending inventory, and high costs, tax, and
  diluted shares;
- base uses source P50 and every base estimate;
- bull uses physical P90, high revenue drivers, low ending inventory, and low costs, tax, and shares.

Consensus stays fixed at its base in all three named cases. This isolates model movement instead of
manufacturing a favorable or adverse moving comparator.

## Consensus, market context, and ranking

Each company freezes same-quarter comparable revenue and EPS ranges plus a dated price, NTM EPS,
market cap, and written valuation context. The engine reports revenue and EPS discrepancies and
current forward P/E context. It does not infer a price target.

The research score is:

```text
absolute modeled EPS discrepancy
  × confidence
  × evidence readiness
  × liquidity
  × catalyst proximity
  × downside resilience
```

Direction is `long_research_candidate` for a nonnegative median EPS discrepancy and
`short_research_candidate` otherwise. Every candidate also carries a dated catalyst, variant wedge,
what-is-priced-in statement, first rejection, investable-if test, thesis kill, and next workflow.
Synthetic physical or financial inputs force `wait_for_proof` regardless of score.

## Release audit surface

The release includes:

- `result.json` with physical lineage, probabilistic company results, cases, comparators, rankings,
  inputs, and evidence;
- `company_summary.csv`, `line_items.csv`, `named_cases.csv`, and `rankings.csv`;
- `input_estimates.csv` with method, posture, confidence, update date, provenance, and
  confirm/falsify tests for every estimate;
- exact scenario and source-result documents;
- a standalone dashboard and manifest covering every emitted byte.

Exact replay into the same directory is idempotent. A different or incomplete pre-existing release
is rejected.

## Current boundary

No live supplier attribution, contract price, inventory, accounting recognition, sell-side
consensus, security price, valuation, positioning, or catalyst dataset is connected. Before a row can
leave `wait_for_proof`, replace the synthetic physical source, freeze licensed comparable market
data, reconcile the supplier line to reported segments, and test downside and thesis-kill evidence.
