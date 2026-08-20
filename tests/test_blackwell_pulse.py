from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

import supply_intelligence.blackwell_pulse_release as blackwell_pulse_release
from supply_intelligence.blackwell_pulse import (
    CLASSIFICATIONS,
    NO_EVIDENCE_BACKED_ESTIMATE,
    SYNTHETIC_AUDIT_FORMAT,
    SyntheticInputAudit,
    UPSTREAM_CLAIMS_FORMAT,
    build_blackwell_pulse,
    load_synthetic_input_audit,
    synthetic_input_audit_from_dict,
)
from supply_intelligence.blackwell_pulse_release import (
    PULSE_CONFIG_FORMAT,
    build_blackwell_pulse_release_documents,
    write_blackwell_pulse_release,
)
from supply_intelligence.cli import main
from supply_intelligence.upstream_release import (
    UPSTREAM_LOCK_FORMAT,
    UPSTREAM_LOCK_PRODUCT,
    UPSTREAM_LOCK_TARGET_QUARTER,
    UPSTREAM_MANIFEST_FORMAT,
    UPSTREAM_SCHEMA_VERSION,
    UpstreamReleaseError,
    fetch_and_load_locked_release,
    load_upstream_release_lock,
)


TEST_ONLY_NOTICE = "TEST-ONLY -- NOT PRODUCTION EVIDENCE"
WEEK_ENDING = "2026-10-11"
RECORDED_AT = "2026-10-12T02:00:00Z"
REPOSITORIES = {
    "datacenter_atlas": "kiankyars/datacenter-atlas",
    "semiconductor_atlas": "kiankyars/semiconductor-atlas",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_CONTRACT = REPOSITORY_ROOT / "contracts" / "blackwell-constraint-pulse-v1"
FIXTURE_CASES = REPOSITORY_ROOT / "tests" / "fixtures" / "blackwell-pulse" / "cases.json"
STAGE_UPSTREAMS = {
    "manufacture": "semiconductor_atlas",
    "shipment": "datacenter_atlas",
    "energization": "datacenter_atlas",
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> Path:
    path.write_bytes(_json_bytes(value))
    return path


def _range(
    low: float = 10,
    base: float = 20,
    high: float = 30,
    unit: str = "system",
) -> dict[str, Any]:
    return {"low": low, "base": base, "high": high, "unit": unit}


def _gate() -> dict[str, Any]:
    return {
        "required_for_numerical_result": True,
        "accepted_postures": ["derived", "reported"],
        "description": f"{TEST_ONLY_NOTICE}: exact scope and evidence are required.",
    }


def _requirement(stage: str, *, target: bool) -> dict[str, Any]:
    upstream = STAGE_UPSTREAMS[stage]
    suffix = "target" if target else "input"
    common = {
        "id": f"{suffix}.{stage}",
        "stage": stage,
        "unit": "system",
        "accepted_range_bases": ["bounded_interval", "exact"],
        "required_upstream": upstream,
        "required_claim_type": "numerical_constraint",
        "attribution_basis": f"test-only-{stage}-attribution",
        "time_basis": "2026-Q4 cumulative through week ending",
        "evidence_gate": _gate(),
    }
    if target:
        return {
            **common,
            "description": f"{TEST_ONLY_NOTICE}: direct {stage} system constraint.",
        }
    return {
        **common,
        "current_source": f"{TEST_ONLY_NOTICE}: frozen synthetic test range.",
        "current_range": _range(1, 2, 3),
        "current_posture": "synthetic",
        "active_for_supply_to_site": True,
        "parameter_class": "throughput",
    }


def _audit_document() -> dict[str, Any]:
    inputs = [_requirement(stage, target=False) for stage in STAGE_UPSTREAMS]
    active_ids = sorted(item["id"] for item in inputs)
    active_ids_sha256 = hashlib.sha256(
        ("\n".join(active_ids) + "\n").encode("utf-8")
    ).hexdigest()
    return {
        "format": SYNTHETIC_AUDIT_FORMAT,
        "product": "blackwell-constraint-pulse",
        "target_quarter": "2026-Q4",
        "required_upstreams": ["datacenter_atlas", "semiconductor_atlas"],
        "baseline": {
            "source_commit": "0" * 40,
            "source_quarter": "2026-Q3",
            "active_numeric_input_count": len(inputs),
            "diagnostic_numeric_input_count": 0,
            "active_input_ids_sha256": active_ids_sha256,
            "notes": f"{TEST_ONLY_NOTICE}: tiny audit exercises gate mechanics only.",
        },
        "inputs": inputs,
        "gate_targets": [
            _requirement(stage, target=True) for stage in STAGE_UPSTREAMS
        ],
        "categorical_gates": [],
        "protected_unknowns": [
            {
                "dimension": dimension,
                "policy": (
                    f"{TEST_ONLY_NOTICE}: keep {dimension} unknown without suitable "
                    "evidence."
                ),
            }
            for dimension in (
                "allocation",
                "capacity",
                "demand",
                "economics",
                "utilization",
                "yield",
            )
        ],
    }


def _tiny_audit() -> SyntheticInputAudit:
    document = _audit_document()
    raw = _json_bytes(document)
    normalized = copy.deepcopy(document)
    normalized["inputs"] = [
        {"kind": "synthetic_input", **item} for item in document["inputs"]
    ]
    normalized["gate_targets"] = [
        {"kind": "gate_target", **item} for item in document["gate_targets"]
    ]
    return SyntheticInputAudit(
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
        semantic_sha256="0" * 64,
        document=normalized,
        inputs=tuple(normalized["inputs"]),
        gate_targets=tuple(normalized["gate_targets"]),
        categorical_gates=(),
    )


def _production_audit_document() -> dict[str, Any]:
    return json.loads(
        (PRODUCTION_CONTRACT / "synthetic-input-audit.json").read_text(
            encoding="utf-8"
        )
    )


def _evidence(claim_id: str) -> list[dict[str, Any]]:
    content = f"{TEST_ONLY_NOTICE}:{claim_id}".encode("utf-8")
    return [
        {
            "id": f"evidence.{claim_id}",
            "source_url": "https://example.test/test-only-evidence",
            "publisher": TEST_ONLY_NOTICE,
            "published_at": "2026-10-08T12:00:00Z",
            "retrieved_at": "2026-10-09T12:00:00Z",
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }
    ]


def _claim(
    requirement: Mapping[str, Any],
    *,
    claim_id: str | None = None,
    claim_kind: str = "numerical",
    intended_use: str = "constraint",
    change_status: str = "added",
    value: Mapping[str, Any] | None = None,
    range_basis: str | None = "bounded_interval",
    posture: str | None = "reported",
    attribution_basis: str | None = None,
    time_basis: str | None = None,
    gate_supports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resolved_id = claim_id or f"claim.{requirement['id']}"
    missing = claim_kind == "missing" or change_status == "removed"
    if missing:
        resolved_value = None
        evidence: list[dict[str, Any]] = []
    elif claim_kind == "directional":
        resolved_value = None
        evidence = _evidence(resolved_id)
    else:
        resolved_value = dict(value or _range())
        evidence = _evidence(resolved_id)
    return {
        "id": resolved_id,
        "target_id": requirement["id"],
        "claim_kind": claim_kind,
        "intended_use": intended_use,
        "change_status": change_status,
        "summary": f"{TEST_ONLY_NOTICE}: generated {resolved_id}.",
        "value": resolved_value,
        "range_basis": None if missing or claim_kind == "directional" else range_basis,
        "posture": None if missing else posture,
        "period": "2026-Q4",
        "time_basis": time_basis or requirement["time_basis"],
        "attribution_basis": attribution_basis or requirement["attribution_basis"],
        "gate_supports": gate_supports or [],
        "evidence": evidence,
    }


def _all_valid_claims(audit_document: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    stage_ranges = {
        "manufacture": _range(120, 150, 180),
        "shipment": _range(100, 130, 160),
        "energization": _range(80, 110, 140),
    }
    result = {upstream_id: [] for upstream_id in REPOSITORIES}
    for requirement in [
        *audit_document["inputs"],
        *audit_document["gate_targets"],
    ]:
        if requirement["id"].startswith("target.") or requirement["id"].startswith(
            "gate:"
        ):
            value = stage_ranges[requirement["stage"]]
        elif requirement["unit"] == "ratio":
            value = _range(0.8, 0.9, 0.95, "ratio")
        else:
            value = _range(1, 2, 3, requirement["unit"])
        result[requirement["required_upstream"]].append(
            _claim(requirement, value=value)
        )
    for upstream_id, claims in result.items():
        supported_gates = sorted(
            (
                gate
                for gate in audit_document["categorical_gates"]
                if upstream_id in gate["required_upstreams"]
            ),
            key=lambda gate: gate["id"],
        )
        if supported_gates:
            evidence_id = claims[0]["evidence"][0]["id"]
            claims[0]["gate_supports"] = [
                {
                    "gate_id": gate["id"],
                    "assertion": gate["description"],
                    "period": "2026-Q4",
                    "time_basis": gate["time_basis"],
                    "attribution_basis": gate["attribution_basis"],
                    "posture": claims[0]["posture"],
                    "evidence_ids": [evidence_id],
                }
                for gate in supported_gates
            ]
    return result


def _zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 9, 12, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw)
    return stream.getvalue()


def _bundle(
    upstream_id: str,
    claims: list[dict[str, Any]],
    *,
    as_of_date: str = "2026-10-09",
    comparison: Mapping[str, str] | None = None,
) -> tuple[bytes, bytes]:
    repository = REPOSITORIES[upstream_id]
    release_tag = "2026-q4-test-only-week-01"
    claims_raw = _json_bytes(
        {"format": UPSTREAM_CLAIMS_FORMAT, "claims": claims}
    )
    manifest = {
        "format": UPSTREAM_MANIFEST_FORMAT,
        "schema_version": UPSTREAM_SCHEMA_VERSION,
        "upstream_id": upstream_id,
        "repository": repository,
        "release_tag": release_tag,
        "comparison": dict(comparison) if comparison is not None else None,
        "as_of_date": as_of_date,
        "recorded_at": "2026-10-09T20:00:00Z",
        "files": {
            "claims.json": {
                "bytes": len(claims_raw),
                "sha256": hashlib.sha256(claims_raw).hexdigest(),
            }
        },
    }
    manifest_raw = _json_bytes(manifest)
    return (
        _zip_bytes(
            [("manifest.json", manifest_raw), ("claims.json", claims_raw)]
        ),
        manifest_raw,
    )


def _lock_entry(
    upstream_id: str,
    bundle_raw: bytes,
    manifest_raw: bytes,
) -> dict[str, Any]:
    repository = REPOSITORIES[upstream_id]
    release_tag = "2026-q4-test-only-week-01"
    asset_name = "test-only-blackwell-claims.zip"
    return {
        "upstream_id": upstream_id,
        "repository": repository,
        "release_tag": release_tag,
        "asset": {
            "name": asset_name,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{release_tag}/{asset_name}"
            ),
            "bytes": len(bundle_raw),
            "sha256": hashlib.sha256(bundle_raw).hexdigest(),
        },
        "manifest": {
            "path": "manifest.json",
            "sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "schema_version": UPSTREAM_SCHEMA_VERSION,
        },
    }


def _lock_document(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "format": UPSTREAM_LOCK_FORMAT,
        "product": UPSTREAM_LOCK_PRODUCT,
        "target_quarter": UPSTREAM_LOCK_TARGET_QUARTER,
        "upstreams": entries,
    }


def _prepare_releases(
    root: Path,
    claims_by_upstream: Mapping[str, list[dict[str, Any]]],
    *,
    cache_name: str = "cache",
    as_of_dates: Mapping[str, str] | None = None,
    comparisons: Mapping[str, Mapping[str, str]] | None = None,
) -> tuple[Path, Path, list[Any]]:
    bundles: dict[str, bytes] = {}
    entries = []
    for upstream_id in sorted(REPOSITORIES):
        bundle_raw, manifest_raw = _bundle(
            upstream_id,
            claims_by_upstream.get(upstream_id, []),
            as_of_date=(as_of_dates or {}).get(upstream_id, "2026-10-09"),
            comparison=(comparisons or {}).get(upstream_id),
        )
        bundles[upstream_id] = bundle_raw
        entries.append(_lock_entry(upstream_id, bundle_raw, manifest_raw))
    lock_path = _write_json(root / "upstream-releases.lock.json", _lock_document(entries))
    lock = load_upstream_release_lock(lock_path)
    cache = root / cache_name
    releases = [
        fetch_and_load_locked_release(
            entry,
            cache,
            lambda _url, raw=bundles[entry.upstream_id]: raw,
        )
        for entry in lock.upstreams
    ]
    return lock_path, cache, releases


def _config_document() -> dict[str, Any]:
    return {
        "format": PULSE_CONFIG_FORMAT,
        "pulse_id": f"blackwell-constraint-pulse:{WEEK_ENDING}",
        "target_quarter": "2026-Q4",
        "week_ending": WEEK_ENDING,
        "recorded_at": RECORDED_AT,
    }


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {
        path.name: path.read_bytes()
        for path in sorted(directory.iterdir())
        if path.is_file()
    }


class BlackwellPulseTests(unittest.TestCase):
    def test_fixture_case_catalog_is_explicitly_non_production(self) -> None:
        catalog = json.loads(FIXTURE_CASES.read_text(encoding="utf-8"))
        self.assertEqual(catalog["notice"], "TEST-ONLY -- NOT PRODUCTION EVIDENCE")
        self.assertEqual(
            [item["id"] for item in catalog["cases"]],
            ["incompatible", "missing", "tampered", "valid"],
        )
        self.assertTrue(all(item["production_evidence"] is False for item in catalog["cases"]))

    def test_every_claim_is_classified_as_exactly_one_of_the_five_classes(self) -> None:
        audit_document = _audit_document()
        requirements = {
            item["id"]: item
            for item in [
                *audit_document["inputs"],
                *audit_document["gate_targets"],
            ]
        }
        claims_by_upstream = {upstream_id: [] for upstream_id in REPOSITORIES}
        cases = [
            (
                "claim.class.numerical",
                requirements["input.manufacture"],
                {},
                "numerical_constraint",
            ),
            (
                "claim.class.scale",
                requirements["input.shipment"],
                {"intended_use": "scale_control"},
                "scale_control",
            ),
            (
                "claim.class.directional",
                requirements["input.energization"],
                {"claim_kind": "directional", "intended_use": "signal"},
                "directional_evidence",
            ),
            (
                "claim.class.incompatible",
                requirements["target.manufacture"],
                {"value": _range(unit="rack")},
                "incompatible",
            ),
            (
                "claim.class.missing",
                requirements["target.shipment"],
                {"claim_kind": "missing"},
                "missing",
            ),
        ]
        for claim_id, requirement, changes, _classification in cases:
            claims_by_upstream[requirement["required_upstream"]].append(
                _claim(requirement, claim_id=claim_id, **changes)
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            audit = _tiny_audit()
            lock = load_upstream_release_lock(lock_path)
            pulse = build_blackwell_pulse(
                audit,
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=lock.sha256,
            )

        expected = {claim_id: classification for claim_id, _, _, classification in cases}
        actual = {
            item["claim_id"]: item["classification"]
            for item in pulse["claim_assessments"]
            if item["claim_id"] in expected
        }
        self.assertEqual(actual, expected)
        self.assertEqual(set(actual.values()), CLASSIFICATIONS)
        self.assertTrue(
            all(item["classification"] in CLASSIFICATIONS for item in pulse["claim_assessments"])
        )

    def test_all_explicit_evidence_gates_produce_a_numerical_system_range(self) -> None:
        audit_document = _audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            audit = _tiny_audit()
            pulse = build_blackwell_pulse(
                audit,
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        self.assertEqual(
            pulse["supply_to_site_estimate"],
            {**_range(80, 110, 140), "range_basis": "bounded_interval"},
        )
        self.assertTrue(pulse["evidence_gates"]["supply_to_site_passed"])
        self.assertTrue(
            all(stage["passed"] for stage in pulse["evidence_gates"]["stages"])
        )

    def test_changed_claims_disclose_the_unreplayed_comparison_basis(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        revised_claim = claims_by_upstream["datacenter_atlas"][0]
        revised_claim["change_status"] = "revised"
        comparison = {
            "release_tag": "2026-q4-test-only-week-00",
            "manifest_sha256": "1" * 64,
            "claims_sha256": "2" * 64,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(
                root,
                claims_by_upstream,
                comparisons={"datacenter_atlas": comparison},
            )
            pulse = build_blackwell_pulse(
                load_synthetic_input_audit(
                    PRODUCTION_CONTRACT / "synthetic-input-audit.json"
                ),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        changed = next(
            item
            for item in pulse["questions"]["what_changed"]
            if item["claim_id"] == revised_claim["id"]
        )
        self.assertEqual(changed["change_status"], "revised")
        self.assertEqual(
            changed["change_basis"],
            "upstream_reported_against_declared_comparison",
        )
        self.assertEqual(
            changed["comparison_verification"],
            "producer_asserted_not_locally_replayed",
        )
        self.assertEqual(changed["comparison"], comparison)
        self.assertIn(changed["stage"], {"manufacture", "shipment", "energization"})
        self.assertEqual(
            pulse["questions"]["what_changed_basis"],
            {
                "status": "upstream_reported",
                "comparison_assets_locally_replayed": False,
                "limitation": (
                    "The locked current release carries the producer's change status "
                    "and declared prior hashes; v1 does not fetch or replay the prior asset."
                ),
            },
        )

    def test_missing_incomplete_evidence_emits_the_exact_non_estimate(self) -> None:
        audit_document = _audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        claims_by_upstream["datacenter_atlas"] = [
            claim
            for claim in claims_by_upstream["datacenter_atlas"]
            if claim["target_id"] != "target.energization"
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            pulse = build_blackwell_pulse(
                _tiny_audit(),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        self.assertEqual(pulse["supply_to_site_estimate"], NO_EVIDENCE_BACKED_ESTIMATE)
        energization = next(
            item for item in pulse["evidence_gates"]["stages"]
            if item["stage"] == "energization"
        )
        self.assertEqual(energization["estimate"], NO_EVIDENCE_BACKED_ESTIMATE)
        self.assertEqual(energization["unresolved_gate_target_ids"], ["target.energization"])

    def test_conflicting_missing_and_numerical_claims_fail_closed(self) -> None:
        audit_document = _audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        energization_target = next(
            item
            for item in audit_document["gate_targets"]
            if item["id"] == "target.energization"
        )
        claims_by_upstream["datacenter_atlas"].append(
            _claim(
                energization_target,
                claim_id="claim.conflicting-missing-energization",
                claim_kind="missing",
            )
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            pulse = build_blackwell_pulse(
                _tiny_audit(),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        target_assessments = [
            item
            for item in pulse["claim_assessments"]
            if item["target_id"] == "target.energization"
        ]
        self.assertEqual(
            {item["classification"] for item in target_assessments},
            {"missing", "numerical_constraint"},
        )
        self.assertEqual(
            pulse["supply_to_site_estimate"],
            NO_EVIDENCE_BACKED_ESTIMATE,
        )
        energization = next(
            item
            for item in pulse["evidence_gates"]["stages"]
            if item["stage"] == "energization"
        )
        self.assertEqual(
            energization["unresolved_gate_target_ids"],
            ["target.energization"],
        )

    def test_incompatible_unit_cannot_produce_a_numerical_result(self) -> None:
        self._assert_incompatible_claim_blocks_result(
            target_id="target.shipment",
            mutation={"value": _range(100, 130, 160, "rack")},
            reason="incompatible_unit",
        )

    def test_unsupported_attribution_cannot_produce_a_numerical_result(self) -> None:
        self._assert_incompatible_claim_blocks_result(
            target_id="target.energization",
            mutation={"attribution_basis": "unsupported test-only attribution"},
            reason="unsupported_attribution",
        )

    def test_unrelated_bare_categorical_assertion_cannot_unlock_a_gate(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        corrupted_support = claims_by_upstream["datacenter_atlas"][0][
            "gate_supports"
        ][0]
        gate_id = corrupted_support["gate_id"]
        corrupted_support["assertion"] = (
            f"{TEST_ONLY_NOTICE}: unrelated evidence cannot prove this gate."
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            pulse = build_blackwell_pulse(
                load_synthetic_input_audit(
                    PRODUCTION_CONTRACT / "synthetic-input-audit.json"
                ),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        gate_result = next(
            item
            for item in pulse["evidence_gates"]["categorical"]
            if item["id"] == gate_id
        )
        self.assertFalse(gate_result["passed"])
        self.assertTrue(
            any(
                "unsupported_gate_assertion" in support["reason_codes"]
                for support in gate_result["support_evaluations"]
            )
        )
        self.assertEqual(
            pulse["supply_to_site_estimate"],
            NO_EVIDENCE_BACKED_ESTIMATE,
        )

    def test_invalid_ratio_or_evidence_url_aborts_before_a_numerical_result(self) -> None:
        audit_document = _production_audit_document()
        ratio_target = next(
            item["id"] for item in audit_document["inputs"] if item["unit"] == "ratio"
        )

        def invalid_ratio(claims: dict[str, list[dict[str, Any]]]) -> None:
            claim = next(
                item
                for upstream_claims in claims.values()
                for item in upstream_claims
                if item["target_id"] == ratio_target
            )
            claim["value"] = _range(1.1, 1.2, 1.3, "ratio")

        def invalid_url(claims: dict[str, list[dict[str, Any]]]) -> None:
            claims["datacenter_atlas"][0]["evidence"][0]["source_url"] = "https://"

        for name, mutation, message in (
            ("ratio", invalid_ratio, "ratio values cannot exceed 1"),
            ("evidence URL", invalid_url, "valid HTTPS URL"),
        ):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                claims_by_upstream = _all_valid_claims(audit_document)
                mutation(claims_by_upstream)
                root = Path(temporary)
                lock_path, _cache, releases = _prepare_releases(
                    root,
                    claims_by_upstream,
                )
                with self.assertRaisesRegex(ValueError, message):
                    build_blackwell_pulse(
                        load_synthetic_input_audit(
                            PRODUCTION_CONTRACT / "synthetic-input-audit.json"
                        ),
                        releases,
                        week_ending=WEEK_ENDING,
                        recorded_at=RECORDED_AT,
                        lock_sha256=load_upstream_release_lock(lock_path).sha256,
                    )

    def test_stale_verified_release_is_incompatible_for_the_week(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(
                root,
                claims_by_upstream,
                as_of_dates={"datacenter_atlas": "2026-10-01"},
            )
            pulse = build_blackwell_pulse(
                load_synthetic_input_audit(
                    PRODUCTION_CONTRACT / "synthetic-input-audit.json"
                ),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        self.assertEqual(
            pulse["supply_to_site_estimate"],
            NO_EVIDENCE_BACKED_ESTIMATE,
        )
        datacenter = next(
            item
            for item in pulse["upstreams"]
            if item["upstream_id"] == "datacenter_atlas"
        )
        self.assertEqual(datacenter["status"], "verified_stale")
        self.assertEqual(datacenter["release"]["age_days"], 10)
        self.assertIn(
            "upstream:stale:datacenter_atlas",
            pulse["evidence_gates"]["blockers"],
        )
        self.assertTrue(
            any(
                "stale_upstream_release" in item["reason_codes"]
                for item in pulse["claim_assessments"]
                if item["upstream_id"] == "datacenter_atlas"
                and item["classification"] == "incompatible"
            )
        )

    def _assert_incompatible_claim_blocks_result(
        self,
        *,
        target_id: str,
        mutation: Mapping[str, Any],
        reason: str,
    ) -> None:
        audit_document = _audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        for claims in claims_by_upstream.values():
            for claim in claims:
                if claim["target_id"] == target_id:
                    claim.update(mutation)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            pulse = build_blackwell_pulse(
                _tiny_audit(),
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        assessment = next(
            item for item in pulse["claim_assessments"]
            if item["target_id"] == target_id
        )
        self.assertEqual(assessment["classification"], "incompatible")
        self.assertIn(reason, assessment["reason_codes"])
        self.assertEqual(pulse["supply_to_site_estimate"], NO_EVIDENCE_BACKED_ESTIMATE)

    def test_sibling_cache_rejection_aborts_before_any_release_is_written(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, _releases = _prepare_releases(root, claims_by_upstream)
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            output = root / "pulse-output"
            with self.assertRaisesRegex(
                UpstreamReleaseError,
                "upstream sibling repository",
            ):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    root / "datacenter_atlas" / "cache",
                    audit_path,
                    output,
                )
            self.assertFalse(output.exists())

    def test_intermediate_sibling_symlink_cannot_produce_a_numerical_release(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(
                root,
                claims_by_upstream,
            )
            sibling = root / "datacenter_atlas"
            sibling.mkdir()
            (cache / "objects").rename(sibling / "objects")
            (cache / "objects").symlink_to(
                sibling / "objects",
                target_is_directory=True,
            )
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            output = root / "pulse-output"

            with self.assertRaisesRegex(UpstreamReleaseError, "symbolic links"):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    cache,
                    audit_path,
                    output,
                )

            self.assertFalse(output.exists())

    def test_tampered_cache_aborts_and_does_not_overwrite_existing_output(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(root, claims_by_upstream)
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            output = root / "pulse-output"
            write_blackwell_pulse_release(
                config_path,
                lock_path,
                cache,
                audit_path,
                output,
            )
            before = _snapshot(output)
            entry = load_upstream_release_lock(lock_path).upstreams[0]
            object_path = (
                cache
                / "objects"
                / "sha256"
                / entry.asset.sha256[:2]
                / entry.asset.sha256
            )
            raw = object_path.read_bytes()
            object_path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])

            with self.assertRaisesRegex(UpstreamReleaseError, "SHA-256 mismatch"):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    cache,
                    audit_path,
                    output,
                )
            self.assertEqual(_snapshot(output), before)

    def test_existing_release_fifo_fails_closed_without_blocking(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(
                root,
                claims_by_upstream,
            )
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            payloads = build_blackwell_pulse_release_documents(
                config_path,
                lock_path,
                cache,
                audit_path,
            )
            output = root / "pulse-output"
            output.mkdir()
            for name, raw in payloads.items():
                if name == "pulse.json":
                    os.mkfifo(output / name)
                else:
                    (output / name).write_bytes(raw)

            with self.assertRaisesRegex(ValueError, "non-regular file"):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    cache,
                    audit_path,
                    output,
                )

            self.assertTrue((output / "pulse.json").exists())

    def test_synthetic_inputs_remain_labelled_and_candidates_are_not_applied(self) -> None:
        audit_document = _audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, _cache, releases = _prepare_releases(root, claims_by_upstream)
            audit = _tiny_audit()
            pulse = build_blackwell_pulse(
                audit,
                releases,
                week_ending=WEEK_ENDING,
                recorded_at=RECORDED_AT,
                lock_sha256=load_upstream_release_lock(lock_path).sha256,
            )

        self.assertTrue(pulse["baseline"]["synthetic_input_posture_preserved"])
        self.assertTrue(all(item["current_posture"] == "synthetic" for item in audit.inputs))
        candidates = pulse["questions"]["synthetic_inputs_now_replaceable"]
        self.assertEqual(len(candidates), len(audit.inputs))
        self.assertTrue(
            all(
                item["current_posture"] == "synthetic"
                and item["replacement_status"] == "eligible_candidate_not_applied"
                for item in candidates
            )
        )
        protected = pulse["questions"]["protected_unknowns"]
        self.assertEqual(
            [item["dimension"] for item in protected],
            [
                "allocation",
                "capacity",
                "demand",
                "economics",
                "utilization",
                "yield",
            ],
        )
        self.assertTrue(
            all(
                item["status"] == "unknown_unless_suitable_evidence_is_gated"
                for item in protected
            )
        )

    def test_release_is_byte_identical_and_idempotent(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(root, claims_by_upstream)
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            first = root / "pulse-first"
            second = root / "pulse-second"

            first_result = write_blackwell_pulse_release(
                config_path,
                lock_path,
                cache,
                audit_path,
                first,
            )
            second_result = write_blackwell_pulse_release(
                config_path,
                lock_path,
                cache,
                audit_path,
                second,
            )
            first_snapshot = _snapshot(first)
            self.assertEqual(first_snapshot, _snapshot(second))

            repeat_result = write_blackwell_pulse_release(
                config_path,
                lock_path,
                cache,
                audit_path,
                first,
            )
            self.assertEqual(_snapshot(first), first_snapshot)
            self.assertEqual(
                first_result["supply_to_site_estimate"],
                {**_range(80, 110, 140), "range_basis": "bounded_interval"},
            )
            manifest = json.loads(first_snapshot["manifest.json"])
            self.assertEqual(
                set(manifest["files"]),
                set(first_snapshot) - {"manifest.json"},
            )
            for name, metadata in manifest["files"].items():
                self.assertEqual(metadata["bytes"], len(first_snapshot[name]))
                self.assertEqual(
                    metadata["sha256"],
                    hashlib.sha256(first_snapshot[name]).hexdigest(),
                )
            self.assertEqual(
                {key: value for key, value in first_result.items() if key != "output_dir"},
                {key: value for key, value in second_result.items() if key != "output_dir"},
            )
            self.assertEqual(repeat_result, first_result)

    def test_concurrent_destination_is_never_replaced(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(
                root,
                claims_by_upstream,
            )
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            output = root / "pulse-output"
            rename_exclusive = (
                blackwell_pulse_release._rename_directory_exclusive
            )

            def create_destination_before_publish(
                parent_descriptor: int,
                source_name: str,
                destination_name: str,
            ) -> None:
                os.mkdir(destination_name, mode=0o700, dir_fd=parent_descriptor)
                rename_exclusive(
                    parent_descriptor,
                    source_name,
                    destination_name,
                )

            with patch.object(
                blackwell_pulse_release,
                "_rename_directory_exclusive",
                side_effect=create_destination_before_publish,
            ), self.assertRaisesRegex(ValueError, "file set differs"):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    cache,
                    audit_path,
                    output,
                )

            self.assertTrue(output.is_dir())
            self.assertEqual(list(output.iterdir()), [])
            self.assertFalse(
                any(
                    item.name.startswith(".blackwell-pulse-")
                    for item in root.iterdir()
                )
            )

    def test_post_publish_sync_failure_is_commit_uncertain_and_retryable(self) -> None:
        audit_document = _production_audit_document()
        claims_by_upstream = _all_valid_claims(audit_document)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path, cache, _releases = _prepare_releases(
                root,
                claims_by_upstream,
            )
            audit_path = _write_json(root / "audit.json", audit_document)
            config_path = _write_json(root / "config.json", _config_document())
            output = root / "pulse-output"
            rename_exclusive = (
                blackwell_pulse_release._rename_directory_exclusive
            )
            fsync = blackwell_pulse_release.os.fsync
            published_parent: int | None = None

            def publish_then_mark(
                parent_descriptor: int,
                source_name: str,
                destination_name: str,
            ) -> None:
                nonlocal published_parent
                rename_exclusive(
                    parent_descriptor,
                    source_name,
                    destination_name,
                )
                published_parent = parent_descriptor

            def fail_first_published_parent_sync(descriptor: int) -> None:
                nonlocal published_parent
                if descriptor == published_parent:
                    published_parent = None
                    raise OSError(5, "TEST-ONLY simulated durability failure")
                fsync(descriptor)

            with patch.object(
                blackwell_pulse_release,
                "_rename_directory_exclusive",
                side_effect=publish_then_mark,
            ), patch.object(
                blackwell_pulse_release.os,
                "fsync",
                side_effect=fail_first_published_parent_sync,
            ), self.assertRaisesRegex(
                OSError,
                "published but parent durability sync failed",
            ):
                write_blackwell_pulse_release(
                    config_path,
                    lock_path,
                    cache,
                    audit_path,
                    output,
                )

            self.assertTrue((output / "manifest.json").is_file())
            retried = write_blackwell_pulse_release(
                config_path,
                lock_path,
                cache,
                audit_path,
                output,
            )
            self.assertEqual(retried["output_dir"], str(output.resolve()))

    def test_incomplete_synthetic_audit_coverage_is_rejected(self) -> None:
        audit_document = _production_audit_document()
        audit_document["inputs"].pop()
        with self.assertRaisesRegex(ValueError, "cardinality does not match"):
            synthetic_input_audit_from_dict(audit_document)

    def test_frozen_audit_semantics_and_evidence_postures_cannot_be_redefined(self) -> None:
        mutations = {
            "current range": lambda document: document["inputs"][0][
                "current_range"
            ].__setitem__("low", 349),
            "attribution": lambda document: document["inputs"][0].__setitem__(
                "attribution_basis",
                "TEST-ONLY -- NOT PRODUCTION EVIDENCE: rewritten scope",
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                audit_document = _production_audit_document()
                mutate(audit_document)
                with self.assertRaisesRegex(ValueError, "semantics do not match"):
                    synthetic_input_audit_from_dict(audit_document)

        audit_document = _production_audit_document()
        audit_document["inputs"][0]["evidence_gate"]["accepted_postures"] = [
            "modeled"
        ]
        with self.assertRaisesRegex(ValueError, "accepted_postures has unsupported"):
            synthetic_input_audit_from_dict(audit_document)

    def test_production_zero_entry_lock_emits_the_exact_fallback(self) -> None:
        lock_path = PRODUCTION_CONTRACT / "upstream-releases.lock.json"
        audit_path = PRODUCTION_CONTRACT / "synthetic-input-audit.json"
        lock = load_upstream_release_lock(lock_path)
        self.assertEqual(lock.upstreams, ())

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = _write_json(root / "config.json", _config_document())
            payloads = build_blackwell_pulse_release_documents(
                config_path,
                lock_path,
                root / "empty-cache",
                audit_path,
            )
        pulse = json.loads(payloads["pulse.json"])
        manifest = json.loads(payloads["manifest.json"])
        self.assertEqual(pulse["supply_to_site_estimate"], NO_EVIDENCE_BACKED_ESTIMATE)
        self.assertEqual(manifest["supply_to_site_estimate"], NO_EVIDENCE_BACKED_ESTIMATE)
        self.assertFalse(pulse["evidence_gates"]["supply_to_site_passed"])

    def test_cli_round_trip_with_production_zero_entry_lock_is_offline_and_fail_closed(
        self,
    ) -> None:
        lock_path = PRODUCTION_CONTRACT / "upstream-releases.lock.json"
        audit_path = PRODUCTION_CONTRACT / "synthetic-input-audit.json"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache"
            output = root / "pulse-output"
            config_path = _write_json(root / "config.json", _config_document())

            fetch_stdout = io.StringIO()
            with redirect_stdout(fetch_stdout):
                fetch_status = main(
                    [
                        "fetch-upstream-releases",
                        "--lockfile",
                        str(lock_path),
                        "--cache-dir",
                        str(cache),
                    ]
                )
            fetch_result = json.loads(fetch_stdout.getvalue())
            self.assertEqual(fetch_status, 0)
            self.assertTrue(fetch_result["valid"])
            self.assertEqual(fetch_result["verified_releases"], [])

            build_stdout = io.StringIO()
            with redirect_stdout(build_stdout):
                build_status = main(
                    [
                        "build-blackwell-pulse",
                        "--config",
                        str(config_path),
                        "--lockfile",
                        str(lock_path),
                        "--cache-dir",
                        str(cache),
                        "--synthetic-audit",
                        str(audit_path),
                        "--output-dir",
                        str(output),
                    ]
                )
            build_result = json.loads(build_stdout.getvalue())

            self.assertEqual(build_status, 0)
            self.assertEqual(build_result["output_dir"], str(output.resolve()))
            pulse = json.loads((output / "pulse.json").read_text(encoding="utf-8"))
            self.assertEqual(
                pulse["supply_to_site_estimate"],
                NO_EVIDENCE_BACKED_ESTIMATE,
            )
            self.assertFalse(pulse["evidence_gates"]["supply_to_site_passed"])


if __name__ == "__main__":
    unittest.main()
