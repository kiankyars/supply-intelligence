"""Replay-safe SEC submissions adapter for filing-event claim packs."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import Request, urlopen

from .release import _csv, _json, _sha256


SEC_WATCH_FORMAT = "ai-supply-sec-filings-watch.v1"
SEC_FILINGS_FORMAT = "ai-supply-sec-filings.v1"
SEC_FILING_CHANGES_FORMAT = "ai-supply-sec-filing-changes.v1"
SEC_FILINGS_RELEASE_FORMAT = "ai-supply-sec-filings-release.v1"
SEC_SUBMISSIONS_BASE_URL = "https://data.sec.gov/submissions"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"
MAX_SOURCE_BYTES = 25_000_000
ENTITY_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
ACCESSION_PATTERN = re.compile(r"\d{10}-\d{2}-\d{6}\Z")
CONTACT_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


@dataclass(frozen=True, slots=True)
class SecEntity:
    id: str
    cik: str

    @property
    def source_file(self) -> str:
        return f"CIK{self.cik}.json"

    @property
    def source_url(self) -> str:
        return f"{SEC_SUBMISSIONS_BASE_URL}/{self.source_file}"


@dataclass(frozen=True, slots=True)
class SecWatch:
    id: str
    filing_date_from: str
    filing_date_to: str
    forms: tuple[str, ...]
    entities: tuple[SecEntity, ...]
    document: str


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be an array")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} is required")
    return value


def _only(value: Mapping[str, Any], fields: set[str], path: str) -> None:
    if unexpected := set(value) - fields:
        raise ValueError(f"unexpected {path} fields: {sorted(unexpected)}")


def _date(value: Any, path: str) -> date:
    try:
        return date.fromisoformat(_text(value, path))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO date") from exc


def _timestamp(value: Any, path: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, path).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _normalized_timestamp(value: Any, path: str) -> str:
    return _timestamp(value, path).isoformat().replace("+00:00", "Z")


def _cik(value: Any, path: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"{path} must be a CIK")
    digits = str(value)
    if not digits.isdigit() or not 1 <= len(digits) <= 10:
        raise ValueError(f"{path} must contain at most ten digits")
    return digits.zfill(10)


def load_sec_watch(path: str | Path) -> SecWatch:
    source = Path(path)
    raw = source.read_bytes()
    try:
        value = _mapping(json.loads(raw), "watch")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC watch JSON: {exc}") from exc
    if value.get("format") != SEC_WATCH_FORMAT:
        raise ValueError(f"watch format must be {SEC_WATCH_FORMAT}")
    _only(
        value,
        {
            "format",
            "id",
            "filing_date_from",
            "filing_date_to",
            "forms",
            "entities",
        },
        "watch",
    )
    watch_id = _text(value.get("id"), "watch.id")
    if not ENTITY_ID_PATTERN.fullmatch(watch_id):
        raise ValueError("watch.id must be a lowercase slug")
    start = _date(value.get("filing_date_from"), "watch.filing_date_from")
    end = _date(value.get("filing_date_to"), "watch.filing_date_to")
    if end < start:
        raise ValueError("watch.filing_date_to cannot precede filing_date_from")
    forms = tuple(
        _text(item, f"watch.forms[{index}]")
        for index, item in enumerate(_list(value.get("forms"), "watch.forms"))
    )
    if not forms or len(forms) != len(set(forms)):
        raise ValueError("watch.forms must contain unique form names")
    entities = []
    for index, item in enumerate(_list(value.get("entities"), "watch.entities")):
        path_name = f"watch.entities[{index}]"
        entity = _mapping(item, path_name)
        _only(entity, {"id", "cik"}, path_name)
        entity_id = _text(entity.get("id"), f"{path_name}.id")
        if not ENTITY_ID_PATTERN.fullmatch(entity_id):
            raise ValueError(f"{path_name}.id must be a lowercase slug")
        entities.append(SecEntity(entity_id, _cik(entity.get("cik"), f"{path_name}.cik")))
    if not entities:
        raise ValueError("watch.entities requires at least one entity")
    if len({item.id for item in entities}) != len(entities):
        raise ValueError("watch entity IDs must be unique")
    if len({item.cik for item in entities}) != len(entities):
        raise ValueError("watch entity CIKs must be unique")
    return SecWatch(
        id=watch_id,
        filing_date_from=start.isoformat(),
        filing_date_to=end.isoformat(),
        forms=forms,
        entities=tuple(entities),
        document=raw.decode("utf-8"),
    )


def _recent_columns(source: Mapping[str, Any], entity: SecEntity) -> Mapping[str, list[Any]]:
    source_cik = _cik(source.get("cik"), f"{entity.id}.cik")
    if source_cik != entity.cik:
        raise ValueError(f"{entity.id} source CIK does not match the watch")
    _text(source.get("name"), f"{entity.id}.name")
    filings = _mapping(source.get("filings"), f"{entity.id}.filings")
    recent = _mapping(filings.get("recent"), f"{entity.id}.filings.recent")
    required = {
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "items",
        "primaryDocument",
        "primaryDocDescription",
        "isXBRL",
        "isInlineXBRL",
    }
    columns = {
        field: _list(recent.get(field), f"{entity.id}.filings.recent.{field}")
        for field in required
    }
    lengths = {len(items) for items in columns.values()}
    if len(lengths) != 1:
        raise ValueError(f"{entity.id} recent filing columns have different lengths")
    return columns


def _filing_record(
    source: Mapping[str, Any],
    entity: SecEntity,
    columns: Mapping[str, list[Any]],
    index: int,
) -> dict[str, Any]:
    accession = _text(columns["accessionNumber"][index], "accessionNumber")
    if not ACCESSION_PATTERN.fullmatch(accession):
        raise ValueError(f"{entity.id} contains an invalid accession number")
    filing_date = _date(columns["filingDate"][index], "filingDate").isoformat()
    report_value = columns["reportDate"][index]
    report_date = ""
    if report_value not in (None, ""):
        report_date = _date(report_value, "reportDate").isoformat()
    accepted_value = columns["acceptanceDateTime"][index]
    accepted_at = ""
    if accepted_value not in (None, ""):
        accepted_at = _normalized_timestamp(accepted_value, "acceptanceDateTime")
    primary_document = _text(columns["primaryDocument"][index], "primaryDocument")
    if Path(primary_document).name != primary_document or primary_document in {".", ".."}:
        raise ValueError(f"{entity.id} primaryDocument must be a file name")
    form = _text(columns["form"][index], "form")
    accession_compact = accession.replace("-", "")
    archive_url = (
        f"{SEC_ARCHIVES_BASE_URL}/{int(entity.cik)}/{accession_compact}/"
        f"{primary_document}"
    )
    return {
        "entity_id": entity.id,
        "company_name": _text(source.get("name"), f"{entity.id}.name"),
        "cik": entity.cik,
        "accession_number": accession,
        "form": form,
        "filing_date": filing_date,
        "report_date": report_date,
        "acceptance_datetime": accepted_at,
        "items": str(columns["items"][index] or ""),
        "primary_document": primary_document,
        "primary_document_description": str(
            columns["primaryDocDescription"][index] or ""
        ),
        "is_xbrl": bool(columns["isXBRL"][index]),
        "is_inline_xbrl": bool(columns["isInlineXBRL"][index]),
        "filing_url": archive_url,
    }


def normalize_sec_submissions(
    watch: SecWatch,
    source_documents: Mapping[str, bytes],
    *,
    retrieved_at: str,
) -> dict[str, Any]:
    recorded_at = _normalized_timestamp(retrieved_at, "retrieved_at")
    if set(source_documents) != {item.id for item in watch.entities}:
        raise ValueError("SEC source documents must exactly match watched entities")
    records = []
    source_metadata = []
    for entity in watch.entities:
        raw = source_documents[entity.id]
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError(f"{entity.id} SEC source exceeds the size limit")
        try:
            source = _mapping(json.loads(raw), entity.id)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid SEC submissions JSON for {entity.id}: {exc}") from exc
        columns = _recent_columns(source, entity)
        seen = set()
        filing_dates = []
        for index in range(len(columns["accessionNumber"])):
            record = _filing_record(source, entity, columns, index)
            accession = record["accession_number"]
            if accession in seen:
                raise ValueError(f"{entity.id} contains duplicate accession numbers")
            seen.add(accession)
            filing_dates.append(record["filing_date"])
            if (
                watch.filing_date_from <= record["filing_date"] <= watch.filing_date_to
                and record["form"] in watch.forms
            ):
                records.append(record)
        supplemental = _list(
            _mapping(source.get("filings"), f"{entity.id}.filings").get("files", []),
            f"{entity.id}.filings.files",
        )
        if (
            supplemental
            and filing_dates
            and watch.filing_date_from < min(filing_dates)
        ):
            raise ValueError(
                f"{entity.id} requested window predates recent submissions; "
                "capture the referenced supplemental history"
            )
        source_metadata.append(
            {
                "entity_id": entity.id,
                "company_name": _text(source.get("name"), f"{entity.id}.name"),
                "cik": entity.cik,
                "source_file": entity.source_file,
                "source_url": entity.source_url,
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "byte_count": len(raw),
            }
        )
    records.sort(
        key=lambda item: (
            item["filing_date"],
            item["acceptance_datetime"],
            item["entity_id"],
            item["accession_number"],
        )
    )
    accessions = [item["accession_number"] for item in records]
    if len(accessions) != len(set(accessions)):
        raise ValueError("watched entities contain overlapping accession numbers")
    return {
        "format": SEC_FILINGS_FORMAT,
        "watch_id": watch.id,
        "recorded_at": recorded_at,
        "filing_date_from": watch.filing_date_from,
        "filing_date_to": watch.filing_date_to,
        "forms": list(watch.forms),
        "entities": source_metadata,
        "filing_count": len(records),
        "filings": records,
    }


def _load_previous_release(path: str | Path) -> tuple[dict[str, Any], str]:
    root = Path(path)
    manifest_raw = (root / "manifest.json").read_bytes()
    try:
        manifest = _mapping(json.loads(manifest_raw), "previous manifest")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid previous SEC manifest: {exc}") from exc
    if manifest.get("format") != SEC_FILINGS_RELEASE_FORMAT:
        raise ValueError(f"previous release format must be {SEC_FILINGS_RELEASE_FORMAT}")
    files = _mapping(manifest.get("files"), "previous manifest.files")
    expected_files = set(files) | {"manifest.json"}
    actual_files = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    }
    if actual_files != expected_files:
        raise ValueError("previous SEC release is incomplete or contains extra files")
    for name, descriptor_value in files.items():
        descriptor = _mapping(descriptor_value, f"previous manifest.files.{name}")
        raw = (root / name).read_bytes()
        if len(raw) != descriptor.get("bytes") or hashlib.sha256(raw).hexdigest() != descriptor.get(
            "sha256"
        ):
            raise ValueError(f"previous SEC release file hash mismatch: {name}")
    filings_raw = (root / "filings.json").read_bytes()
    try:
        filings = _mapping(json.loads(filings_raw), "previous filings")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid previous SEC filings JSON: {exc}") from exc
    if filings.get("format") != SEC_FILINGS_FORMAT:
        raise ValueError(f"previous filings format must be {SEC_FILINGS_FORMAT}")
    return dict(filings), hashlib.sha256(manifest_raw).hexdigest()


def _scope_identity(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "watch_id": document.get("watch_id"),
        "forms": document.get("forms"),
        "entities": [
            {"entity_id": item.get("entity_id"), "cik": item.get("cik")}
            for item in document.get("entities", [])
        ],
    }


def _new_filings(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    current_filings = _list(current.get("filings"), "current.filings")
    if previous is None:
        return [dict(item) for item in current_filings]
    if _scope_identity(current) != _scope_identity(previous):
        raise ValueError("previous SEC release watch scope does not match")
    if (
        current.get("filing_date_from") > previous.get("filing_date_from")
        or current.get("filing_date_to") < previous.get("filing_date_to")
    ):
        raise ValueError("current SEC filing window must contain the previous window")
    if _timestamp(current.get("recorded_at"), "current.recorded_at") <= _timestamp(
        previous.get("recorded_at"), "previous.recorded_at"
    ):
        raise ValueError("current SEC recorded_at must follow the previous release")
    previous_by_accession = {
        item["accession_number"]: item
        for item in _list(previous.get("filings"), "previous.filings")
    }
    current_by_accession = {item["accession_number"]: item for item in current_filings}
    for accession, old in previous_by_accession.items():
        current_item = current_by_accession.get(accession)
        if current_item is None:
            raise ValueError(f"previous SEC filing disappeared: {accession}")
        if current_item != old:
            raise ValueError(
                f"SEC filing metadata changed and requires reviewed revision: {accession}"
            )
    return [
        dict(item)
        for item in current_filings
        if item["accession_number"] not in previous_by_accession
    ]


def _filing_claim(item: Mapping[str, Any], source_id: str) -> dict[str, Any]:
    accession = item["accession_number"]
    return {
        "claim_key": (
            f"company.{item['entity_id']}.sec_filing.{accession.replace('-', '')}"
        ),
        "subject": item["company_name"],
        "predicate": "submitted an SEC filing",
        "value": {
            key: item[key]
            for key in (
                "accession_number",
                "form",
                "filing_date",
                "report_date",
                "acceptance_datetime",
                "items",
                "primary_document",
                "filing_url",
            )
        },
        "unit": "filing_event",
        "dimensions": {
            "entity_scope": "company",
            "geography": "global",
            "period": item["report_date"] or item["filing_date"],
            "stage": "company_disclosure",
            "capacity_basis": "not_capacity",
            "quantity_semantics": "filing_event",
            "qualifier": item["form"],
        },
        "posture": "reported",
        "status": "asserted",
        "valid_from": item["filing_date"],
        "valid_to": None,
        "methodology": (
            "Record the filing event and SEC archive pointer from the official submissions "
            "feed. The event is a disclosure signal, not a production or capacity claim."
        ),
        "confidence": 0.99,
        "confirming_evidence": (
            "The accession remains present in the SEC submissions history with the same form, "
            "filing date, and primary document."
        ),
        "falsifying_evidence": (
            "SEC corrects or withdraws the accession metadata, or the source CIK does not match "
            "the watched company."
        ),
        "supersedes_revision_id": None,
        "evidence": [
            {
                "source_id": source_id,
                "role": "primary",
                "independence_group": f"sec-edgar-submissions-{item['cik']}",
            }
        ],
    }


def _filing_rows(
    filings: Sequence[Mapping[str, Any]],
    *,
    new_accessions: set[str],
) -> str:
    if not filings:
        return '<tr><td colspan="6" class="empty">No selected filing events.</td></tr>'
    rows = []
    for item in reversed(filings):
        accession = str(item["accession_number"])
        status = '<span class="badge">New</span>' if accession in new_accessions else ""
        report_date = str(item["report_date"] or "—")
        items = str(item["items"] or "—")
        rows.append(
            "<tr>"
            f"<td><strong>{escape(str(item['company_name']))}</strong>"
            f"<span class=\"subtle\">CIK {escape(str(item['cik']))}</span></td>"
            f"<td><span class=\"form\">{escape(str(item['form']))}</span>{status}</td>"
            f"<td>{escape(str(item['filing_date']))}</td>"
            f"<td>{escape(report_date)}</td>"
            f"<td>{escape(items)}</td>"
            f"<td><a href=\"{escape(str(item['filing_url']), quote=True)}\">"
            f"{escape(accession)}</a></td>"
            "</tr>"
        )
    return "".join(rows)


def render_sec_filings_dashboard(
    current: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> str:
    filings = _list(current.get("filings"), "current.filings")
    additions = _list(changes.get("new_filings"), "changes.new_filings")
    new_accessions = {str(item["accession_number"]) for item in additions}
    source_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item['company_name']))}</td>"
        f"<td>{escape(str(item['cik']))}</td>"
        f"<td><a href=\"{escape(str(item['source_url']), quote=True)}\">SEC submissions JSON</a></td>"
        f"<td><code>{escape(str(item['content_sha256'])[:16])}…</code></td>"
        f"<td>{int(item['byte_count']):,}</td>"
        "</tr>"
        for item in current.get("entities", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEC filing watch · {escape(str(current['watch_id']))}</title>
<style>
:root {{ color-scheme: light; --ink:#17201d; --muted:#65716c; --paper:#f3f0e9;
  --panel:#fffdf8; --line:#d8d4c9; --teal:#0b786b; --amber:#a86112; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink); font:15px/1.45 ui-sans-serif,
  -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
main {{ width:min(1380px,calc(100% - 40px)); margin:0 auto; padding:42px 0 64px; }}
header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end;
  border-bottom:1px solid var(--line); padding-bottom:24px; }}
.eyebrow {{ color:var(--teal); font:700 12px/1.2 ui-monospace,SFMono-Regular,monospace;
  letter-spacing:.12em; text-transform:uppercase; }}
h1 {{ font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif; margin:8px 0 6px; }}
.meta {{ text-align:right; color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:22px 0; }}
.card,.panel,.warning {{ background:var(--panel); border:1px solid var(--line); }}
.card {{ padding:20px; }} .card strong {{ display:block; font:700 34px/1 ui-monospace,monospace;
  margin-top:8px; }} .label,.subtle {{ color:var(--muted); }}
.warning {{ padding:18px 20px; border-color:#d7a45d; background:#fff3dc; display:grid;
  grid-template-columns:160px 1fr; gap:20px; }} .warning strong {{ color:var(--amber); }}
.panel {{ margin-top:22px; overflow:hidden; }}
.panel-head {{ display:flex; justify-content:space-between; align-items:end; gap:16px;
  padding:20px; border-bottom:1px solid var(--line); }}
h2 {{ font:700 26px/1.15 Georgia,serif; margin:4px 0 0; }}
.table-wrap {{ overflow-x:auto; }} table {{ width:100%; border-collapse:collapse; min-width:860px; }}
th {{ color:var(--muted); font-size:11px; letter-spacing:.08em; text-align:left;
  text-transform:uppercase; }} th,td {{ padding:13px 16px; border-bottom:1px solid var(--line);
  vertical-align:top; }} tr:last-child td {{ border-bottom:0; }}
td .subtle {{ display:block; font-size:12px; margin-top:2px; }}
.form {{ display:inline-block; font:700 13px ui-monospace,monospace; }}
.badge {{ display:inline-block; margin-left:8px; padding:2px 7px; border-radius:999px;
  color:#fff; background:var(--teal); font-size:11px; font-weight:700; }}
a {{ color:var(--teal); text-underline-offset:3px; }} code {{ font-size:12px; }}
.empty {{ color:var(--muted); text-align:center; padding:30px; }}
footer {{ color:var(--muted); margin-top:24px; font-size:13px; }}
@media (max-width:760px) {{ main {{ width:min(100% - 24px,1380px); padding-top:24px; }}
  header,.panel-head {{ align-items:flex-start; flex-direction:column; }} .meta {{ text-align:left; }}
  .cards {{ grid-template-columns:1fr; }} .warning {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body><main>
<header><div><div class="eyebrow">AI Supply Intelligence · SEC disclosure watch</div>
<h1>{escape(str(current['watch_id']))}</h1>
<div class="label">Forms {escape(', '.join(current['forms']))} · filing dates
{escape(str(current['filing_date_from']))} through {escape(str(current['filing_date_to']))}</div></div>
<div class="meta">Known at<br><strong>{escape(str(current['recorded_at']))}</strong></div></header>
<section class="warning"><strong>Disclosure signal only</strong><span>Every generated claim is
<code>not_capacity</code>. A filing event does not establish production, allocation, shipment, or
operational deployment. Numeric claims require separate reviewed extraction from the filing.</span></section>
<section class="cards"><div class="card"><span class="label">Watched entities</span>
<strong>{len(current['entities'])}</strong></div><div class="card"><span class="label">Selected filings</span>
<strong>{len(filings)}</strong></div><div class="card"><span class="label">New accessions</span>
<strong>{len(additions)}</strong></div></section>
<section class="panel"><div class="panel-head"><div><div class="eyebrow">Triage queue</div>
<h2>New filing events</h2></div><span class="label">Relative to the hash-verified predecessor</span></div>
<div class="table-wrap"><table><thead><tr><th>Company</th><th>Form</th><th>Filed</th>
<th>Report date</th><th>Items</th><th>Accession</th></tr></thead><tbody>
{_filing_rows(additions, new_accessions=new_accessions)}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><div class="eyebrow">Watch history</div>
<h2>All selected filings</h2></div><span class="label">Newest first</span></div>
<div class="table-wrap"><table><thead><tr><th>Company</th><th>Form</th><th>Filed</th>
<th>Report date</th><th>Items</th><th>Accession</th></tr></thead><tbody>
{_filing_rows(filings, new_accessions=new_accessions)}</tbody></table></div></section>
<section class="panel"><div class="panel-head"><div><div class="eyebrow">Source ledger</div>
<h2>Hash-pinned SEC feeds</h2></div></div><div class="table-wrap"><table><thead><tr>
<th>Company</th><th>CIK</th><th>Source</th><th>SHA-256</th><th>Bytes</th></tr></thead>
<tbody>{source_rows}</tbody></table></div></section>
<footer>Method: filter the official per-CIK recent submissions arrays by the configured inclusive
date window and exact form set; diff stable accessions against an immutable predecessor.</footer>
</main></body></html>"""


def build_sec_filings_release_documents(
    watch: SecWatch,
    source_documents: Mapping[str, bytes],
    *,
    retrieved_at: str,
    previous_release: str | Path | None = None,
) -> dict[str, str]:
    current = normalize_sec_submissions(
        watch,
        source_documents,
        retrieved_at=retrieved_at,
    )
    previous = None
    previous_manifest_sha256 = None
    if previous_release is not None:
        previous, previous_manifest_sha256 = _load_previous_release(previous_release)
    additions = _new_filings(current, previous)
    changes = {
        "format": SEC_FILING_CHANGES_FORMAT,
        "watch_id": watch.id,
        "recorded_at": current["recorded_at"],
        "previous_manifest_sha256": previous_manifest_sha256,
        "new_filing_count": len(additions),
        "new_filings": additions,
    }
    rows = current["filings"]
    csv_fields = [
        "entity_id",
        "company_name",
        "cik",
        "accession_number",
        "form",
        "filing_date",
        "report_date",
        "acceptance_datetime",
        "items",
        "primary_document",
        "primary_document_description",
        "is_xbrl",
        "is_inline_xbrl",
        "filing_url",
    ]
    documents = {
        "watch.json": watch.document,
        "filings.json": _json(current),
        "filings.csv": _csv(csv_fields, rows),
        "new_filings.json": _json(changes),
        "dashboard.html": render_sec_filings_dashboard(current, changes),
        "README.md": (
            f"# SEC filing watch: {watch.id}\n\n"
            f"Captured `{len(rows)}` selected filing events through "
            f"`{current['recorded_at']}`; `{len(additions)}` are new relative to the "
            f"declared predecessor.\n\n"
            "Exact SEC submissions JSON is preserved under `sources/`. Filing events are "
            "directional disclosure signals with `capacity_basis: not_capacity`; no filing "
            "text is interpreted as production, allocation, or capacity without a separate "
            "reviewed claim.\n"
        ),
    }
    for entity in watch.entities:
        documents[f"sources/{entity.source_file}"] = source_documents[entity.id].decode(
            "utf-8"
        )
    if additions:
        source_ids = {
            item["entity_id"]: f"sec-submissions-{item['entity_id']}"
            for item in additions
        }
        addition_entities = {item["entity_id"] for item in additions}
        sources = []
        for entity in watch.entities:
            if entity.id not in addition_entities:
                continue
            raw = source_documents[entity.id]
            sources.append(
                {
                    "id": source_ids[entity.id],
                    "content_file": f"sources/{entity.source_file}",
                    "expected_sha256": hashlib.sha256(raw).hexdigest(),
                    "capture_kind": "structured_export",
                    "media_type": "application/json",
                    "source_url": entity.source_url,
                    "publisher": "U.S. Securities and Exchange Commission",
                    "source_family": f"sec-edgar-submissions-{entity.cik}",
                    "published_at": None,
                    "retrieved_at": current["recorded_at"],
                    "license": "SEC website terms",
                }
            )
        pack = {
            "format": "ai-supply-ingest-pack.v1",
            "recorded_at": current["recorded_at"],
            "sources": sources,
            "claims": [
                _filing_claim(item, source_ids[item["entity_id"]])
                for item in additions
            ],
        }
        documents["ingest_pack.json"] = _json(pack)
    manifest = {
        "format": SEC_FILINGS_RELEASE_FORMAT,
        "watch_id": watch.id,
        "recorded_at": current["recorded_at"],
        "filing_date_from": watch.filing_date_from,
        "filing_date_to": watch.filing_date_to,
        "forms": list(watch.forms),
        "source_count": len(source_documents),
        "filing_count": len(rows),
        "new_filing_count": len(additions),
        "previous_manifest_sha256": previous_manifest_sha256,
        "ingest_pack_present": bool(additions),
        "files": {
            name: {"bytes": len(text.encode("utf-8")), "sha256": _sha256(text)}
            for name, text in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest)
    return documents


def write_sec_filings_release(
    watch: SecWatch,
    source_documents: Mapping[str, bytes],
    output_dir: str | Path,
    *,
    retrieved_at: str,
    previous_release: str | Path | None = None,
) -> dict[str, Any]:
    documents = build_sec_filings_release_documents(
        watch,
        source_documents,
        retrieved_at=retrieved_at,
        previous_release=previous_release,
    )
    destination = Path(output_dir)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            item.relative_to(destination).as_posix()
            for item in destination.rglob("*")
            if item.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != text.encode("utf-8")
            for name, text in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, text in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }


def load_local_sec_sources(
    watch: SecWatch,
    source_dir: str | Path,
) -> dict[str, bytes]:
    root = Path(source_dir)
    return {
        entity.id: (root / entity.source_file).read_bytes()
        for entity in watch.entities
    }


def _validate_user_agent(user_agent: str) -> str:
    value = _text(user_agent, "user_agent")
    if not CONTACT_PATTERN.search(value):
        raise ValueError("SEC user_agent must include a contact email address")
    return value


def fetch_sec_sources(
    watch: SecWatch,
    *,
    user_agent: str,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    minimum_interval_seconds: float = 0.12,
) -> dict[str, bytes]:
    declared_agent = _validate_user_agent(user_agent)
    if minimum_interval_seconds < 0.1:
        raise ValueError("SEC request interval must be at least 0.1 seconds")
    documents = {}
    for index, entity in enumerate(watch.entities):
        if index:
            sleep(minimum_interval_seconds)
        request = Request(
            entity.source_url,
            headers={
                "User-Agent": declared_agent,
                "Accept": "application/json",
            },
        )
        with opener(request, timeout=30) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(f"SEC returned HTTP {status} for {entity.id}")
            raw = response.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError(f"{entity.id} SEC source exceeds the size limit")
        documents[entity.id] = raw
    return documents


def fetch_sec_filings_release(
    watch: SecWatch,
    output_dir: str | Path,
    *,
    retrieved_at: str,
    user_agent: str,
    previous_release: str | Path | None = None,
) -> dict[str, Any]:
    sources = fetch_sec_sources(watch, user_agent=user_agent)
    return write_sec_filings_release(
        watch,
        sources,
        output_dir,
        retrieved_at=retrieved_at,
        previous_release=previous_release,
    )
