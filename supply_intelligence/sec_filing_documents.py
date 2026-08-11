"""Hash-pinned capture releases for selected SEC filing documents."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .release import _csv, _json
from .sec_filings_adapter import (
    ACCESSION_PATTERN,
    CONTACT_PATTERN,
    ENTITY_ID_PATTERN,
    SEC_FILINGS_FORMAT,
    _list,
    _load_previous_release,
    _mapping,
    _normalized_timestamp,
    _text,
)


SEC_FILING_SELECTION_FORMAT = "ai-supply-sec-filing-selection.v1"
SEC_FILING_DOCUMENTS_FORMAT = "ai-supply-sec-filing-documents.v1"
SEC_FILING_DOCUMENTS_RELEASE_FORMAT = "ai-supply-sec-filing-documents-release.v1"
MAX_DOCUMENT_BYTES = 100_000_000
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class SecFilingDocumentRequest:
    accession_number: str
    review_reason: str
    expected_sha256: str | None


@dataclass(frozen=True, slots=True)
class SecFilingDocumentSelection:
    id: str
    source_manifest_sha256: str
    requests: tuple[SecFilingDocumentRequest, ...]
    document: bytes


def load_sec_filing_document_selection(
    path: str | Path,
) -> SecFilingDocumentSelection:
    source = Path(path)
    raw = source.read_bytes()
    try:
        value = _mapping(json.loads(raw), "selection")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC filing selection JSON: {exc}") from exc
    if value.get("format") != SEC_FILING_SELECTION_FORMAT:
        raise ValueError(f"selection format must be {SEC_FILING_SELECTION_FORMAT}")
    unexpected = set(value) - {
        "format",
        "id",
        "source_manifest_sha256",
        "filings",
    }
    if unexpected:
        raise ValueError(f"unexpected selection fields: {sorted(unexpected)}")
    selection_id = _text(value.get("id"), "selection.id")
    if not ENTITY_ID_PATTERN.fullmatch(selection_id):
        raise ValueError("selection.id must be a lowercase slug")
    manifest_sha256 = _text(
        value.get("source_manifest_sha256"),
        "selection.source_manifest_sha256",
    )
    if not SHA256_PATTERN.fullmatch(manifest_sha256):
        raise ValueError("selection.source_manifest_sha256 must be lowercase SHA-256")
    requests = []
    for index, item_value in enumerate(_list(value.get("filings"), "selection.filings")):
        path_name = f"selection.filings[{index}]"
        item = _mapping(item_value, path_name)
        if unexpected := set(item) - {
            "accession_number",
            "review_reason",
            "expected_sha256",
        }:
            raise ValueError(f"unexpected {path_name} fields: {sorted(unexpected)}")
        accession = _text(item.get("accession_number"), f"{path_name}.accession_number")
        if not ACCESSION_PATTERN.fullmatch(accession):
            raise ValueError(f"{path_name}.accession_number is invalid")
        expected = item.get("expected_sha256")
        if expected is not None:
            expected = _text(expected, f"{path_name}.expected_sha256")
            if not SHA256_PATTERN.fullmatch(expected):
                raise ValueError(f"{path_name}.expected_sha256 must be lowercase SHA-256")
        requests.append(
            SecFilingDocumentRequest(
                accession_number=accession,
                review_reason=_text(item.get("review_reason"), f"{path_name}.review_reason"),
                expected_sha256=expected,
            )
        )
    if not requests:
        raise ValueError("selection.filings requires at least one filing")
    if len({item.accession_number for item in requests}) != len(requests):
        raise ValueError("selection filing accessions must be unique")
    return SecFilingDocumentSelection(
        id=selection_id,
        source_manifest_sha256=manifest_sha256,
        requests=tuple(requests),
        document=raw,
    )


def resolve_sec_filing_document_selection(
    filings_release: str | Path,
    selection: SecFilingDocumentSelection,
) -> tuple[list[dict[str, Any]], bytes]:
    filings, manifest_sha256 = _load_previous_release(filings_release)
    if manifest_sha256 != selection.source_manifest_sha256:
        raise ValueError("SEC filings release manifest SHA-256 does not match selection")
    if filings.get("format") != SEC_FILINGS_FORMAT:
        raise ValueError(f"source filings format must be {SEC_FILINGS_FORMAT}")
    by_accession = {
        item["accession_number"]: item
        for item in _list(filings.get("filings"), "source filings")
    }
    selected = []
    for request in selection.requests:
        filing = by_accession.get(request.accession_number)
        if filing is None:
            raise ValueError(
                f"selected accession is absent from source release: {request.accession_number}"
            )
        selected.append({**filing, "review_reason": request.review_reason})
    return selected, (Path(filings_release) / "manifest.json").read_bytes()


def _document_relative_path(filing: Mapping[str, Any]) -> str:
    accession = str(filing["accession_number"]).replace("-", "")
    return f"documents/{accession}/{filing['primary_document']}"


def load_local_sec_filing_documents(
    selected_filings: list[Mapping[str, Any]],
    source_dir: str | Path,
) -> dict[str, bytes]:
    root = Path(source_dir)
    return {
        str(filing["accession_number"]): (
            root
            / str(filing["accession_number"]).replace("-", "")
            / str(filing["primary_document"])
        ).read_bytes()
        for filing in selected_filings
    }


def _media_type(file_name: str) -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or "application/octet-stream"


def _dashboard_rows(documents: list[Mapping[str, Any]]) -> str:
    return "".join(
        "<tr>"
        f"<td><strong>{escape(str(item['company_name']))}</strong>"
        f"<span>CIK {escape(str(item['cik']))}</span></td>"
        f"<td><code>{escape(str(item['form']))}</code></td>"
        f"<td>{escape(str(item['filing_date']))}</td>"
        f"<td>{escape(str(item['review_reason']))}</td>"
        f"<td><a href=\"{escape(str(item['local_document']), quote=True)}\">Local copy</a> · "
        f"<a href=\"{escape(str(item['source_url']), quote=True)}\">SEC</a></td>"
        f"<td><code>{escape(str(item['content_sha256'])[:16])}…</code>"
        f"<span>{int(item['byte_count']):,} bytes</span></td>"
        "</tr>"
        for item in documents
    )


def render_sec_filing_documents_dashboard(result: Mapping[str, Any]) -> str:
    documents = _list(result.get("documents"), "result.documents")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEC filing review · {escape(str(result['selection_id']))}</title><style>
:root {{ --ink:#17201d;--muted:#64716c;--paper:#f3f0e9;--panel:#fffdf8;--line:#d8d4c9;
--teal:#08786b;--amber:#a86112; }} *{{box-sizing:border-box}} body{{margin:0;background:var(--paper);
color:var(--ink);font:15px/1.45 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{width:min(1400px,calc(100% - 40px));margin:auto;padding:42px 0 64px}} header{{display:flex;
justify-content:space-between;gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:24px}}
.eyebrow{{color:var(--teal);font:700 12px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}}
h1{{font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif;margin:8px 0 6px}} .meta,.subtle,td span{{color:var(--muted)}}
.meta{{text-align:right}} .warning{{margin:22px 0;padding:18px 20px;border:1px solid #d7a45d;background:#fff3dc;
display:grid;grid-template-columns:170px 1fr;gap:20px}} .warning strong{{color:var(--amber)}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}} .card,.panel{{background:var(--panel);border:1px solid var(--line)}}
.card{{padding:20px}} .card b{{display:block;font:700 34px ui-monospace,monospace;margin-top:8px}}
.panel{{margin-top:22px;overflow:hidden}} .panel-head{{padding:20px;border-bottom:1px solid var(--line)}}
h2{{font:700 27px Georgia,serif;margin:4px 0}} .table-wrap{{overflow-x:auto}} table{{width:100%;min-width:1050px;border-collapse:collapse}}
th,td{{padding:14px 16px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}} th{{color:var(--muted);font-size:11px;
letter-spacing:.08em;text-transform:uppercase}} tr:last-child td{{border:0}} td span{{display:block;font-size:12px;margin-top:3px}}
a{{color:var(--teal);text-underline-offset:3px}} footer{{margin-top:24px;color:var(--muted);font-size:13px}}
@media(max-width:760px){{main{{width:calc(100% - 24px);padding-top:24px}}header{{align-items:start;flex-direction:column}}.meta{{text-align:left}}
.warning{{grid-template-columns:1fr}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><div class="eyebrow">AI Supply Intelligence · evidence capture</div>
<h1>SEC filing review queue</h1><div class="subtle">Selection {escape(str(result['selection_id']))}</div></div>
<div class="meta">Captured at<br><strong>{escape(str(result['recorded_at']))}</strong></div></header>
<section class="warning"><strong>Raw evidence, not a claim</strong><span>These documents are preserved
for reviewed extraction. Their presence does not establish production, capacity, allocation,
shipments, or an investment conclusion.</span></section><section class="cards">
<div class="card"><span class="subtle">Documents</span><b>{len(documents)}</b></div>
<div class="card"><span class="subtle">Companies</span><b>{len({item['cik'] for item in documents})}</b></div>
<div class="card"><span class="subtle">Forms</span><b>{len({item['form'] for item in documents})}</b></div></section>
<section class="panel"><div class="panel-head"><div class="eyebrow">Review queue</div><h2>Hash-pinned filing documents</h2></div>
<div class="table-wrap"><table><thead><tr><th>Company</th><th>Form</th><th>Filed</th><th>Reason</th>
<th>Document</th><th>Digest</th></tr></thead><tbody>{_dashboard_rows(documents)}</tbody></table></div></section>
<footer>Method: resolve selected accessions against a hash-verified SEC filing-event release, then
preserve the exact primary-document bytes and SEC archive URL.</footer></main></body></html>"""


def build_sec_filing_documents_release_documents(
    filings_release: str | Path,
    selection: SecFilingDocumentSelection,
    source_documents: Mapping[str, bytes],
    *,
    retrieved_at: str,
) -> dict[str, bytes]:
    selected, source_manifest = resolve_sec_filing_document_selection(
        filings_release,
        selection,
    )
    if set(source_documents) != {item.accession_number for item in selection.requests}:
        raise ValueError("filing document sources must exactly match selected accessions")
    request_by_accession = {item.accession_number: item for item in selection.requests}
    recorded_at = _normalized_timestamp(retrieved_at, "retrieved_at")
    metadata = []
    raw_documents: dict[str, bytes] = {}
    for filing in selected:
        accession = str(filing["accession_number"])
        raw = source_documents[accession]
        if not raw:
            raise ValueError(f"SEC filing document is empty: {accession}")
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"SEC filing document exceeds the size limit: {accession}")
        digest = hashlib.sha256(raw).hexdigest()
        expected = request_by_accession[accession].expected_sha256
        if expected is not None and digest != expected:
            raise ValueError(f"SEC filing document SHA-256 mismatch: {accession}")
        relative_path = _document_relative_path(filing)
        raw_documents[relative_path] = raw
        metadata.append(
            {
                **filing,
                "source_url": filing["filing_url"],
                "local_document": relative_path,
                "media_type": _media_type(str(filing["primary_document"])),
                "content_sha256": digest,
                "byte_count": len(raw),
                "retrieved_at": recorded_at,
            }
        )
    result = {
        "format": SEC_FILING_DOCUMENTS_FORMAT,
        "selection_id": selection.id,
        "recorded_at": recorded_at,
        "source_filings_manifest_sha256": selection.source_manifest_sha256,
        "document_count": len(metadata),
        "documents": metadata,
    }
    csv_fields = [
        "entity_id",
        "company_name",
        "cik",
        "accession_number",
        "form",
        "filing_date",
        "report_date",
        "review_reason",
        "primary_document",
        "source_url",
        "local_document",
        "media_type",
        "content_sha256",
        "byte_count",
        "retrieved_at",
    ]
    documents: dict[str, bytes] = {
        "selection.json": selection.document,
        "source_release_manifest.json": source_manifest,
        "documents.json": _json(result).encode("utf-8"),
        "review_queue.csv": _csv(csv_fields, metadata).encode("utf-8"),
        "dashboard.html": render_sec_filing_documents_dashboard(result).encode("utf-8"),
        "README.md": (
            f"# SEC filing document capture: {selection.id}\n\n"
            f"Captured `{len(metadata)}` exact primary documents at `{recorded_at}` from the "
            "hash-pinned filing-event release. Open `dashboard.html` first. These are raw "
            "review inputs, not extracted production, capacity, allocation, shipment, or "
            "investment claims.\n"
        ).encode("utf-8"),
        **raw_documents,
    }
    manifest = {
        "format": SEC_FILING_DOCUMENTS_RELEASE_FORMAT,
        "selection_id": selection.id,
        "recorded_at": recorded_at,
        "source_filings_manifest_sha256": selection.source_manifest_sha256,
        "document_count": len(metadata),
        "files": {
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest).encode("utf-8")
    return documents


def write_sec_filing_documents_release(
    filings_release: str | Path,
    selection: SecFilingDocumentSelection,
    source_documents: Mapping[str, bytes],
    output_dir: str | Path,
    *,
    retrieved_at: str,
) -> dict[str, Any]:
    documents = build_sec_filing_documents_release_documents(
        filings_release,
        selection,
        source_documents,
        retrieved_at=retrieved_at,
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
            (destination / name).read_bytes() != raw
            for name, raw in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, raw in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }


def _validate_user_agent(value: str) -> str:
    user_agent = _text(value, "user_agent")
    if not CONTACT_PATTERN.search(user_agent):
        raise ValueError("SEC user_agent must include a contact email address")
    return user_agent


def fetch_sec_filing_documents(
    selected_filings: list[Mapping[str, Any]],
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
    for index, filing in enumerate(selected_filings):
        if index:
            sleep(minimum_interval_seconds)
        request = Request(
            str(filing["filing_url"]),
            headers={"User-Agent": declared_agent, "Accept": "text/html,application/xhtml+xml"},
        )
        with opener(request, timeout=60) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ValueError(
                    f"SEC returned HTTP {status} for {filing['accession_number']}"
                )
            raw = response.read(MAX_DOCUMENT_BYTES + 1)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError(
                f"SEC filing document exceeds the size limit: {filing['accession_number']}"
            )
        documents[str(filing["accession_number"])] = raw
    return documents


def fetch_sec_filing_documents_release(
    filings_release: str | Path,
    selection: SecFilingDocumentSelection,
    output_dir: str | Path,
    *,
    retrieved_at: str,
    user_agent: str,
) -> dict[str, Any]:
    selected, _ = resolve_sec_filing_document_selection(filings_release, selection)
    documents = fetch_sec_filing_documents(selected, user_agent=user_agent)
    return write_sec_filing_documents_release(
        filings_release,
        selection,
        documents,
        output_dir,
        retrieved_at=retrieved_at,
    )
