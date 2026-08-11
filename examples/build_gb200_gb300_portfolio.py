"""Build the checked GB200 and GB300 shared-resource demonstration."""

from __future__ import annotations

import json
from pathlib import Path

from build_gb200_illustrative import AS_OF, derived, identity, reported, synthetic


RECORDED_AT = "2026-07-18T02:07:24Z"
OUTPUT = Path(__file__).with_name(
    "gb200-gb300-shared-illustrative-2026q3.json"
)


def capacity(
    low: float,
    base: float,
    high: float,
    unit: str,
    group: str,
) -> dict[str, object]:
    return synthetic(
        low,
        base,
        high,
        unit,
        "Illustrative quarterly shared-pool range selected to test cross-platform conservation. It is not an estimate of actual supplier capacity.",
        "synthetic:shared-capacity",
        "Supplier output, installed tool throughput, utilization, and inventory evidence support the pool range.",
        "Verified shared-pool output falls outside the range.",
        group,
    )


def yield_range(
    low: float,
    base: float,
    high: float,
    group: str,
) -> dict[str, object]:
    return synthetic(
        low,
        base,
        high,
        "ratio",
        "Illustrative effective yield applied once to the shared pool.",
        "synthetic:shared-capacity",
        "Known-good-output and scrap evidence support the yield range.",
        "Qualification or output data show a materially different yield.",
        group,
    )


def resource(
    identifier: str,
    kind: str,
    name: str,
    stage: str,
    basis: str,
    capacity_estimate: dict[str, object],
    yield_estimate: dict[str, object],
    notes: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "resource_kind": kind,
        "resource_name": name,
        "stage": stage,
        "capacity_basis": basis,
        "capacity": capacity_estimate,
        "effective_yield": yield_estimate,
        "notes": notes,
    }


def requirement(
    identifier: str,
    platform_id: str,
    resource_id: str,
    estimate: dict[str, object],
    notes: str = "",
) -> dict[str, object]:
    return {
        "id": identifier,
        "platform_id": platform_id,
        "resource_pool_id": resource_id,
        "units_per_system": estimate,
        "notes": notes,
    }


def one_per_system(unit: str, method: str) -> dict[str, object]:
    return synthetic(
        1,
        1,
        1,
        unit,
        method,
        "synthetic:shared-capacity",
        "The operating workflow confirms one resource unit per rack-scale system.",
        "The workflow requires a different unit count per system.",
    )


def main() -> None:
    evidence = [
        {
            "id": "nvidia:gb200-product",
            "kind": "company_technical_document",
            "title": "NVIDIA GB200 NVL72 product specifications",
            "source_url": "https://www.nvidia.com/en-us/data-center/gb200-nvl72/",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-nvl72-documentation",
            "license": "NVIDIA website terms",
            "excerpt": "NVIDIA reports 72 Blackwell GPUs, 36 Grace CPUs, 13.4 TB HBM3E, and a liquid-cooled rack-scale design.",
            "content_hash": None,
        },
        {
            "id": "nvidia:gb200-hardware",
            "kind": "company_technical_document",
            "title": "NVIDIA DGX GB Rack Scale Systems hardware guide",
            "source_url": "https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-nvl72-documentation",
            "license": "NVIDIA documentation terms",
            "excerpt": "The guide reports 18 compute trays, 9 NVLink switch trays, 8 power shelves, and approximately 120 kW rack consumption.",
            "content_hash": None,
        },
        {
            "id": "nvidia:gb300-product",
            "kind": "company_technical_document",
            "title": "NVIDIA GB300 NVL72 product specifications",
            "source_url": "https://www.nvidia.com/en-us/data-center/gb300-nvl72/",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-nvl72-documentation",
            "license": "NVIDIA website terms",
            "excerpt": "NVIDIA reports 72 Blackwell Ultra GPUs, 36 Grace CPUs, and 20 TB of GPU memory in a liquid-cooled rack-scale platform.",
            "content_hash": None,
        },
        {
            "id": "nvidia:gb300-components",
            "kind": "company_technical_document",
            "title": "NVIDIA NVL72 AI Factory system hardware and components",
            "source_url": "https://docs.nvidia.com/enterprise-reference-architectures/nvl72-ai-factory/latest/components.html",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": "2026-03-01",
            "source_family": "nvidia-nvl72-documentation",
            "license": "NVIDIA documentation terms",
            "excerpt": "NVIDIA reports 4 B300 GPUs and 2 Grace CPUs per compute tray, 9 NVSwitch trays, 8 power shelves, and up to 142 kW per rack.",
            "content_hash": None,
        },
        {
            "id": "synthetic:shared-capacity",
            "kind": "synthetic",
            "title": "Illustrative shared capacity, yield, and stage throughput",
            "source_url": "urn:synthetic:gb200-gb300-shared-capacity",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-portfolio-demo",
            "license": "CC0-1.0",
            "excerpt": "All shared capacity, yield, qualification, logistics, installation, and commissioning ranges linked here are synthetic.",
            "content_hash": None,
        },
        {
            "id": "synthetic:portfolio-policy",
            "kind": "synthetic",
            "title": "Illustrative platform demand and allocation weights",
            "source_url": "urn:synthetic:gb200-gb300-portfolio-policy",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-portfolio-demo",
            "license": "CC0-1.0",
            "excerpt": "Demand ranges and priority weights are synthetic and do not represent orders or reserved capacity.",
            "content_hash": None,
        },
    ]

    def platform(
        identifier: str,
        name: str,
        product_evidence: str,
        demand_values: tuple[float, float, float],
        weight_values: tuple[float, float, float],
    ) -> dict[str, object]:
        return {
            "platform": {
                "id": identifier,
                "name": name,
                "vendor": "NVIDIA",
                "system_unit": "rack-scale system",
                "accelerator_packages_per_system": derived(
                    72,
                    72,
                    72,
                    "package/system",
                    "Treats each of the 72 disclosed GPUs as one accelerator package for the portfolio output metric.",
                    product_evidence,
                    "A manufacturing BOM uses a different package or module definition.",
                    0.82,
                ),
                "servers_per_system": derived(
                    18,
                    18,
                    18,
                    "server/system",
                    "Uses 18 compute trays as 18 complete server nodes per rack.",
                    "nvidia:gb200-hardware" if identifier == "nvidia-gb200-nvl72" else "nvidia:gb300-components",
                    "A current rack specification reports a different compute-node count.",
                    0.95,
                ),
                "racks_per_system": reported(
                    1,
                    "rack/system",
                    "The platform boundary is one NVL72 rack-scale system.",
                    product_evidence,
                    "The modeled system boundary changes from one rack.",
                ),
                "notes": "Product configuration is source-backed; manufacturing package semantics remain a derived abstraction.",
            },
            "demand": synthetic(
                *demand_values,
                "system",
                "Illustrative quarterly platform demand ceiling; not an order-book estimate.",
                "synthetic:portfolio-policy",
                "Customer commitments and delivery schedules support the demand range.",
                "Cancellations, substitutions, or order evidence place demand outside the range.",
                "portfolio-demand",
            ),
            "priority_weight": synthetic(
                *weight_values,
                "weight",
                "Illustrative progressive-allocation weight; not an inferred contract priority.",
                "synthetic:portfolio-policy",
                "Reserved capacity, prepayments, and supplier allocation records support the weight.",
                "Observed product mix or contractual priority conflicts with the weight.",
                "portfolio-priority",
            ),
        }

    platforms = [
        platform(
            "nvidia-gb200-nvl72",
            "NVIDIA GB200 NVL72",
            "nvidia:gb200-product",
            (320, 400, 480),
            (0.72, 0.85, 1.00),
        ),
        platform(
            "nvidia-gb300-nvl72",
            "NVIDIA GB300 NVL72",
            "nvidia:gb300-product",
            (390, 500, 610),
            (1.05, 1.25, 1.48),
        ),
    ]

    resources = [
        resource("shared-advanced-packaging", "advanced_packaging", "Shared advanced-package output", "accelerator_package", "known_good_output", capacity(45000, 55000, 66000, "package", "packaging"), yield_range(0.88, 0.93, 0.97, "packaging"), "One pool is consumed by both platforms."),
        resource("shared-hbm3e", "hbm_capacity", "Shared HBM3E output", "accelerator_package", "known_good_output", capacity(6900, 8500, 10300, "TB", "memory"), yield_range(0.91, 0.95, 0.98, "memory"), "Aggregate HBM terabytes remain a placeholder for a later stack-level pool."),
        resource("shared-interposers", "silicon_interposer", "Shared silicon interposer output", "accelerator_package", "known_good_output", capacity(44000, 53500, 64000, "interposer", "packaging"), yield_range(0.91, 0.95, 0.98, "packaging"), "Per-package interposer requirements are synthetic until manufacturing BOM evidence is added."),
        resource("shared-abf-substrates", "abf_substrate", "Shared ABF substrate output", "accelerator_package", "known_good_output", capacity(50000, 61500, 73500, "substrate", "substrates"), yield_range(0.93, 0.97, 0.99, "substrates"), "Substrate dimensions and technology variants remain unmodeled."),
        resource("shared-compute-tray-assembly", "server_assembly", "Shared compute-tray assembly", "server_assembly", "sellable_output", capacity(9000, 11000, 13200, "tray", "odm"), yield_range(0.90, 0.94, 0.98, "odm"), "The pool tests shared ODM labor and line capacity."),
        resource("shared-nvlink-switch-trays", "network_switch", "Shared NVLink switch-tray output", "rack_integration", "sellable_output", capacity(4800, 6000, 7200, "switch_tray", "networking"), yield_range(0.94, 0.97, 0.99, "networking"), "Both rack configurations consume nine switch trays."),
        resource("shared-power-shelves", "power_delivery", "Shared rack power-shelf output", "rack_integration", "sellable_output", capacity(4100, 5050, 6050, "power_shelf", "power-components"), yield_range(0.95, 0.98, 0.995, "power-components"), "Both disclosed racks consume eight power shelves."),
        resource("shared-liquid-cooling", "cooling", "Shared liquid-cooling integration", "rack_integration", "sellable_output", capacity(400, 500, 600, "rack_cooling_set", "rack-integration"), yield_range(0.90, 0.95, 0.98, "rack-integration"), "Facility-side cooling remains a later installation constraint."),
        resource("shared-qualification", "qualification", "Shared rack qualification", "shipped", "sellable_output", capacity(360, 445, 535, "qualification_slot", "qualification"), yield_range(0.91, 0.96, 0.99, "qualification"), "Qualification remains separate from tray assembly."),
        resource("shared-logistics", "logistics", "Shared rack logistics", "shipped", "sellable_output", capacity(350, 430, 520, "shipment_slot", "logistics"), yield_range(0.96, 0.985, 0.997, "logistics"), "No real freight or customs data are used."),
        resource("shared-installation", "rack_integration", "Shared customer-site installation", "installed", "installed_resource", capacity(315, 395, 480, "installation_slot", "site-readiness"), yield_range(0.93, 0.97, 0.99, "site-readiness"), "Separates shipped systems from installed systems."),
        resource("shared-energized-power", "datacenter_power", "Shared energized critical IT power", "operational", "energized_resource", capacity(40, 50, 62, "MW", "site-readiness"), identity("ratio", "synthetic:shared-capacity", "Capacity is already defined as energized critical IT MW."), "Power requirements use disclosed rack values while regional availability remains synthetic."),
        resource("shared-commissioning", "datacenter_commissioning", "Shared data-center commissioning", "operational", "installed_resource", capacity(280, 345, 420, "commissioning_slot", "site-readiness"), yield_range(0.92, 0.97, 0.99, "site-readiness"), "Keeps installed hardware distinct from operational hardware."),
    ]

    requirements = []
    for platform_id in ("nvidia-gb200-nvl72", "nvidia-gb300-nvl72"):
        product_evidence = "nvidia:gb200-product" if "gb200" in platform_id else "nvidia:gb300-product"
        hardware_evidence = "nvidia:gb200-hardware" if "gb200" in platform_id else "nvidia:gb300-components"
        requirements.extend(
            [
                requirement(f"{platform_id}:packages", platform_id, "shared-advanced-packaging", derived(72, 72, 72, "package", "Uses 72 disclosed GPUs as 72 package equivalents per system.", product_evidence, "A manufacturing BOM uses a different package count.", 0.82)),
                requirement(f"{platform_id}:interposers", platform_id, "shared-interposers", synthetic(66, 72, 78, "interposer", "Illustrative one-interposer-per-package abstraction.", "synthetic:shared-capacity", "Package cross-sections support the count.", "A manufacturing BOM shows a different topology.")),
                requirement(f"{platform_id}:substrates", platform_id, "shared-abf-substrates", synthetic(66, 72, 78, "substrate", "Illustrative one-substrate-per-package abstraction.", "synthetic:shared-capacity", "Supplier BOM evidence supports the count.", "Package construction uses a different substrate count.")),
                requirement(f"{platform_id}:trays", platform_id, "shared-compute-tray-assembly", derived(18, 18, 18, "tray", "Uses 18 compute trays per rack.", hardware_evidence, "A current rack BOM reports a different tray count.", 0.95)),
                requirement(f"{platform_id}:switch-trays", platform_id, "shared-nvlink-switch-trays", reported(9, "switch_tray", "Uses nine disclosed NVLink switch trays per rack.", hardware_evidence, "A current rack BOM reports a different switch-tray count.")),
                requirement(f"{platform_id}:power-shelves", platform_id, "shared-power-shelves", reported(8, "power_shelf", "Uses eight disclosed power shelves per rack.", hardware_evidence, "A current rack BOM reports a different power-shelf count.")),
                requirement(f"{platform_id}:cooling", platform_id, "shared-liquid-cooling", derived(1, 1, 1, "rack_cooling_set", "Uses one complete liquid-cooling integration set per liquid-cooled rack.", product_evidence, "The rack design needs a different cooling-set count.")),
                requirement(f"{platform_id}:qualification", platform_id, "shared-qualification", one_per_system("qualification_slot", "One end-to-end qualification slot per rack-scale system.")),
                requirement(f"{platform_id}:logistics", platform_id, "shared-logistics", one_per_system("shipment_slot", "One specialized shipment slot per rack-scale system.")),
                requirement(f"{platform_id}:installation", platform_id, "shared-installation", one_per_system("installation_slot", "One customer-site installation slot per rack-scale system.")),
                requirement(f"{platform_id}:commissioning", platform_id, "shared-commissioning", one_per_system("commissioning_slot", "One acceptance commissioning slot per installed rack-scale system.")),
            ]
        )

    requirements.extend(
        [
            requirement("nvidia-gb200-nvl72:hbm", "nvidia-gb200-nvl72", "shared-hbm3e", reported(13.4, "TB", "Uses NVIDIA's aggregate HBM3E specification per GB200 NVL72.", "nvidia:gb200-product", "A current NVIDIA specification reports a different aggregate HBM capacity.")),
            requirement("nvidia-gb300-nvl72:hbm", "nvidia-gb300-nvl72", "shared-hbm3e", reported(20, "TB", "Uses NVIDIA's aggregate GPU-memory specification per GB300 NVL72.", "nvidia:gb300-product", "A current NVIDIA specification reports a different aggregate GPU-memory capacity.")),
            requirement("nvidia-gb200-nvl72:power", "nvidia-gb200-nvl72", "shared-energized-power", derived(0.11, 0.12, 0.13, "MW", "Converts approximately 120 kW rack consumption into a 0.12 MW base range.", "nvidia:gb200-hardware", "Metered rack demand falls outside 110–130 kW.", 0.88)),
            requirement("nvidia-gb300-nvl72:power", "nvidia-gb300-nvl72", "shared-energized-power", derived(0.13, 0.142, 0.15, "MW", "Converts NVIDIA's up-to-142 kW rack requirement into a narrow deployment range.", "nvidia:gb300-components", "Metered rack demand falls outside 130–150 kW.", 0.88)),
        ]
    )

    document = {
        "format": "ai-supply-portfolio.v1",
        "scenario": {
            "id": "gb200-gb300-shared-illustrative-2026q3",
            "name": "GB200 and GB300 shared-resource reconciliation",
            "quarter": "2026-Q3",
            "as_of_date": AS_OF,
            "recorded_at": RECORDED_AT,
            "synthetic": True,
            "samples": 20000,
            "seed": 20260718,
            "notes": "NVIDIA rack requirements are source-backed where disclosed. Shared capacity, demand, allocation priority, yield, qualification, logistics, installation, and commissioning inputs are synthetic.",
        },
        "evidence": evidence,
        "platforms": platforms,
        "resource_pools": resources,
        "requirements": requirements,
    }
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
