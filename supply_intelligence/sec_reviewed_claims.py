"""Exact-text-anchored human review packs for SEC filing evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Mapping

from .claim_ledger import _claim_revision
from .release import _json
from .sec_filing_documents import SHA256_PATTERN
from .sec_filing_text_index import (
    SEC_FILING_TEXT_RELEASE_FORMAT,
    SEC_FILING_TEXT_RESULT_FORMAT,
)
from .sec_filings_adapter import (
    ACCESSION_PATTERN,
    ENTITY_ID_PATTERN,
    _list,
    _mapping,
    _normalized_timestamp,
    _text,
    _timestamp,
)


SEC_REVIEWED_CLAIMS_FORMAT = "ai-supply-sec-reviewed-claims.v1"
SEC_REVIEWED_CLAIMS_RESULT_FORMAT = "ai-supply-sec-reviewed-claims-result.v1"
SEC_REVIEWED_CLAIMS_RELEASE_FORMAT = "ai-supply-sec-reviewed-claims-release.v1"


@dataclass(frozen=True, slots=True)
class ReviewedClaimSpec:
    accession_number: str
    character_start: int
    character_end: int
    expected_text: str
    claim: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReviewedClaimsRecipe:
    id: str
    source_manifest_sha256: str
    recorded_at: str
    reviewer: str
    claims: tuple[ReviewedClaimSpec, ...]
    document: bytes


def load_sec_reviewed_claims_recipe(path: str | Path) -> ReviewedClaimsRecipe:
    source = Path(path)
    raw = source.read_bytes()
    try:
        value = _mapping(json.loads(raw), "recipe")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC reviewed-claims JSON: {exc}") from exc
    if value.get("format") != SEC_REVIEWED_CLAIMS_FORMAT:
        raise ValueError(f"recipe format must be {SEC_REVIEWED_CLAIMS_FORMAT}")
    if unexpected := set(value) - {
        "format",
        "id",
        "source_manifest_sha256",
        "recorded_at",
        "reviewer",
        "claims",
    }:
        raise ValueError(f"unexpected recipe fields: {sorted(unexpected)}")
    recipe_id = _text(value.get("id"), "recipe.id")
    if not ENTITY_ID_PATTERN.fullmatch(recipe_id):
        raise ValueError("recipe.id must be a lowercase slug")
    digest = _text(value.get("source_manifest_sha256"), "recipe.source_manifest_sha256")
    if not SHA256_PATTERN.fullmatch(digest):
        raise ValueError("recipe.source_manifest_sha256 must be lowercase SHA-256")
    recorded_at = _normalized_timestamp(value.get("recorded_at"), "recipe.recorded_at")
    reviewer = _text(value.get("reviewer"), "recipe.reviewer")
    claims = []
    for index, item_value in enumerate(_list(value.get("claims"), "recipe.claims")):
        path_name = f"recipe.claims[{index}]"
        item = _mapping(item_value, path_name)
        if unexpected := set(item) - {
            "accession_number",
            "character_start",
            "character_end",
            "expected_text",
            "claim",
        }:
            raise ValueError(f"unexpected {path_name} fields: {sorted(unexpected)}")
        accession = _text(item.get("accession_number"), f"{path_name}.accession_number")
        if not ACCESSION_PATTERN.fullmatch(accession):
            raise ValueError(f"{path_name}.accession_number is invalid")
        start = item.get("character_start")
        end = item.get("character_end")
        if isinstance(start, bool) or not isinstance(start, int) or start < 0:
            raise ValueError(f"{path_name}.character_start must be a nonnegative integer")
        if isinstance(end, bool) or not isinstance(end, int) or end <= start:
            raise ValueError(f"{path_name}.character_end must follow character_start")
        expected = _text(item.get("expected_text"), f"{path_name}.expected_text")
        if len(expected) > 1000:
            raise ValueError(f"{path_name}.expected_text cannot exceed 1000 characters")
        claim = _mapping(item.get("claim"), f"{path_name}.claim")
        if "evidence" in claim:
            raise ValueError(f"{path_name}.claim evidence is assigned from the pinned filing")
        claims.append(ReviewedClaimSpec(accession, start, end, expected, dict(claim)))
    if not claims:
        raise ValueError("recipe.claims requires at least one reviewed claim")
    claim_keys = [item.claim.get("claim_key") for item in claims]
    if any(not isinstance(key, str) or not key for key in claim_keys):
        raise ValueError("every reviewed claim requires claim_key")
    if len(claim_keys) != len(set(claim_keys)):
        raise ValueError("reviewed claim keys must be unique")
    return ReviewedClaimsRecipe(
        id=recipe_id,
        source_manifest_sha256=digest,
        recorded_at=recorded_at,
        reviewer=reviewer,
        claims=tuple(claims),
        document=raw,
    )


def _load_text_release(
    path: str | Path,
) -> tuple[dict[str, Any], bytes, dict[str, bytes]]:
    root = Path(path)
    manifest_raw = (root / "manifest.json").read_bytes()
    try:
        manifest = _mapping(json.loads(manifest_raw), "source manifest")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid SEC text-index manifest: {exc}") from exc
    if manifest.get("format") != SEC_FILING_TEXT_RELEASE_FORMAT:
        raise ValueError(f"source release format must be {SEC_FILING_TEXT_RELEASE_FORMAT}")
    files = _mapping(manifest.get("files"), "source manifest.files")
    actual = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file()
    }
    if actual != set(files) | {"manifest.json"}:
        raise ValueError("source SEC text release is incomplete or contains extra files")
    raw_files = {}
    for name, descriptor_value in files.items():
        descriptor = _mapping(descriptor_value, f"source manifest.files.{name}")
        raw = (root / name).read_bytes()
        if len(raw) != descriptor.get("bytes") or hashlib.sha256(raw).hexdigest() != descriptor.get(
            "sha256"
        ):
            raise ValueError(f"source SEC text release file hash mismatch: {name}")
        raw_files[name] = raw
    try:
        result = _mapping(json.loads(raw_files["result.json"]), "source text result")
        source_documents = _mapping(
            json.loads(raw_files["source_documents.json"]),
            "source documents",
        )
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("source SEC text release contains invalid metadata") from exc
    if result.get("format") != SEC_FILING_TEXT_RESULT_FORMAT:
        raise ValueError(f"source text result format must be {SEC_FILING_TEXT_RESULT_FORMAT}")
    return {"result": dict(result), "source_documents": dict(source_documents)}, manifest_raw, raw_files


def _source_by_accession(source_documents: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = [
        _mapping(item, f"source documents[{index}]")
        for index, item in enumerate(
            _list(source_documents.get("documents"), "source documents")
        )
    ]
    accessions = [
        _text(item.get("accession_number"), f"source documents[{index}].accession_number")
        for index, item in enumerate(rows)
    ]
    if len(accessions) != len(set(accessions)):
        raise ValueError("source SEC documents contain duplicate accessions")
    return dict(zip(accessions, rows, strict=True))


def _claim_rows(items: list[Mapping[str, Any]]) -> str:
    return "".join(
        "<tr>"
        f"<td><strong>{escape(str(item['claim']['subject']))}</strong>"
        f"<span>{escape(str(item['accession_number']))}</span></td>"
        f"<td>{escape(str(item['claim']['predicate']))}</td>"
        f"<td><code>{escape(json.dumps(item['claim']['value'], ensure_ascii=False))}</code>"
        f"<span>{escape(str(item['claim']['unit']))}</span></td>"
        f"<td>{escape(str(item['claim']['dimensions']['period']))}<span>"
        f"{escape(str(item['claim']['dimensions']['stage']))} · "
        f"{escape(str(item['claim']['dimensions']['capacity_basis']))}</span></td>"
        f"<td>{escape(str(item['expected_text']))}<span>chars "
        f"{item['character_start']}:{item['character_end']}</span></td>"
        "</tr>"
        for item in items
    )


def render_sec_reviewed_claims_dashboard(result: Mapping[str, Any]) -> str:
    items = _list(result.get("reviewed_claims"), "result.reviewed_claims")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Reviewed SEC claims</title><style>
:root{{--ink:#17201d;--muted:#64716c;--paper:#f3f0e9;--panel:#fffdf8;--line:#d8d4c9;--teal:#08786b;--amber:#a86112}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 ui-sans-serif,-apple-system,"Segoe UI",sans-serif}}main{{width:min(1400px,calc(100% - 40px));margin:auto;padding:42px 0 64px}}
header{{display:flex;justify-content:space-between;gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:24px}}.eyebrow{{color:var(--teal);font:700 12px ui-monospace,monospace;letter-spacing:.12em;text-transform:uppercase}}
h1{{font:700 clamp(34px,5vw,62px)/1.02 Georgia,serif;margin:8px 0 6px}}.muted,td span{{color:var(--muted)}}.meta{{text-align:right}}.warning{{margin:22px 0;padding:18px 20px;border:1px solid #d7a45d;background:#fff3dc;display:grid;grid-template-columns:180px 1fr;gap:20px}}.warning strong{{color:var(--amber)}}
.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}.card,.panel{{background:var(--panel);border:1px solid var(--line)}}.card{{padding:20px}}.card b{{display:block;font:700 34px ui-monospace,monospace;margin-top:8px}}.panel{{margin-top:22px;overflow:hidden}}.head{{padding:20px;border-bottom:1px solid var(--line)}}h2{{font:700 27px Georgia,serif;margin:4px 0}}
.wrap{{overflow-x:auto}}table{{width:100%;min-width:1100px;border-collapse:collapse}}th,td{{padding:14px 16px;border-bottom:1px solid var(--line);vertical-align:top;text-align:left}}th{{color:var(--muted);font-size:11px;letter-spacing:.08em;text-transform:uppercase}}tr:last-child td{{border:0}}td span{{display:block;font-size:12px;margin-top:3px}}code{{font-size:12px}}footer{{margin-top:24px;color:var(--muted);font-size:13px}}
@media(max-width:760px){{main{{width:calc(100% - 24px);padding-top:24px}}header{{align-items:start;flex-direction:column}}.meta{{text-align:left}}.warning{{grid-template-columns:1fr}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><div class="eyebrow">AI Supply Intelligence · reviewed evidence</div><h1>SEC claim authoring gate</h1><div class="muted">Recipe {escape(str(result['recipe_id']))}</div></div>
<div class="meta">Reviewer<br><strong>{escape(str(result['reviewer']))}</strong><br>{escape(str(result['recorded_at']))}</div></header>
<section class="warning"><strong>Anchor is not interpretation</strong><span>An exact text match proves
what source passage was reviewed. It does not prove the analyst's scope or numeric interpretation;
downstream manufacturing and other domain gates remain authoritative.</span></section>
<section class="cards"><div class="card"><span class="muted">Reviewed claims</span><b>{len(items)}</b></div><div class="card"><span class="muted">Source filings</span><b>{len({item['accession_number'] for item in items})}</b></div><div class="card"><span class="muted">Claim postures</span><b>{len({item['claim']['posture'] for item in items})}</b></div></section>
<section class="panel"><div class="head"><div class="eyebrow">Authoring audit</div><h2>Exact text anchors and explicit scope</h2></div><div class="wrap"><table><thead><tr><th>Subject</th><th>Predicate</th><th>Value</th><th>Scope</th><th>Anchor</th></tr></thead><tbody>{_claim_rows(items)}</tbody></table></div></section>
<footer>Method: verify each expected passage against the pinned normalized filing text at the exact
half-open character interval, attach the original raw filing as primary evidence, then validate the
claim object with the common ledger contract.</footer></main></body></html>"""


def build_sec_reviewed_claims_release_documents(
    text_release: str | Path,
    recipe: ReviewedClaimsRecipe,
) -> dict[str, bytes]:
    source, source_manifest, source_files = _load_text_release(text_release)
    source_digest = hashlib.sha256(source_manifest).hexdigest()
    if source_digest != recipe.source_manifest_sha256:
        raise ValueError("SEC text release manifest SHA-256 does not match recipe")
    source_documents = _source_by_accession(source["source_documents"])
    text_rows = [
        _mapping(item, f"source text documents[{index}]")
        for index, item in enumerate(
            _list(source["result"].get("documents"), "source text documents")
        )
    ]
    text_accessions = [
        _text(item.get("accession_number"), f"source text documents[{index}].accession_number")
        for index, item in enumerate(text_rows)
    ]
    if len(text_accessions) != len(set(text_accessions)):
        raise ValueError("source SEC text result contains duplicate accessions")
    text_documents = dict(zip(text_accessions, text_rows, strict=True))
    reviewed = []
    source_ids = {}
    used_accessions = []
    for index, spec in enumerate(recipe.claims):
        document = text_documents.get(spec.accession_number)
        metadata = source_documents.get(spec.accession_number)
        if document is None or metadata is None:
            raise ValueError(f"reviewed accession is absent from text release: {spec.accession_number}")
        text_file = _text(document.get("text_file"), "source text_file")
        text_raw = source_files.get(text_file)
        if text_raw is None:
            raise ValueError(f"normalized filing text is absent: {text_file}")
        if hashlib.sha256(text_raw).hexdigest() != document.get("text_sha256"):
            raise ValueError(f"normalized filing text metadata hash mismatch: {text_file}")
        text = text_raw.decode("utf-8").rstrip("\n")
        if spec.character_end > len(text):
            raise ValueError(f"reviewed text anchor exceeds document: {spec.accession_number}")
        actual = text[spec.character_start : spec.character_end]
        if actual != spec.expected_text:
            raise ValueError(f"reviewed text anchor mismatch: {spec.accession_number}")
        retrieved_at = _timestamp(metadata.get("retrieved_at"), "source retrieved_at")
        if _timestamp(recipe.recorded_at, "recipe.recorded_at") < retrieved_at:
            raise ValueError("reviewed claim recorded_at cannot precede source retrieval")
        source_id = f"sec-filing-{spec.accession_number.replace('-', '')}"
        source_ids[spec.accession_number] = source_id
        claim = dict(spec.claim)
        claim["methodology"] = (
            _text(claim.get("methodology"), f"claims[{index}].methodology")
            + f" Exact evidence anchor: normalized filing text characters "
            f"[{spec.character_start}, {spec.character_end}) for accession "
            f"{spec.accession_number}."
        )
        claim["evidence"] = [
            {
                "source_id": source_id,
                "role": "primary",
                "independence_group": f"sec-edgar-filing-{spec.accession_number}",
            }
        ]
        _claim_revision(
            claim,
            f"claims[{index}]",
            recipe.recorded_at,
            {source_id: f"snapshot:{'0' * 32}"},
        )
        reviewed.append(
            {
                "accession_number": spec.accession_number,
                "character_start": spec.character_start,
                "character_end": spec.character_end,
                "expected_text": spec.expected_text,
                "text_file": text_file,
                "raw_source_document": document["source_document"],
                "claim": claim,
            }
        )
        if spec.accession_number not in used_accessions:
            used_accessions.append(spec.accession_number)
    pack_sources = []
    copied_sources = {}
    for accession in used_accessions:
        metadata = source_documents[accession]
        document = text_documents[accession]
        raw_source_path = f"sources/{document['source_document']}"
        raw = source_files.get(raw_source_path)
        if raw is None:
            raise ValueError(f"raw filing source is absent: {raw_source_path}")
        raw_digest = hashlib.sha256(raw).hexdigest()
        if raw_digest != metadata.get("content_sha256") or raw_digest != document.get(
            "source_sha256"
        ):
            raise ValueError(f"raw filing source metadata hash mismatch: {accession}")
        output_source_path = raw_source_path
        copied_sources[output_source_path] = raw
        text_path = document["text_file"]
        copied_sources[text_path] = source_files[text_path]
        pack_sources.append(
            {
                "id": source_ids[accession],
                "content_file": output_source_path,
                "expected_sha256": metadata["content_sha256"],
                "capture_kind": "raw_source",
                "media_type": metadata["media_type"],
                "source_url": metadata["source_url"],
                "publisher": "U.S. Securities and Exchange Commission",
                "source_family": f"sec-edgar-filing-{accession}",
                "published_at": metadata["filing_date"],
                "retrieved_at": metadata["retrieved_at"],
                "license": "SEC website terms",
            }
        )
    pack = {
        "format": "ai-supply-ingest-pack.v1",
        "recorded_at": recipe.recorded_at,
        "sources": pack_sources,
        "claims": [item["claim"] for item in reviewed],
    }
    result = {
        "format": SEC_REVIEWED_CLAIMS_RESULT_FORMAT,
        "recipe_id": recipe.id,
        "source_manifest_sha256": source_digest,
        "recorded_at": recipe.recorded_at,
        "reviewer": recipe.reviewer,
        "claim_count": len(reviewed),
        "reviewed_claims": reviewed,
    }
    documents: dict[str, bytes] = {
        "recipe.json": recipe.document,
        "source_release_manifest.json": source_manifest,
        "result.json": _json(result).encode("utf-8"),
        "ingest_pack.json": _json(pack).encode("utf-8"),
        "dashboard.html": render_sec_reviewed_claims_dashboard(result).encode("utf-8"),
        "README.md": (
            f"# Reviewed SEC claims: {recipe.id}\n\n"
            f"Reviewer `{recipe.reviewer}` anchored `{len(reviewed)}` claims to exact normalized "
            f"text ranges at `{recipe.recorded_at}`. Text anchors prove source location, not the "
            "interpretation. Run downstream scope gates before using any claim as a model input.\n"
        ).encode("utf-8"),
        **copied_sources,
    }
    manifest = {
        "format": SEC_REVIEWED_CLAIMS_RELEASE_FORMAT,
        "recipe_id": recipe.id,
        "source_manifest_sha256": source_digest,
        "recorded_at": recipe.recorded_at,
        "reviewer": recipe.reviewer,
        "claim_count": len(reviewed),
        "files": {
            name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            for name, raw in sorted(documents.items())
        },
    }
    documents["manifest.json"] = _json(manifest).encode("utf-8")
    return documents


def write_sec_reviewed_claims_release(
    text_release: str | Path,
    recipe: ReviewedClaimsRecipe,
    output_dir: str | Path,
) -> dict[str, Any]:
    documents = build_sec_reviewed_claims_release_documents(text_release, recipe)
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
