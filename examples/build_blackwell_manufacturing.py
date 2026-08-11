"""Build the checked Blackwell wafer-to-package conversion demonstration."""

from __future__ import annotations

import json
from pathlib import Path

from build_gb200_illustrative import AS_OF, estimate, reported, synthetic


RECORDED_AT = "2026-07-18T03:22:00Z"
OUTPUT = Path(__file__).with_name(
    "blackwell-wafer-hbm-illustrative-2026q3.json"
)


def synthetic_input(
    low: float,
    base: float,
    high: float,
    unit: str,
    method: str,
    group: str | None = None,
) -> dict[str, object]:
    return synthetic(
        low,
        base,
        high,
        unit,
        method,
        "synthetic:manufacturing-process",
        "Supplier wafer starts, process-control, yield, binning, or assembly records support the range.",
        "Verified production or process data place the input outside the range.",
        group,
    )


def derived_topology(
    value: float,
    unit: str,
    method: str,
    evidence_ids: list[str],
    falsifying: str,
    confidence: float,
) -> dict[str, object]:
    return estimate(
        value,
        value,
        value,
        unit,
        evidence_ids,
        posture="derived",
        methodology=method,
        confidence=confidence,
        confirming="A current product BOM reports the same physical topology.",
        falsifying=falsifying,
    )


def main() -> None:
    evidence = [
        {
            "id": "nvidia:blackwell-launch",
            "kind": "company_technical_document",
            "title": "NVIDIA Blackwell Platform Arrives to Power a New Era of Computing",
            "source_url": "https://nvidianews.nvidia.com/news/nvidia-blackwell-platform-arrives-to-power-a-new-era-of-computing",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": "2024-03-18",
            "source_family": "nvidia-blackwell-documentation",
            "license": "NVIDIA website terms",
            "excerpt": "NVIDIA reports a custom TSMC 4NP process and two reticle-limit GPU dies per Blackwell GPU.",
            "content_hash": None,
        },
        {
            "id": "nvidia:gb200-memory",
            "kind": "company_technical_document",
            "title": "NVIDIA Transformer Engine CPU offloading documentation",
            "source_url": "https://docs.nvidia.com/deeplearning/transformer-engine-releases/release-2.15/user-guide/features/other_optimizations/cpu_offloading/cpu_offloading.html",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-gb200-documentation",
            "license": "NVIDIA documentation terms",
            "excerpt": "NVIDIA documents 192 GB HBM3E per GB200 Blackwell GPU.",
            "content_hash": None,
        },
        {
            "id": "micron:hbm3e-reference",
            "kind": "company_technical_document",
            "title": "Micron HBM3E product specifications",
            "source_url": "https://www.micron.com/products/memory/hbm/hbm3e",
            "publisher": "Micron Technology",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "micron-hbm3e-documentation",
            "license": "Micron website terms",
            "excerpt": "Micron reports 24 GB capacity for an 8-high HBM3E placement and 36 GB for a 12-high placement.",
            "content_hash": None,
        },
        {
            "id": "nvidia:gb200-product",
            "kind": "company_technical_document",
            "title": "NVIDIA GB200 NVL72 product specifications",
            "source_url": "https://www.nvidia.com/en-us/data-center/gb200-nvl72/",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-gb200-documentation",
            "license": "NVIDIA website terms",
            "excerpt": "NVIDIA reports 72 Blackwell GPUs in one GB200 NVL72 rack-scale system.",
            "content_hash": None,
        },
        {
            "id": "tsmc:2026q2-management-report",
            "kind": "company_disclosure",
            "title": "TSMC second-quarter 2026 management report",
            "source_url": "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-07/6f49632674bd2d0fd48cb65aaf89ec6ab510b559/2Q26%20ManagementReport.pdf",
            "publisher": "Taiwan Semiconductor Manufacturing Company",
            "retrieved_at": RECORDED_AT,
            "published_at": "2026-07-16",
            "source_family": "tsmc-quarterly-results",
            "license": "TSMC website terms",
            "excerpt": "TSMC reports 4.336 million 12-inch-equivalent wafer shipments across the company in 2Q26.",
            "content_hash": None,
        },
        {
            "id": "synthetic:manufacturing-process",
            "kind": "synthetic",
            "title": "Illustrative wafer, yield, binning, and assembly assumptions",
            "source_url": "urn:synthetic:blackwell-manufacturing-process",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-manufacturing-demo",
            "license": "CC0-1.0",
            "excerpt": "Wafer starts, die geometry, defect density, yield, bin share, supplier allocation, and assembly throughput are synthetic.",
            "content_hash": None,
        },
    ]

    logic_wafer = {
        "id": "blackwell-logic-wafer",
        "name": "Illustrative Blackwell logic wafer flow",
        "wafer_starts": synthetic_input(
            25000,
            35000,
            45000,
            "wafer",
            "Illustrative quarterly Blackwell logic wafer starts. NVIDIA and TSMC do not disclose this range in the cited documents.",
            "logic-front-end",
        ),
        "wafer_diameter_mm": synthetic_input(
            300,
            300,
            300,
            "mm",
            "Reference 300 mm logic wafer diameter; the cited product documents do not state wafer diameter.",
        ),
        "edge_exclusion_mm": synthetic_input(
            2,
            2.5,
            3,
            "mm",
            "Illustrative unusable wafer edge used by the gross-die approximation.",
        ),
        "die_width_mm": synthetic_input(
            25.5,
            26,
            26.5,
            "mm",
            "Illustrative reticle-scale die width. NVIDIA discloses a reticle-limit design but not dimensions.",
            "logic-geometry",
        ),
        "die_height_mm": synthetic_input(
            31.5,
            32,
            32.5,
            "mm",
            "Illustrative reticle-scale die height. NVIDIA discloses a reticle-limit design but not dimensions.",
            "logic-geometry",
        ),
        "scribe_width_mm": synthetic_input(
            0.07,
            0.1,
            0.13,
            "mm",
            "Illustrative scribe width added to both die dimensions.",
        ),
        "notes": "The gross-die result is a geometry sensitivity, not a disclosed Blackwell dies-per-wafer value.",
    }
    hbm_wafer = {
        "id": "hbm3e-memory-wafer",
        "name": "Illustrative HBM3E memory-die wafer flow",
        "wafer_starts": synthetic_input(
            90000,
            120000,
            150000,
            "wafer",
            "Illustrative combined HBM3E memory wafer starts before supplier and product allocation.",
            "hbm-front-end",
        ),
        "wafer_diameter_mm": synthetic_input(
            300,
            300,
            300,
            "mm",
            "Reference 300 mm DRAM wafer diameter; the cited product page does not disclose fab geometry.",
        ),
        "edge_exclusion_mm": synthetic_input(
            2,
            2.5,
            3,
            "mm",
            "Illustrative HBM wafer edge exclusion.",
        ),
        "die_width_mm": synthetic_input(
            9.5,
            10,
            10.5,
            "mm",
            "Illustrative HBM3E memory-die width; no supplier die dimension is asserted.",
            "hbm-geometry",
        ),
        "die_height_mm": synthetic_input(
            10.5,
            11,
            11.5,
            "mm",
            "Illustrative HBM3E memory-die height; no supplier die dimension is asserted.",
            "hbm-geometry",
        ),
        "scribe_width_mm": synthetic_input(
            0.05,
            0.08,
            0.11,
            "mm",
            "Illustrative HBM scribe width.",
        ),
        "notes": "Supplier mix, node, die size, wafer allocation, and redundancy repair remain unmodeled evidence gaps.",
    }

    document = {
        "format": "ai-supply-manufacturing.v1",
        "scenario": {
            "id": "blackwell-wafer-hbm-illustrative-2026q3",
            "name": "Blackwell wafer, HBM, and package conversion",
            "quarter": "2026-Q3",
            "as_of_date": AS_OF,
            "recorded_at": RECORDED_AT,
            "synthetic": True,
            "samples": 20000,
            "seed": 20260719,
            "notes": "Product topology uses primary NVIDIA and Micron documents. All process and capacity inputs remain synthetic.",
        },
        "evidence": evidence,
        "references": [
            {
                "id": "tsmc-total-wafer-shipments-2026q2",
                "name": "TSMC total 12-inch-equivalent wafer shipments",
                "period": "2026-Q2",
                "comparison_target": "logic_wafer_starts",
                "estimate": reported(
                    4_336_000,
                    "wafer",
                    "Uses TSMC's reported 2Q26 company-wide 12-inch-equivalent wafer shipments as a prior-quarter scale control. It does not isolate 4NP, NVIDIA, or Blackwell.",
                    "tsmc:2026q2-management-report",
                    "TSMC revises the reported 2Q26 shipment total or changes its unit basis.",
                ),
                "usable_as_product_capacity": False,
                "notes": "This prior-quarter company total checks scale only. It cannot allocate wafers by node, customer, or product and does not replace synthetic Blackwell wafer starts.",
            }
        ],
        "logic": {
            "wafer": logic_wafer,
            "defect_density_per_cm2": synthetic_input(
                0.05,
                0.08,
                0.12,
                "defects/cm2",
                "Illustrative random-defect density for the negative-binomial yield model.",
                "logic-yield",
            ),
            "clustering_alpha": synthetic_input(
                2,
                3,
                4,
                "alpha",
                "Illustrative negative-binomial defect-clustering parameter.",
                "logic-yield",
            ),
            "wafer_sort_yield": synthetic_input(
                0.92,
                0.96,
                0.985,
                "ratio",
                "Illustrative post-defect wafer-sort pass rate.",
                "logic-yield",
            ),
            "performance_bin_share": synthetic_input(
                0.65,
                0.78,
                0.88,
                "ratio",
                "Illustrative share of known-good logic dies that meet the modeled accelerator bin.",
                "logic-binning",
            ),
        },
        "hbm": {
            "wafer": hbm_wafer,
            "known_good_die_yield": synthetic_input(
                0.82,
                0.9,
                0.95,
                "ratio",
                "Illustrative HBM known-good memory-die yield after repair and test.",
                "hbm-yield",
            ),
            "memory_dies_per_stack": reported(
                8,
                "die/stack",
                "Uses Micron's disclosed 24 GB 8-high HBM3E product as a reference stack. It does not assert Micron supply to GB200.",
                "micron:hbm3e-reference",
                "A GB200 manufacturing BOM uses a different HBM layer count or capacity per placement.",
            ),
            "stack_assembly_yield": synthetic_input(
                0.88,
                0.94,
                0.98,
                "ratio",
                "Illustrative TSV stack-assembly yield.",
                "hbm-stack-yield",
            ),
            "stack_final_test_yield": synthetic_input(
                0.94,
                0.975,
                0.995,
                "ratio",
                "Illustrative final HBM stack test yield.",
                "hbm-stack-yield",
            ),
            "stack_capacity_gb": reported(
                24,
                "GB/stack",
                "Uses Micron's disclosed 24 GB 8-high HBM3E product as a reference placement.",
                "micron:hbm3e-reference",
                "The selected GB200 configuration uses a different capacity per HBM placement.",
            ),
            "stacks_per_accelerator": derived_topology(
                8,
                "stack/accelerator",
                "Divides NVIDIA's 192 GB per GB200 GPU by the 24 GB reference HBM3E placement. This derives eight placements and does not identify the memory supplier.",
                ["nvidia:gb200-memory", "micron:hbm3e-reference"],
                "A product BOM reports a different placement count or stack capacity.",
                0.82,
            ),
        },
        "package": {
            "assembly_starts": synthetic_input(
                350000,
                450000,
                550000,
                "package",
                "Illustrative quarterly advanced-package assembly starts allocated to the modeled accelerator.",
                "package-assembly",
            ),
            "assembly_yield": synthetic_input(
                0.9,
                0.95,
                0.98,
                "ratio",
                "Illustrative final advanced-package assembly and test yield.",
                "package-assembly",
            ),
            "logic_dies_per_accelerator": reported(
                2,
                "die/accelerator",
                "Uses NVIDIA's disclosure of two reticle-limit GPU dies in one Blackwell GPU.",
                "nvidia:blackwell-launch",
                "A product teardown or manufacturing BOM reports a different logic-die count.",
            ),
            "accelerators_per_system": reported(
                72,
                "accelerator/system",
                "Uses NVIDIA's disclosure of 72 Blackwell GPUs per GB200 NVL72.",
                "nvidia:gb200-product",
                "A current NVIDIA rack BOM reports a different GPU count.",
            ),
        },
    }
    OUTPUT.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
