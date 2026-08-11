# SEC filing-event adapter

Status: executable ingestion adapter, 2026-07-19.

The adapter converts the SEC's official per-CIK submissions JSON into immutable filing-event
releases and optional claim-ledger ingest packs. It watches disclosure events; it does not interpret
a filing as production, allocation, shipment, or capacity evidence.

## Source boundary

The SEC documents the unauthenticated submissions endpoint as:

```text
https://data.sec.gov/submissions/CIK##########.json
```

The current JSON contains at least one year or 1,000 recent filings and may point to supplemental
history files. The adapter validates the ten-digit CIK, equal-length recent-filing columns, unique
accessions, ISO dates and acceptance timestamps, safe primary-document names, and the configured
form and date filters. If the requested window predates the recent array while supplemental history
is declared, loading fails instead of silently returning an incomplete history.

Automated access must use a declared organization-and-contact User-Agent and remain within the SEC's
fair-access limit. `fetch-sec-filings` requires an email-bearing User-Agent and spaces sequential
requests by at least 0.12 seconds. The contact is a runtime argument, not a committed credential or
watch-file field.

Primary references:

- [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
- [SEC programmatic access and fair-access guidance](https://www.sec.gov/about/webmaster-frequently-asked-questions)
- [SEC EDGAR data access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)

## Watch and release contract

`ai-supply-sec-filings-watch.v1` declares a stable watch ID, inclusive filing-date bounds, unique
form names, and unique entity IDs and CIKs. The checked watch covers NVIDIA and Micron 10-K, 10-Q,
and 8-K filings and amendments; it contains no contact information.

`ai-supply-sec-filings-release.v1` preserves:

- the exact watch JSON;
- byte-identical SEC submissions JSON for every CIK;
- all selected normalized filings in JSON and CSV plus a first-read dashboard;
- the new-accession set relative to an optional prior release;
- an `ai-supply-ingest-pack.v1` when at least one new filing exists; and
- a SHA-256 manifest covering every payload.

Every generated claim has `capacity_basis: not_capacity`, `quantity_semantics: filing_event`, and a
stable accession-based key. The value records the form, dates, items, primary document, and SEC
archive URL. A separate reviewed extraction must create any numeric manufacturing or financial
claim from the actual filing content.

When a predecessor is supplied, the current watch scope must match and its date window must contain
the prior window. Existing accession metadata must remain equivalent after normalization. A
disappearing accession, changed metadata, or predecessor-manifest drift fails closed; corrections
need a reviewed claim revision rather than an automatic overwrite. If no accession is new, the
release records zero additions and omits the otherwise-invalid empty ingest pack.

## Run

Fetch directly from the SEC with a real organization contact:

```sh
python3 -m supply_intelligence fetch-sec-filings \
  --watch examples/ingestion/sec-ai-supply-watch.json \
  --retrieved-at 2026-07-19T23:00:00Z \
  --user-agent 'Your Organization research-contact@example.com' \
  --output-dir releases/sec-filings/20260719T230000Z
```

Or normalize previously captured `CIK##########.json` files without network access:

```sh
python3 -m supply_intelligence build-sec-filings-release \
  --watch examples/ingestion/sec-ai-supply-watch.json \
  --source-dir path/to/captured/submissions \
  --retrieved-at 2026-07-19T23:00:00Z \
  --output-dir releases/sec-filings/20260719T230000Z
```

For the next observation, add `--previous-release` pointing to the prior directory. When
`ingest_pack.json` is present, pass it to `ingest-claims` or add it to a reviewed scheduled claim
cycle.

## Primary-document capture

A second explicit selection controls which filing documents are downloaded. It pins the source
filing-event manifest and gives each accession a review reason and optional expected document hash:

```json
{
  "format": "ai-supply-sec-filing-selection.v1",
  "id": "nvidia-quarterly-review",
  "source_manifest_sha256": "<64 lowercase hex characters>",
  "filings": [
    {
      "accession_number": "0001045810-26-000000",
      "review_reason": "Review manufacturing, inventory, and demand disclosures.",
      "expected_sha256": null
    }
  ]
}
```

```sh
python3 -m supply_intelligence fetch-sec-filing-documents \
  --filings-release releases/sec-filings/20260719T230000Z \
  --selection path/to/filing-selection.json \
  --retrieved-at 2026-07-19T23:05:00Z \
  --user-agent 'Your Organization research-contact@example.com' \
  --output-dir releases/sec-filing-documents/20260719T230500Z
```

`ai-supply-sec-filing-documents-release.v1` preserves the exact primary documents, the selection,
the source release manifest, a JSON/CSV review queue, dashboard, and manifest. The selected accession
must resolve to the pinned event release, and an optional expected SHA must match. The release does
not extract prose or XBRL claims and does not auto-rerun a supply scenario.

## Deterministic text index

`build-sec-filing-text-index` takes a hash-pinned document release and a recipe containing literal
review terms, context length, and a per-term hit cap. It decodes declared or common SEC encodings,
removes script, style, and noscript content, normalizes visible whitespace, and writes one UTF-8 text
file per accession. Case-insensitive literal hits carry character offsets into that normalized file,
context snippets, categories, and occurrence numbers. Any hits beyond the configured cap are counted
as truncated.

```json
{
  "format": "ai-supply-sec-filing-text-index.v1",
  "id": "ai-supply-disclosure-terms",
  "source_manifest_sha256": "<document-release manifest SHA-256>",
  "context_characters": 120,
  "max_hits_per_term_per_document": 50,
  "terms": [
    {"id": "hbm", "label": "HBM", "category": "memory", "literal": "HBM"}
  ]
}
```

```sh
python3 -m supply_intelligence build-sec-filing-text-index \
  --documents-release releases/sec-filing-documents/20260719T230500Z \
  --recipe path/to/text-index-recipe.json \
  --output-dir releases/sec-filing-text/20260719T230500Z
```

The output copies every raw source document, pins the upstream manifest, and includes normalized
text, hit CSV/JSON, dashboard, and a full manifest. A literal match is a triage aid, not a claim and
not evidence that the surrounding disclosure matches the platform, period, customer, or capacity
basis required by a model input.

## Exact-text-anchored reviewed claims

`build-sec-reviewed-claims` is the manual interpretation boundary. Its recipe pins the text-release
manifest, identifies the reviewer and transaction time, and supplies a common-ledger claim object for
each exact half-open character range. Evidence is not accepted in the recipe; the builder attaches
the corresponding raw SEC filing as the sole primary source so the analyst cannot substitute an
unpinned citation.

```json
{
  "format": "ai-supply-sec-reviewed-claims.v1",
  "id": "nvidia-hbm-disclosure-review",
  "source_manifest_sha256": "<text-release manifest SHA-256>",
  "recorded_at": "2026-07-19T23:15:00Z",
  "reviewer": "Analyst name or review role",
  "claims": [
    {
      "accession_number": "0001045810-26-000000",
      "character_start": 1200,
      "character_end": 1240,
      "expected_text": "<exact normalized filing passage>",
      "claim": {
        "claim_key": "<stable key>",
        "subject": "<entity>",
        "predicate": "<reviewed assertion>",
        "value": "<typed value>",
        "unit": "<unit>",
        "dimensions": {
          "entity_scope": "company",
          "geography": "global",
          "period": "2026-Q2",
          "stage": "company_disclosure",
          "capacity_basis": "not_capacity",
          "quantity_semantics": "qualitative_signal"
        },
        "posture": "reported",
        "status": "asserted",
        "valid_from": "2026-06-24",
        "valid_to": null,
        "methodology": "Preserve the disclosure scope without quantitative conversion.",
        "confidence": 0.9,
        "confirming_evidence": "A later filing repeats the characterization.",
        "falsifying_evidence": "A later filing retracts or weakens it.",
        "supersedes_revision_id": null
      }
    }
  ]
}
```

```sh
python3 -m supply_intelligence build-sec-reviewed-claims \
  --text-release releases/sec-filing-text/20260719T230500Z \
  --recipe path/to/reviewed-claims.json \
  --output-dir releases/sec-reviewed-claims/20260719T231500Z
```

The builder rechecks the complete source release, normalized-text hash, raw-document hash, exact
text slice, claim schema, and that review time does not precede source retrieval. The immutable
release preserves the recipe, upstream manifest, normalized text, raw filing, review result,
dashboard, and ledger-ready `ingest_pack.json`; replay into an occupied directory must be byte
identical.

An exact anchor proves which passage the reviewer used. It does not prove that a qualitative or
numeric interpretation is correct, that units were converted correctly, or that the filing's scope
matches a model constraint. Manufacturing and other domain gates remain authoritative. The pipeline
still does not perform autonomous prose interpretation or XBRL extraction.
