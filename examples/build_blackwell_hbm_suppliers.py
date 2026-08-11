"""Print the checked supplier-resolved Blackwell HBM scenario as JSON."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "examples" / "hbm-suppliers" / "sources"
SYNTHETIC_EVIDENCE = "synthetic:hbm-supplier-portfolio"


def source_hash(name: str) -> str:
    return hashlib.sha256((SOURCE_DIR / name).read_bytes()).hexdigest()


def estimate(
    low: float,
    base: float,
    high: float,
    unit: str,
    *,
    posture: str,
    methodology: str,
    confidence: float,
    evidence_ids: list[str],
    confirming_evidence: str,
    falsifying_evidence: str,
    correlation_group: str | None = None,
) -> dict[str, object]:
    return {
        "base": base,
        "confidence": confidence,
        "confirming_evidence": confirming_evidence,
        "correlation_group": correlation_group,
        "evidence_ids": evidence_ids,
        "falsifying_evidence": falsifying_evidence,
        "high": high,
        "last_updated": "2026-07-19",
        "low": low,
        "methodology": methodology,
        "posture": posture,
        "unit": unit,
    }


def synthetic(
    low: float,
    base: float,
    high: float,
    unit: str,
    methodology: str,
    *,
    correlation_group: str | None = None,
) -> dict[str, object]:
    return estimate(
        low,
        base,
        high,
        unit,
        posture="synthetic",
        methodology=methodology,
        confidence=0.3,
        evidence_ids=[SYNTHETIC_EVIDENCE],
        confirming_evidence=(
            "Supplier wafer, yield, qualification, or allocation records support the range."
        ),
        falsifying_evidence=(
            "Verified supplier or customer records place the input outside the range."
        ),
        correlation_group=correlation_group,
    )


def wafer(
    supplier_id: str,
    starts: tuple[float, float, float],
    *,
    diameter: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "die_height_mm": synthetic(
            10.5,
            11,
            11.5,
            "mm",
            f"Illustrative {supplier_id} HBM3E memory-die height.",
            correlation_group=f"{supplier_id}-geometry",
        ),
        "die_width_mm": synthetic(
            9.5,
            10,
            10.5,
            "mm",
            f"Illustrative {supplier_id} HBM3E memory-die width.",
            correlation_group=f"{supplier_id}-geometry",
        ),
        "edge_exclusion_mm": synthetic(
            2,
            2.5,
            3,
            "mm",
            f"Illustrative {supplier_id} HBM wafer edge exclusion.",
        ),
        "id": f"{supplier_id}-hbm3e-wafer",
        "name": f"{supplier_id} HBM3E-compatible wafer flow",
        "notes": "Wafer starts and die geometry are not supplier-reported in this checked scenario.",
        "scribe_width_mm": synthetic(
            0.05,
            0.08,
            0.11,
            "mm",
            f"Illustrative {supplier_id} HBM scribe width.",
        ),
        "wafer_diameter_mm": diameter
        or synthetic(
            300,
            300,
            300,
            "mm",
            f"Unverified reference wafer diameter for {supplier_id}; do not infer it from Micron evidence.",
        ),
        "wafer_starts": synthetic(
            *starts,
            "wafer",
            f"Illustrative quarterly {supplier_id} HBM3E-compatible wafer starts before platform qualification and customer allocation.",
            correlation_group=f"{supplier_id}-front-end",
        ),
    }


def supplier(
    supplier_id: str,
    name: str,
    starts: tuple[float, float, float],
    *,
    process_node: str,
    diameter: dict[str, object] | None,
    known_good: tuple[float, float, float],
    assembly: tuple[float, float, float],
    final_test: tuple[float, float, float],
    qualified: tuple[float, float, float],
    allocation: tuple[float, float, float],
) -> dict[str, object]:
    return {
        "capacity_scope": (
            f"Only {name}'s modeled 2026-Q3 HBM3E-compatible memory-wafer flow, "
            "before Blackwell qualification and NVIDIA allocation; no other supplier scope is included."
        ),
        "capacity_scope_id": f"{supplier_id}-global-hbm3e-compatible-2026q3",
        "customer_allocation_share": synthetic(
            *allocation,
            "ratio",
            f"Illustrative share of {name} Blackwell-qualified stacks allocated to NVIDIA Blackwell in 2026-Q3.",
            correlation_group=f"{supplier_id}-allocation",
        ),
        "geography": "global supplier network",
        "id": supplier_id,
        "known_good_die_yield": synthetic(
            *known_good,
            "ratio",
            f"Illustrative {name} known-good HBM memory-die yield after repair and test.",
            correlation_group=f"{supplier_id}-yield",
        ),
        "name": name,
        "notes": (
            "Supplier participation, qualification, wafer starts, yields, and NVIDIA allocation are synthetic. "
            "The row exercises non-overlapping scope and does not assert a commercial relationship."
        ),
        "platform_qualified_share": synthetic(
            *qualified,
            "ratio",
            f"Illustrative share of {name} good 24GB 8-high-compatible stacks qualified for Blackwell.",
            correlation_group=f"{supplier_id}-qualification",
        ),
        "process_node": process_node,
        "product": "Illustrative 24GB 8-high-compatible HBM3E",
        "stack_assembly_yield": synthetic(
            *assembly,
            "ratio",
            f"Illustrative {name} HBM3E stack-assembly yield.",
            correlation_group=f"{supplier_id}-stack-yield",
        ),
        "stack_final_test_yield": synthetic(
            *final_test,
            "ratio",
            f"Illustrative {name} HBM3E final stack-test yield.",
            correlation_group=f"{supplier_id}-stack-yield",
        ),
        "wafer": wafer(supplier_id, starts, diameter=diameter),
        "wafer_start_basis": "supplier_hbm3e_compatible",
    }


def build() -> dict[str, object]:
    micron_diameter = estimate(
        300,
        300,
        300,
        "mm",
        posture="derived",
        methodology=(
            "Micron's 2025 Form 10-K identifies 8-high 24GB HBM3E on 1-beta and states that "
            "Micron products are manufactured on 300mm wafers. This supports Micron's nominal "
            "HBM3E wafer format only; it does not support another supplier or any capacity input."
        ),
        confidence=0.98,
        evidence_ids=["micron:2025-10k-hbm-wafer"],
        confirming_evidence=(
            "A Micron process or product document explicitly identifies the same HBM3E flow as 300mm."
        ),
        falsifying_evidence=(
            "Micron identifies a non-300mm wafer format for the modeled 1-beta HBM3E flow."
        ),
    )
    return {
        "evidence": [
            {
                "content_hash": source_hash(
                    "nvidia-blackwell-hbm-capacity-observation.json"
                ),
                "excerpt": "NVIDIA reports 192GB maximum HBM3E capacity for a Blackwell GPU.",
                "id": "nvidia:blackwell-hbm-capacity",
                "kind": "company_technical_document",
                "license": "NVIDIA website terms",
                "published_at": "2025-08-22",
                "publisher": "NVIDIA",
                "retrieved_at": "2026-07-19T23:10:00Z",
                "source_family": "nvidia-blackwell-documentation",
                "source_url": "https://developer.nvidia.com/blog/?p=104887",
                "title": "NVIDIA Blackwell and Blackwell Ultra architecture comparison",
            },
            {
                "content_hash": source_hash(
                    "nvidia-blackwell-hbm-height-observation.json"
                ),
                "excerpt": "NVIDIA distinguishes 8-Hi HBM3E in Blackwell from 12-Hi HBM3E in Blackwell Ultra.",
                "id": "nvidia:blackwell-hbm-height",
                "kind": "company_technical_document",
                "license": "NVIDIA website terms",
                "published_at": "2025-11-12",
                "publisher": "NVIDIA",
                "retrieved_at": "2026-07-19T23:10:00Z",
                "source_family": "nvidia-blackwell-documentation",
                "source_url": "https://developer.nvidia.com/blog/nvidia-blackwell-architecture-sweeps-mlperf-training-v5-1-benchmarks/",
                "title": "NVIDIA Blackwell MLPerf Training v5.1 architecture notes",
            },
            {
                "content_hash": source_hash("micron-hbm3e-reference-observation.json"),
                "excerpt": "Micron reports a 24GB 8-high HBM3E placement built with 1-beta technology.",
                "id": "micron:hbm3e-reference",
                "kind": "company_technical_document",
                "license": "Micron website terms",
                "published_at": None,
                "publisher": "Micron Technology",
                "retrieved_at": "2026-07-19T23:10:00Z",
                "source_family": "micron-hbm3e-documentation",
                "source_url": "https://www.micron.com/products/memory/hbm/hbm3e",
                "title": "Micron HBM3E product specifications",
            },
            {
                "content_hash": source_hash(
                    "micron-2025-10k-hbm-wafer-observation.json"
                ),
                "excerpt": "Micron reports 8-high 24GB HBM3E on 1-beta and states that its products use 300mm wafers.",
                "id": "micron:2025-10k-hbm-wafer",
                "kind": "company_disclosure",
                "license": "Micron investor-relations website terms",
                "published_at": "2025-10-03",
                "publisher": "Micron Technology",
                "retrieved_at": "2026-07-19T23:10:00Z",
                "source_family": "micron-sec-filings",
                "source_url": "https://investors.micron.com/static-files/8791eb80-8263-4c6f-aa74-fdd03fbbb027",
                "title": "Micron 2025 Form 10-K",
            },
            {
                "content_hash": None,
                "excerpt": "Supplier wafer starts, die geometry, yields, qualification, allocation, and platform demand are illustrative.",
                "id": SYNTHETIC_EVIDENCE,
                "kind": "synthetic",
                "license": "CC0-1.0",
                "published_at": "2026-07-19",
                "publisher": "AI Supply Intelligence demo",
                "retrieved_at": "2026-07-19T23:10:00Z",
                "source_family": "synthetic-hbm-supplier-demo",
                "source_url": "urn:synthetic:blackwell-hbm-supplier-portfolio",
                "title": "Illustrative supplier HBM capacity and allocation assumptions",
            },
        ],
        "format": "ai-supply-hbm-supplier-portfolio.v1",
        "platform": {
            "accelerator_package_demand": synthetic(
                300000,
                400000,
                500000,
                "package",
                "Illustrative quarterly demand for Blackwell accelerator packages served by this HBM pool.",
                correlation_group="blackwell-package-demand",
            ),
            "customer": "NVIDIA Blackwell",
            "hbm_generation": "HBM3E",
            "id": "nvidia-blackwell-24gb-8high-reference",
            "memory_dies_per_stack": estimate(
                8,
                8,
                8,
                "die/stack",
                posture="reported",
                methodology=(
                    "NVIDIA describes Blackwell as using 8-Hi HBM3E, while Micron reports an "
                    "8-high 24GB HBM3E reference product. This fixes stack height, not supplier mix."
                ),
                confidence=0.98,
                evidence_ids=[
                    "nvidia:blackwell-hbm-height",
                    "micron:hbm3e-reference",
                ],
                confirming_evidence="A Blackwell package BOM or cross-section shows eight memory dies per stack.",
                falsifying_evidence="A Blackwell product BOM identifies a different physical stack height.",
            ),
            "name": "NVIDIA Blackwell 192GB HBM3E reference configuration",
            "notes": (
                "The platform topology is a reference configuration. NVIDIA's current GB200 NVL72 page "
                "also reports 372GB across two GPUs, so addressable capacity and SKU revisions require follow-up."
            ),
            "stack_capacity_gb": estimate(
                24,
                24,
                24,
                "GB/stack",
                posture="reported",
                methodology=(
                    "Use Micron's reported 24GB 8-high HBM3E placement as the compatible reference "
                    "stack. This does not assert Micron supply to Blackwell."
                ),
                confidence=0.98,
                evidence_ids=["micron:hbm3e-reference"],
                confirming_evidence="A Blackwell BOM identifies 24GB physical HBM3E placements.",
                falsifying_evidence="The modeled Blackwell configuration uses a different capacity per placement.",
            ),
            "stacks_per_accelerator": estimate(
                8,
                8,
                8,
                "stack/accelerator",
                posture="derived",
                methodology=(
                    "Divide NVIDIA's reported 192GB maximum Blackwell HBM3E capacity by the 24GB "
                    "reference placement. This derives eight placements without identifying suppliers."
                ),
                confidence=0.85,
                evidence_ids=[
                    "nvidia:blackwell-hbm-capacity",
                    "micron:hbm3e-reference",
                ],
                confirming_evidence="A Blackwell package BOM or cross-section shows eight HBM placements.",
                falsifying_evidence="A Blackwell product BOM identifies a different placement count or stack capacity.",
            ),
        },
        "scenario": {
            "as_of_date": "2026-07-19",
            "id": "blackwell-hbm-supplier-portfolio-illustrative-2026q3",
            "name": "Blackwell supplier-resolved HBM3E portfolio",
            "notes": (
                "This portfolio splits one illustrative HBM pool across SK hynix, Micron, and Samsung. "
                "Only Micron's nominal 300mm wafer format and shared reference topology use official "
                "evidence. All supplier capacity, yield, qualification, allocation, and demand ranges remain synthetic."
            ),
            "quarter": "2026-Q3",
            "recorded_at": "2026-07-19T23:20:00Z",
            "samples": 20000,
            "seed": 20260719,
            "synthetic": True,
        },
        "source_files": [
            {
                "evidence_id": "nvidia:blackwell-hbm-capacity",
                "path": "examples/hbm-suppliers/sources/nvidia-blackwell-hbm-capacity-observation.json",
                "sha256": source_hash("nvidia-blackwell-hbm-capacity-observation.json"),
            },
            {
                "evidence_id": "nvidia:blackwell-hbm-height",
                "path": "examples/hbm-suppliers/sources/nvidia-blackwell-hbm-height-observation.json",
                "sha256": source_hash("nvidia-blackwell-hbm-height-observation.json"),
            },
            {
                "evidence_id": "micron:hbm3e-reference",
                "path": "examples/hbm-suppliers/sources/micron-hbm3e-reference-observation.json",
                "sha256": source_hash("micron-hbm3e-reference-observation.json"),
            },
            {
                "evidence_id": "micron:2025-10k-hbm-wafer",
                "path": "examples/hbm-suppliers/sources/micron-2025-10k-hbm-wafer-observation.json",
                "sha256": source_hash("micron-2025-10k-hbm-wafer-observation.json"),
            },
        ],
        "suppliers": [
            supplier(
                "sk-hynix",
                "SK hynix",
                (40000, 55000, 70000),
                process_node="supplier HBM3E process not source-verified",
                diameter=None,
                known_good=(0.82, 0.9, 0.95),
                assembly=(0.88, 0.94, 0.98),
                final_test=(0.94, 0.975, 0.995),
                qualified=(0.75, 0.85, 0.92),
                allocation=(0.35, 0.45, 0.55),
            ),
            supplier(
                "micron",
                "Micron Technology",
                (25000, 35000, 45000),
                process_node="1-beta",
                diameter=micron_diameter,
                known_good=(0.84, 0.91, 0.96),
                assembly=(0.9, 0.95, 0.985),
                final_test=(0.95, 0.98, 0.997),
                qualified=(0.7, 0.8, 0.9),
                allocation=(0.45, 0.55, 0.65),
            ),
            supplier(
                "samsung",
                "Samsung Electronics",
                (20000, 30000, 40000),
                process_node="supplier HBM3E process not source-verified",
                diameter=None,
                known_good=(0.78, 0.87, 0.94),
                assembly=(0.84, 0.91, 0.97),
                final_test=(0.92, 0.965, 0.992),
                qualified=(0.4, 0.6, 0.8),
                allocation=(0.15, 0.25, 0.4),
            ),
        ],
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, sort_keys=True))
