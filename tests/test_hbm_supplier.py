from __future__ import annotations

import copy
import csv
import hashlib
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from supply_intelligence.cli import main
from supply_intelligence.hbm_supplier_engine import (
    HBM_SUPPLIER_RESULT_FORMAT,
    reconcile_hbm_suppliers,
)
from supply_intelligence.hbm_supplier_loader import (
    HBM_SUPPLIER_SCENARIO_FORMAT,
    hbm_supplier_scenario_from_dict,
)
from supply_intelligence.hbm_supplier_release import (
    HBM_SUPPLIER_DRAW_RELEASE_FORMAT,
    HBM_SUPPLIER_RELEASE_FORMAT,
    write_hbm_supplier_release,
)


def _estimate(
    value: float,
    unit: str,
    *,
    posture: str = "synthetic",
    confidence: float = 0.4,
    evidence_id: str = "synthetic:hbm-supplier",
) -> dict[str, object]:
    return {
        "base": value,
        "confidence": confidence,
        "confirming_evidence": "A supplier production record supports this input.",
        "correlation_group": None,
        "evidence_ids": [evidence_id],
        "falsifying_evidence": "A verified production record places this input elsewhere.",
        "high": value,
        "last_updated": "2026-07-19",
        "low": value,
        "methodology": "Deterministic test input.",
        "posture": posture,
        "unit": unit,
    }


def _wafer(supplier_id: str, starts: float) -> dict[str, object]:
    return {
        "die_height_mm": _estimate(10, "mm"),
        "die_width_mm": _estimate(10, "mm"),
        "edge_exclusion_mm": _estimate(0, "mm"),
        "id": f"{supplier_id}-wafer",
        "name": f"{supplier_id} HBM wafer",
        "notes": "Deterministic geometry.",
        "scribe_width_mm": _estimate(0, "mm"),
        "wafer_diameter_mm": _estimate(100, "mm"),
        "wafer_starts": _estimate(starts, "wafer"),
    }


def _supplier(
    supplier_id: str,
    starts: float,
    allocation: float,
) -> dict[str, object]:
    return {
        "capacity_scope": f"Only {supplier_id}'s compatible 2026-Q3 test flow.",
        "capacity_scope_id": f"scope-{supplier_id}-2026q3",
        "customer_allocation_share": _estimate(allocation, "ratio"),
        "geography": "global",
        "id": supplier_id,
        "known_good_die_yield": _estimate(1, "ratio"),
        "name": supplier_id.title(),
        "notes": "Deterministic supplier test flow.",
        "platform_qualified_share": _estimate(1, "ratio"),
        "process_node": "test-node",
        "product": "HBM3E test stack",
        "stack_assembly_yield": _estimate(1, "ratio"),
        "stack_final_test_yield": _estimate(1, "ratio"),
        "wafer": _wafer(supplier_id, starts),
        "wafer_start_basis": "supplier_hbm3e_compatible",
    }


def _document(*, demand: float = 12) -> dict[str, object]:
    return {
        "evidence": [
            {
                "content_hash": None,
                "excerpt": "Synthetic supplier-flow fixture.",
                "id": "synthetic:hbm-supplier",
                "kind": "synthetic",
                "license": None,
                "published_at": "2026-07-18",
                "publisher": "Test suite",
                "retrieved_at": "2026-07-19T10:00:00Z",
                "source_family": "test-suite",
                "source_url": "urn:synthetic:hbm-supplier",
                "title": "Synthetic HBM supplier fixture",
            }
        ],
        "format": HBM_SUPPLIER_SCENARIO_FORMAT,
        "platform": {
            "accelerator_package_demand": _estimate(demand, "package"),
            "customer": "Test Customer",
            "hbm_generation": "HBM3E",
            "id": "test-platform",
            "memory_dies_per_stack": _estimate(8, "die/stack"),
            "name": "Test accelerator",
            "notes": "Test topology.",
            "stack_capacity_gb": _estimate(24, "GB/stack"),
            "stacks_per_accelerator": _estimate(8, "stack/accelerator"),
        },
        "scenario": {
            "as_of_date": "2026-07-19",
            "id": "hbm-supplier-test",
            "name": "Supplier-resolved HBM test",
            "notes": "Test supplier aggregation and allocation.",
            "quarter": "2026-Q3",
            "recorded_at": "2026-07-19T12:00:00Z",
            "samples": 100,
            "seed": 17,
            "synthetic": True,
        },
        "suppliers": [
            _supplier("supplier-a", 10, 1),
            _supplier("supplier-b", 10, 0.5),
        ],
    }


class HbmSupplierTests(unittest.TestCase):
    def test_draw_release_preserves_each_supplier_and_aggregate_capacity(self) -> None:
        scenario = hbm_supplier_scenario_from_dict(_document())
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "draw-release"
            metadata = write_hbm_supplier_release(
                scenario,
                destination,
                source_document=json.dumps(_document(), indent=2, sort_keys=True) + "\n",
                include_capacity_draws=True,
            )
            self.assertEqual(HBM_SUPPLIER_DRAW_RELEASE_FORMAT, metadata["format"])
            self.assertEqual(scenario.samples, metadata["capacity_draw_count"])
            with (destination / "capacity_draws.csv").open(
                encoding="utf-8",
                newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(scenario.samples, len(rows))
            for row in rows:
                supplier_total = sum(
                    float(row[f"supplier.{supplier.id}.customer_allocated_stacks"])
                    for supplier in scenario.suppliers
                )
                self.assertAlmostEqual(
                    supplier_total,
                    float(row["customer_allocated_stacks"]),
                )
                self.assertAlmostEqual(
                    float(row["customer_allocated_stacks"])
                    / float(row["stacks_per_accelerator"]),
                    float(row["hbm_package_equivalents"]),
                )

    def test_supplier_outputs_conserve_capacity_and_allocation(self) -> None:
        scenario = hbm_supplier_scenario_from_dict(_document())
        result = reconcile_hbm_suppliers(scenario)
        self.assertEqual(HBM_SUPPLIER_RESULT_FORMAT, result["format"])
        allocated = sum(
            item["outputs"]["customer_allocated_stacks"]["p50"]
            for item in result["suppliers"]
        )
        self.assertAlmostEqual(
            allocated,
            result["totals"]["customer_allocated_stacks"]["p50"],
        )
        shares = sum(
            item["outputs"]["customer_allocated_stack_share"]["p50"]
            for item in result["suppliers"]
        )
        self.assertAlmostEqual(1, shares)
        supplier_a, supplier_b = result["suppliers"]
        self.assertAlmostEqual(
            2,
            supplier_a["outputs"]["customer_allocated_stacks"]["p50"]
            / supplier_b["outputs"]["customer_allocated_stacks"]["p50"],
        )
        self.assertEqual(0, result["supply_sufficiency"]["probability_hbm_limited"])
        self.assertAlmostEqual(
            12,
            result["totals"]["packages_supported"]["p50"],
        )

    def test_demand_shortfall_and_supplier_criticality_are_explicit(self) -> None:
        scenario = hbm_supplier_scenario_from_dict(_document(demand=20))
        result = reconcile_hbm_suppliers(scenario)
        self.assertEqual(1, result["supply_sufficiency"]["probability_hbm_limited"])
        self.assertGreater(
            result["totals"]["unfilled_package_demand"]["p50"],
            0,
        )
        self.assertTrue(
            all(item["criticality_probability"] == 1 for item in result["suppliers"])
        )

    def test_duplicate_scope_and_double_allocation_are_rejected(self) -> None:
        duplicate = _document()
        duplicate["suppliers"][1]["capacity_scope_id"] = duplicate["suppliers"][0][
            "capacity_scope_id"
        ]
        with self.assertRaisesRegex(ValueError, "double count supply"):
            hbm_supplier_scenario_from_dict(duplicate)

        allocated = _document()
        allocated_supplier = allocated["suppliers"][0]
        allocated_supplier["wafer_start_basis"] = "platform_allocated"
        allocated_supplier["customer_allocation_share"] = _estimate(0.5, "ratio")
        with self.assertRaisesRegex(ValueError, "must be fixed at one"):
            hbm_supplier_scenario_from_dict(allocated)

    def test_evidence_and_synthetic_posture_guards(self) -> None:
        evidence_late = _document()
        evidence_late["evidence"][0]["retrieved_at"] = "2026-07-19T13:00:00Z"
        with self.assertRaisesRegex(ValueError, "retrieved after recorded_at"):
            hbm_supplier_scenario_from_dict(evidence_late)

        falsely_evidence_backed = _document()
        falsely_evidence_backed["scenario"]["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "cannot contain synthetic"):
            hbm_supplier_scenario_from_dict(falsely_evidence_backed)

    def test_derived_input_leaves_the_synthetic_research_queue(self) -> None:
        document = _document()
        diameter = document["suppliers"][0]["wafer"]["wafer_diameter_mm"]
        diameter["posture"] = "derived"
        diameter["confidence"] = 0.95
        scenario = hbm_supplier_scenario_from_dict(document)
        result = reconcile_hbm_suppliers(scenario)
        supplier_a_gaps = {
            item["parameter"]
            for item in result["research_queue"]
            if item["owner_id"] == "supplier-a"
        }
        self.assertNotIn("wafer.wafer_diameter_mm", supplier_a_gaps)

    def test_non_synthetic_evidence_requires_exact_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text('{"reported":"source fixture"}\n', encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            document = _document()
            evidence = document["evidence"][0]
            evidence["kind"] = "company_disclosure"
            evidence["content_hash"] = digest
            evidence["source_url"] = "https://example.com/source"
            document["source_files"] = [
                {
                    "evidence_id": evidence["id"],
                    "path": source.name,
                    "sha256": digest,
                }
            ]
            scenario = hbm_supplier_scenario_from_dict(
                document,
                source_root=root,
            )
            self.assertEqual(1, len(scenario.source_documents))

            drifted = copy.deepcopy(document)
            drifted["source_files"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                hbm_supplier_scenario_from_dict(drifted, source_root=root)

            missing = copy.deepcopy(document)
            missing["source_files"] = []
            with self.assertRaisesRegex(ValueError, "pinned source document"):
                hbm_supplier_scenario_from_dict(missing, source_root=root)

            escaped = copy.deepcopy(document)
            escaped["source_files"][0]["path"] = "../source.json"
            with self.assertRaisesRegex(ValueError, "below source_root"):
                hbm_supplier_scenario_from_dict(escaped, source_root=root)

    def test_release_and_cli_are_replay_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = _document()
            raw = json.dumps(document, indent=2, sort_keys=True) + "\n"
            scenario_path = root / "scenario.json"
            scenario_path.write_text(raw, encoding="utf-8")
            scenario = hbm_supplier_scenario_from_dict(document)
            destination = root / "release"
            metadata = write_hbm_supplier_release(
                scenario,
                destination,
                source_document=raw,
            )
            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(HBM_SUPPLIER_RELEASE_FORMAT, manifest["format"])
            self.assertEqual(2, metadata["supplier_count"])
            for name, descriptor in manifest["files"].items():
                payload = (destination / name).read_bytes()
                self.assertEqual(descriptor["bytes"], len(payload))
                self.assertEqual(
                    descriptor["sha256"],
                    hashlib.sha256(payload).hexdigest(),
                )
            replay = write_hbm_supplier_release(
                scenario,
                destination,
                source_document=raw,
            )
            self.assertEqual(metadata["scenario_id"], replay["scenario_id"])
            (destination / "README.md").write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or incomplete release"):
                write_hbm_supplier_release(
                    scenario,
                    destination,
                    source_document=raw,
                )

            output = StringIO()
            with redirect_stdout(output):
                status = main(
                    [
                        "validate-hbm-suppliers",
                        "--scenario",
                        str(scenario_path),
                        "--source-root",
                        str(root),
                    ]
                )
            self.assertEqual(0, status)
            validation = json.loads(output.getvalue())
            self.assertEqual(2, validation["suppliers"])
            self.assertEqual(2, len(validation["capacity_scope_ids"]))


if __name__ == "__main__":
    unittest.main()
