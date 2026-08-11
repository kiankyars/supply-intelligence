# Source snapshots and bitemporal claims

The claim ledger is an append-only application contract backed by SQLite. It stores immutable source
bytes, hash-addressed source metadata, claim revisions, evidence edges, and ingest-run identities.
It is separate from scenario releases: a scenario selects and interprets claims, while the ledger
preserves what was observed and what the system knew at each transaction-time cutoff.

## Checked ingest pack

The checked pack contains two normalized observations and four claims:

- NVIDIA's approximate GB200 NVL72 full-rack power in reported kW and derived MW;
- TSMC's consolidated 2Q26 wafer shipments in reported thousands and derived individual wafers.

The TSMC claims are company-wide scale controls. They do not identify a process node, customer,
product, installed capacity, or economically usable capacity. The checked files are short,
paraphrased observations with official source URLs; they are not copies of the source documents.

```sh
python3 -m supply_intelligence ingest-claims \
  --database state/claims.sqlite3 \
  --pack examples/ingestion/2026-07-19-official-controls-pack.json

python3 -m supply_intelligence query-claims \
  --database state/claims.sqlite3 \
  --valid-at 2026-06-30 \
  --known-at 2026-07-19T19:00:00Z
```

The first command creates parent directories and initializes schema version 1. Repeating the exact
pack returns the same run ID and skips existing claim revisions.

## Ingest pack contract

`ai-supply-ingest-pack.v1` contains one transaction timestamp, source declarations, and one or more
claim revisions. Each source declaration specifies:

- a unique pack-local alias;
- a content file relative to the pack directory;
- its expected SHA-256 digest;
- one of `raw_source`, `normalized_observation`, `structured_export`, or `model_result`;
- media type, source URL, publisher, source family, publication time, retrieval time, and license.

The loader resolves the content path before reading it and rejects absolute paths or traversal
outside the pack directory. It hashes the exact bytes and refuses a mismatch. A source retrieval
time cannot follow the pack's `recorded_at`, because evidence unavailable at transaction time cannot
support that revision.

A claim revision records a stable claim key, subject, predicate, typed JSON value, unit, posture,
status, valid-time interval, method, confidence, confirmation and falsification tests, and evidence
edges. Evidence edges carry a role and independence group so two copies of one syndicated source are
not silently treated as independent confirmation.

Claims also carry structured entity, geography, period, production-stage, capacity-basis, and
quantity-semantics dimensions, plus optional product, process-node, customer, technology, and
qualifier fields. Dimensions are included in revision identity. Downstream gates use them to prevent
company totals, prior periods, shipments, or broad status signals from becoming product-specific
quarterly capacity.

## Append-only revision rules

The first revision for a claim key cannot name a predecessor. Every later revision must name the
current latest revision and must have a strictly later `recorded_at`. A retraction stores a null value
with status `retracted`; it does not delete history.

Source inserts, revisions, evidence edges, and the ingest-run row share one `BEGIN IMMEDIATE`
transaction. A bad hash, invalid predecessor, or other validation failure leaves none of the pack's
rows committed. Deterministic snapshot, revision, run, and alert IDs make exact replay idempotent.

These guarantees are enforced through the package API. Direct writes to the SQLite file can bypass
them, so production deployment still needs file permissions, backups, and integrity monitoring.

## Bitemporal queries

Valid time answers when a claim applies to the world. Transaction time answers when the system knew
the revision. `valid_from` is inclusive and `valid_to` is exclusive. The query selects the latest
revision for each claim key satisfying both cutoffs, then omits retracted claims.

```sh
python3 -m supply_intelligence diff-claims \
  --database state/claims.sqlite3 \
  --valid-at 2026-06-30 \
  --previous-known-at 2026-07-19T18:59:59Z \
  --current-known-at 2026-07-19T19:00:00Z
```

`ai-supply-claim-diff.v1` emits deterministic `claim_added`, `claim_revised`, and `claim_removed`
alerts. The payload includes both claim versions and their source metadata. This is source-level
change detection; result-level bottleneck alerts remain a separate command.

## Scheduled cycles

`ai-supply-claim-cycle.v1` pins an ordered list of ingest packs, a valid-date view, a baseline
known-time cutoff, and a minimum interval. The command is safe to invoke more often than that
interval; it returns `not_due` without ingesting or writing a release.

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

An external timer such as launchd, cron, or a workflow scheduler can call this command. The runner:

1. takes a nonblocking per-job file lock;
2. verifies the job and every pack hash;
3. rejects a new pack recorded after `run_at` or at/before the prior checkpoint;
4. idempotently ingests packs in recorded-time order;
5. compares the last frozen snapshot with the current query;
6. enqueues deterministic notifications;
7. writes an immutable cycle release and atomically advances its checkpoint.

Each release preserves the exact job and pack files, prior and current snapshots, claim diff, ingest
lineage, notification event IDs, and a SHA-256 manifest. A later cycle reads the prior snapshot from
that release and verifies its hash. It does not reconstruct the old view from a database that may
have received a historical backfill.

Exact packs already listed in the checkpoint can be replayed. A newly added backdated pack is
blocked by the scheduled runner because it would rewrite a prior known-time view. Historical imports
remain possible through the lower-level ingest command, but they should use a separate controlled
backfill workflow and trigger an explicit rebuild.

## Notification outbox

Claim diffs enter a separate SQLite outbox. Event IDs are derived from tamper-checked alert payloads,
so repeated enqueue skips the same event. Pending notifications can be listed, delivered in bounded
batches to a local JSONL sink, and acknowledged with a timestamp and note.

```sh
python3 -m supply_intelligence list-claim-notifications \
  --outbox state/notifications.sqlite3 \
  --status pending

python3 -m supply_intelligence deliver-claim-notifications \
  --outbox state/notifications.sqlite3 \
  --sink state/claim-alerts.jsonl \
  --delivered-at 2026-07-19T19:01:00Z
```

JSONL delivery is at least once. The sink write is flushed before outbox status advances; a process
crash in between can duplicate a line. Consumers must deduplicate by `event_id`. Acknowledgement is
an audited state transition and does not imply that a scenario was rerun or an investment view was
approved.

## Current boundary

The companion [SEC filing-event adapter](sec-filings-adapter.md) now fetches or normalizes official
per-CIK submissions feeds and produces reviewed-pack-compatible filing events. Its explicit
accession-selection stage preserves exact primary documents, its text index creates deterministic
review offsets, and a human-authored recipe can emit a claim pack only while the pinned text slice
still matches exactly. The anchor audits the reviewed passage but does not validate the analyst's
interpretation. Numeric prose remains manual and XBRL extraction is not implemented. Other sources
still need adapters, and the ledger itself does not crawl.
Scheduling is a local interval gate designed to be called by an
external timer; it is not a resident daemon. JSONL is the only delivery sink. The ledger also does
not make a claim usable as model capacity: scenario and atlas adapters must still preserve capacity
basis, period, scope, allocation, and uncertainty.
