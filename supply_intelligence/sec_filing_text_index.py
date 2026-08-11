"""Deterministic text and literal-hit indexes for captured SEC filings."""

from __future__ import annotations

import codecs
import hashlib
import json
import re
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

from .release import _csv, _json
from .sec_filing_documents import (
    SEC_FILING_DOCUMENTS_FORMAT,
    SEC_FILING_DOCUMENTS_RELEASE_FORMAT,
    SHA256_PATTERN,
)
from .sec_filings_adapter import ENTITY_ID_PATTERN, _list, _mapping, _text


SEC_FILING_TEXT_RECIPE_FORMAT = "ai-supply-sec-filing-text-index.v1"
SEC_FILING_TEXT_RESULT_FORMAT = "ai-supply-sec-filing-text-result.v1"
SEC_FILING_TEXT_RELEASE_FORMAT = "ai-supply-sec-filing-text-release.v1"
SUPPORTED_MEDIA_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "text/plain",
}
CHARSET_PATTERN = re.compile(br"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", re.I)


@dataclass(frozen=True, slots=True)
class FilingTextTerm:
    id: str
    label: str
    category: str
    literal: str


@dataclass(frozen=True, slots=True)
class FilingTextRecipe:
    id: str
    source_manifest_sha256: str
    context_characters: int
    max_hits_per_term_per_document: int
    terms: tuple[FilingTextTerm, ...]
    document: bytes


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


def load_sec_filing_text_recipe(path: str | Path) -> FilingTextRecipe:
    source = Path(path)
    raw = source.read_bytes()
    try:
        value = _mapping(json.loads(raw), "recipe")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC filing text recipe JSON: {exc}") from exc
    if value.get("format") != SEC_FILING_TEXT_RECIPE_FORMAT:
        raise ValueError(f"recipe format must be {SEC_FILING_TEXT_RECIPE_FORMAT}")
    if unexpected := set(value) - {
        "format",
        "id",
        "source_manifest_sha256",
        "context_characters",
        "max_hits_per_term_per_document",
        "terms",
    }:
        raise ValueError(f"unexpected recipe fields: {sorted(unexpected)}")
    recipe_id = _text(value.get("id"), "recipe.id")
    if not ENTITY_ID_PATTERN.fullmatch(recipe_id):
        raise ValueError("recipe.id must be a lowercase slug")
    source_digest = _text(
        value.get("source_manifest_sha256"),
        "recipe.source_manifest_sha256",
    )
    if not SHA256_PATTERN.fullmatch(source_digest):
        raise ValueError("recipe.source_manifest_sha256 must be lowercase SHA-256")
    context = value.get("context_characters")
    if isinstance(context, bool) or not isinstance(context, int) or not 40 <= context <= 500:
        raise ValueError("recipe.context_characters must be an integer from 40 to 500")
    maximum = value.get("max_hits_per_term_per_document")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 500:
        raise ValueError(
            "recipe.max_hits_per_term_per_document must be an integer from 1 to 500"
        )
    terms = []
    for index, item_value in enumerate(_list(value.get("terms"), "recipe.terms")):
        path_name = f"recipe.terms[{index}]"
        item = _mapping(item_value, path_name)
        if unexpected := set(item) - {"id", "label", "category", "literal"}:
            raise ValueError(f"unexpected {path_name} fields: {sorted(unexpected)}")
        term_id = _text(item.get("id"), f"{path_name}.id")
        if not ENTITY_ID_PATTERN.fullmatch(term_id):
            raise ValueError(f"{path_name}.id must be a lowercase slug")
        literal = _text(item.get("literal"), f"{path_name}.literal")
        if len(literal) > 200:
            raise ValueError(f"{path_name}.literal cannot exceed 200 characters")
        terms.append(
            FilingTextTerm(
                id=term_id,
                label=_text(item.get("label"), f"{path_name}.label"),
                category=_text(item.get("category"), f"{path_name}.category"),
                literal=literal,
            )
        )
    if not terms:
        raise ValueError("recipe.terms requires at least one term")
    if len({term.id for term in terms}) != len(terms):
        raise ValueError("recipe term IDs must be unique")
    if len({term.literal.casefold() for term in terms}) != len(terms):
        raise ValueError("recipe term literals must be case-insensitively unique")
    return FilingTextRecipe(
        id=recipe_id,
        source_manifest_sha256=source_digest,
        context_characters=context,
        max_hits_per_term_per_document=maximum,
        terms=tuple(terms),
        document=raw,
    )


def _load_document_release(
    path: str | Path,
) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    root = Path(path)
    manifest_raw = (root / "manifest.json").read_bytes()
    try:
        manifest = _mapping(json.loads(manifest_raw), "source manifest")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC document manifest: {exc}") from exc
    if manifest.get("format") != SEC_FILING_DOCUMENTS_RELEASE_FORMAT:
        raise ValueError(
            f"source release format must be {SEC_FILING_DOCUMENTS_RELEASE_FORMAT}"
        )
    files = _mapping(manifest.get("files"), "source manifest.files")
    actual_files = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    }
    if actual_files != set(files) | {"manifest.json"}:
        raise ValueError("source SEC document release is incomplete or contains extra files")
    raw_files = {}
    for name, descriptor_value in files.items():
        descriptor = _mapping(descriptor_value, f"source manifest.files.{name}")
        raw = (root / name).read_bytes()
        if len(raw) != descriptor.get("bytes") or hashlib.sha256(raw).hexdigest() != descriptor.get(
            "sha256"
        ):
            raise ValueError(f"source SEC document release file hash mismatch: {name}")
        raw_files[name] = raw
    try:
        result = _mapping(json.loads(raw_files["documents.json"]), "source documents")
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("source SEC document release has invalid documents.json") from exc
    if result.get("format") != SEC_FILING_DOCUMENTS_FORMAT:
        raise ValueError(f"source documents format must be {SEC_FILING_DOCUMENTS_FORMAT}")
    return dict(result), manifest_raw, raw_files


def _decode_document(raw: bytes) -> tuple[str, str]:
    candidates = []
    match = CHARSET_PATTERN.search(raw[:8192])
    if match:
        candidates.append(match.group(1).decode("ascii", errors="ignore"))
    candidates.extend(["utf-8-sig", "cp1252"])
    seen = set()
    for encoding in candidates:
        try:
            normalized = codecs.lookup(encoding).name
        except LookupError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return raw.decode(normalized), normalized
        except UnicodeDecodeError:
            continue
    raise ValueError("SEC filing document text encoding is unsupported")


def _visible_text(raw: bytes, media_type: str) -> tuple[str, str]:
    if media_type not in SUPPORTED_MEDIA_TYPES:
        raise ValueError(f"SEC filing media type is unsupported for text indexing: {media_type}")
    decoded, encoding = _decode_document(raw)
    if media_type == "text/plain":
        parts = [decoded]
    else:
        parser = _VisibleTextParser()
        parser.feed(decoded)
        parser.close()
        parts = parser.parts
    text = " ".join(" ".join(parts).split())
    return text, encoding


def _term_hits(
    text: str,
    term: FilingTextTerm,
    *,
    context: int,
    maximum: int,
) -> tuple[list[dict[str, Any]], int]:
    hits = []
    occurrence_count = 0
    for match in re.finditer(re.escape(term.literal), text, flags=re.IGNORECASE):
        occurrence_count += 1
        if len(hits) >= maximum:
            continue
        start = max(0, match.start() - context)
        end = min(len(text), match.end() + context)
        hits.append(
            {
                "term_id": term.id,
                "term_label": term.label,
                "category": term.category,
                "literal": term.literal,
                "occurrence": occurrence_count,
                "character_start": match.start(),
                "character_end": match.end(),
                "snippet": text[start:end],
            }
        )
    return hits, occurrence_count - len(hits)


def _hit_rows(hits: list[Mapping[str, Any]]) -> str:
    if not hits:
        return '<tr><td colspan="5" class="empty">No configured terms matched.</td></tr>'
    return "".join(
        "<tr>"
        f"<td><strong>{escape(str(item['company_name']))}</strong>"
        f"<span>{escape(str(item['form']))} · {escape(str(item['filing_date']))}</span></td>"
        f"<td>{escape(str(item['term_label']))}<span>{escape(str(item['category']))}</span></td>"
        f"<td>{int(item['occurrence'])}</td>"
        f"<td>{escape(str(item['snippet']))}</td>"
        f"<td><code>{int(item['character_start'])}:{int(item['character_end'])}</code></td>"
        "</tr>"
        for item in hits
    )


def render_sec_filing_text_dashboard(result: Mapping[str, Any]) -> str:
    hits = _list(result.get("hits"), "result.hits")
    documents = _list(result.get("documents"), "result.documents")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SEC evidence hits</title><style>
:root{{--ink:#17201d;--muted:#64716c;--paper:#f3f0e9;--panel:#fffdf8;--line:#d8d4c9;--teal:#08786b;--amber:#a86112}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 ui-sans-serif,-apple-system,"Segoe UI",sans-serif}}
main{{width:min(1400px,calc(100% - 40px));margin:auto;padding:42px 0 64px}}header{{display:flex;justify-content:space-between;gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:24px}}
.eyebrow{{color:var(--teal);font:700 12px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}}h1{{font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif;margin:8px 0 6px}}
.muted,td span{{color:var(--muted)}}.meta{{text-align:right}}.warning{{margin:22px 0;padding:18px 20px;border:1px solid #d7a45d;background:#fff3dc;display:grid;grid-template-columns:170px 1fr;gap:20px}}
.warning strong{{color:var(--amber)}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.card,.panel{{background:var(--panel);border:1px solid var(--line)}}.card{{padding:20px}}.card b{{display:block;font:700 34px ui-monospace,monospace;margin-top:8px}}
.panel{{margin-top:22px;overflow:hidden}}.head{{padding:20px;border-bottom:1px solid var(--line)}}h2{{font:700 27px Georgia,serif;margin:4px 0}}.wrap{{overflow-x:auto}}table{{width:100%;min-width:1050px;border-collapse:collapse}}
th,td{{padding:14px 16px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}th{{color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase}}tr:last-child td{{border:0}}td span{{display:block;font-size:12px;margin-top:3px}}code{{font-size:12px}}.empty{{text-align:center;color:var(--muted)}}footer{{margin-top:24px;color:var(--muted);font-size:13px}}
@media(max-width:760px){{main{{width:calc(100% - 24px);padding-top:24px}}header{{align-items:start;flex-direction:column}}.meta{{text-align:left}}.warning{{grid-template-columns:1fr}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><div class="eyebrow">AI Supply Intelligence · filing text index</div><h1>SEC evidence-hit review</h1>
<div class="muted">Recipe {escape(str(result['recipe_id']))}</div></div><div class="meta">Source manifest<br><code>{escape(str(result['source_manifest_sha256'])[:16])}…</code></div></header>
<section class="warning"><strong>Hits are not claims</strong><span>Literal matches are review aids.
They do not prove that a disclosure applies to a product, quarter, capacity basis, customer, or
production estimate.</span></section><section class="cards"><div class="card"><span class="muted">Documents</span><b>{len(documents)}</b></div>
<div class="card"><span class="muted">Configured terms</span><b>{len(result['terms'])}</b></div><div class="card"><span class="muted">Visible hits</span><b>{len(hits)}</b></div></section>
<section class="panel"><div class="head"><div class="eyebrow">Evidence queue</div><h2>Literal matches with normalized-text offsets</h2></div><div class="wrap"><table><thead><tr><th>Filing</th><th>Term</th><th>#</th><th>Context</th><th>Offset</th></tr></thead>
<tbody>{_hit_rows(hits)}</tbody></table></div></section><footer>Method: decode each hash-pinned primary document, remove script and style content, normalize whitespace, then run case-insensitive literal matching. Offsets address the preserved normalized text file, not raw HTML.</footer>
</main></body></html>"""


def build_sec_filing_text_release_documents(
    document_release: str | Path,
    recipe: FilingTextRecipe,
) -> dict[str, bytes]:
    source, source_manifest, source_files = _load_document_release(document_release)
    manifest_digest = hashlib.sha256(source_manifest).hexdigest()
    if manifest_digest != recipe.source_manifest_sha256:
        raise ValueError("SEC filing document manifest SHA-256 does not match recipe")
    document_rows = []
    hit_rows = []
    copied_sources: dict[str, bytes] = {}
    for item_value in _list(source.get("documents"), "source.documents"):
        item = _mapping(item_value, "source document")
        relative = _text(item.get("local_document"), "source document.local_document")
        raw = source_files.get(relative)
        if raw is None:
            raise ValueError(f"source document is absent from release: {relative}")
        if hashlib.sha256(raw).hexdigest() != item.get("content_sha256"):
            raise ValueError(f"source document metadata hash mismatch: {relative}")
        text, encoding = _visible_text(raw, _text(item.get("media_type"), "media_type"))
        accession = _text(item.get("accession_number"), "accession_number")
        text_path = f"text/{accession.replace('-', '')}.txt"
        text_bytes = (text + "\n").encode("utf-8")
        matched_terms = []
        document_hits = []
        truncated = 0
        for term in recipe.terms:
            hits, omitted = _term_hits(
                text,
                term,
                context=recipe.context_characters,
                maximum=recipe.max_hits_per_term_per_document,
            )
            if hits:
                matched_terms.append(term.id)
            truncated += omitted
            for hit in hits:
                document_hits.append(
                    {
                        "accession_number": accession,
                        "entity_id": item["entity_id"],
                        "company_name": item["company_name"],
                        "form": item["form"],
                        "filing_date": item["filing_date"],
                        "text_file": text_path,
                        **hit,
                    }
                )
        hit_rows.extend(document_hits)
        document_rows.append(
            {
                "accession_number": accession,
                "entity_id": item["entity_id"],
                "company_name": item["company_name"],
                "form": item["form"],
                "filing_date": item["filing_date"],
                "source_document": relative,
                "source_sha256": item["content_sha256"],
                "source_encoding": encoding,
                "text_file": text_path,
                "text_sha256": hashlib.sha256(text_bytes).hexdigest(),
                "character_count": len(text),
                "word_count": len(text.split()),
                "hit_count": len(document_hits),
                "truncated_hit_count": truncated,
                "matched_term_ids": matched_terms,
            }
        )
        copied_sources[f"sources/{relative}"] = raw
        copied_sources[text_path] = text_bytes
    result = {
        "format": SEC_FILING_TEXT_RESULT_FORMAT,
        "recipe_id": recipe.id,
        "source_manifest_sha256": manifest_digest,
        "document_count": len(document_rows),
        "term_count": len(recipe.terms),
        "hit_count": len(hit_rows),
        "truncated_hit_count": sum(item["truncated_hit_count"] for item in document_rows),
        "terms": [
            {"id": term.id, "label": term.label, "category": term.category, "literal": term.literal}
            for term in recipe.terms
        ],
        "documents": document_rows,
        "hits": hit_rows,
    }
    hit_fields = [
        "accession_number",
        "entity_id",
        "company_name",
        "form",
        "filing_date",
        "term_id",
        "term_label",
        "category",
        "literal",
        "occurrence",
        "character_start",
        "character_end",
        "snippet",
        "text_file",
    ]
    documents: dict[str, bytes] = {
        "recipe.json": recipe.document,
        "source_release_manifest.json": source_manifest,
        "source_documents.json": source_files["documents.json"],
        "result.json": _json(result).encode("utf-8"),
        "hits.csv": _csv(hit_fields, hit_rows).encode("utf-8"),
        "dashboard.html": render_sec_filing_text_dashboard(result).encode("utf-8"),
        "README.md": (
            f"# SEC filing text index: {recipe.id}\n\n"
            f"Indexed `{len(document_rows)}` hash-pinned documents for `{len(recipe.terms)}` "
            f"literal terms and emitted `{len(hit_rows)}` visible hits. Hits and snippets are "
            "review aids, not extracted claims. Character offsets address the normalized UTF-8 "
            "text files.\n"
        ).encode("utf-8"),
        **copied_sources,
    }
    manifest = {
        "format": SEC_FILING_TEXT_RELEASE_FORMAT,
        "recipe_id": recipe.id,
        "source_manifest_sha256": manifest_digest,
        "document_count": len(document_rows),
        "term_count": len(recipe.terms),
        "hit_count": len(hit_rows),
        "truncated_hit_count": result["truncated_hit_count"],
        "files": {
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest).encode("utf-8")
    return documents


def write_sec_filing_text_release(
    document_release: str | Path,
    recipe: FilingTextRecipe,
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_sec_filing_text_release_documents(document_release, recipe)
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
            (destination / name).read_bytes() != raw for name, raw in documents.items()
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
