"""Build the checked illustrative GB200 NVL72 quarterly scenario."""

from __future__ import annotations

import json
from pathlib import Path


AS_OF = "2026-07-17"
RECORDED_AT = "2026-07-18T01:49:33Z"
OUTPUT = Path(__file__).with_name("gb200-nvl72-illustrative-2026q3.json")


def estimate(
    low: float,
    base: float,
    high: float,
    unit: str,
    evidence_ids: list[str],
    *,
    posture: str,
    methodology: str,
    confidence: float,
    confirming: str,
    falsifying: str,
    correlation_group: str | None = None,
) -> dict[str, object]:
    return {
        "low": low,
        "base": base,
        "high": high,
        "unit": unit,
        "posture": posture,
        "methodology": methodology,
        "confidence": confidence,
        "last_updated": AS_OF,
        "evidence_ids": evidence_ids,
        "confirming_evidence": confirming,
        "falsifying_evidence": falsifying,
        "correlation_group": correlation_group,
    }


def reported(value: float, unit: str, method: str, evidence: str, falsifying: str) -> dict[str, object]:
    return estimate(
        value,
        value,
        value,
        unit,
        [evidence],
        posture="reported",
        methodology=method,
        confidence=0.98,
        confirming="A current NVIDIA BOM or service manual reports the same configuration.",
        falsifying=falsifying,
    )


def derived(
    low: float,
    base: float,
    high: float,
    unit: str,
    method: str,
    evidence: str,
    falsifying: str,
    confidence: float = 0.85,
) -> dict[str, object]:
    return estimate(
        low,
        base,
        high,
        unit,
        [evidence],
        posture="derived",
        methodology=method,
        confidence=confidence,
        confirming="A manufacturing BOM or current NVIDIA system specification supports the conversion.",
        falsifying=falsifying,
    )


def synthetic(
    low: float,
    base: float,
    high: float,
    unit: str,
    method: str,
    evidence: str,
    confirming: str,
    falsifying: str,
    correlation_group: str | None = None,
    confidence: float = 0.35,
) -> dict[str, object]:
    return estimate(
        low,
        base,
        high,
        unit,
        [evidence],
        posture="synthetic",
        methodology=method,
        confidence=confidence,
        confirming=confirming,
        falsifying=falsifying,
        correlation_group=correlation_group,
    )


def identity(unit: str, evidence: str, method: str) -> dict[str, object]:
    return estimate(
        1,
        1,
        1,
        unit,
        [evidence],
        posture="derived",
        methodology=method,
        confidence=1.0,
        confirming="The capacity definition remains on the stated post-adjustment basis.",
        falsifying="The capacity input is redefined to a pre-yield or pre-allocation basis.",
    )


def constraint(
    identifier: str,
    resource_kind: str,
    resource_name: str,
    stage: str,
    capacity_basis: str,
    capacity: dict[str, object],
    effective_yield: dict[str, object],
    allocation: dict[str, object],
    bom: dict[str, object],
    notes: str,
) -> dict[str, object]:
    return {
        "id": identifier,
        "resource_kind": resource_kind,
        "resource_name": resource_name,
        "stage": stage,
        "capacity_basis": capacity_basis,
        "capacity": capacity,
        "effective_yield": effective_yield,
        "platform_allocation": allocation,
        "units_per_system": bom,
        "notes": notes,
    }


def share(base: float) -> dict[str, object]:
    return synthetic(
        max(0, base - 0.04),
        base,
        min(1, base + 0.04),
        "ratio",
        "Illustrative customer-cohort share used only to exercise allocation and demand-cap logic.",
        "synthetic:allocation",
        "Customer prepayments, purchase commitments, ODM routing, or disclosed reserved capacity support this share.",
        "Shipment manifests or customer disclosures show a materially different allocation.",
        "customer-mix",
    )


def demand_cap(low: float, base: float, high: float) -> dict[str, object]:
    return synthetic(
        low,
        base,
        high,
        "system",
        "Illustrative quarterly cohort demand ceiling; not an order-book estimate.",
        "synthetic:allocation",
        "Purchase commitments and delivery schedules support the ceiling.",
        "Cancellations, export restrictions, or delivery data place demand outside the range.",
    )


def main() -> None:
    synthetic_capacity_method = (
        "Illustrative quarterly range selected to exercise the reconciliation engine. It is not an estimate of actual supplier capacity."
    )
    synthetic_yield_method = (
        "Illustrative effective yield after process, test, and quality loss; no actual yield claim is made."
    )
    synthetic_share_method = (
        "Illustrative share of the resource available to this platform after competing products and customers."
    )
    capacity_confirm = "Supplier output, tool throughput, utilization, inventory, and shipment evidence support this range."
    capacity_falsify = "Verified quarterly output or installed throughput falls outside this range."
    yield_confirm = "Known-good-output and scrap data support the modeled conversion rate."
    yield_falsify = "Supplier or customer qualification data show a materially different effective yield."
    share_confirm = "Reserved-capacity contracts, prepayments, or observed shipment mix support the platform share."
    share_falsify = "Allocation disclosures or shipment routing show a materially different platform share."

    evidence = [
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
            "excerpt": "NVIDIA reports 36 Grace CPUs, 72 Blackwell GPUs, 13.4 TB HBM3E, and liquid cooling for GB200 NVL72.",
            "content_hash": None,
        },
        {
            "id": "nvidia:dgx-gb-hardware",
            "kind": "company_technical_document",
            "title": "NVIDIA DGX GB Rack Scale Systems — Hardware",
            "source_url": "https://docs.nvidia.com/dgx/dgxgb200-user-guide/hardware.html",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": None,
            "source_family": "nvidia-gb200-documentation",
            "license": "NVIDIA documentation terms",
            "excerpt": "The guide reports 18 compute trays, 9 NVLink switch trays, 2 TOR switches, 4 ConnectX-7 NICs and 2 BlueField-3 DPUs per tray, eight power shelves, and approximately 120 kW rack consumption.",
            "content_hash": None,
        },
        {
            "id": "nvidia:blackwell-tuning",
            "kind": "company_technical_document",
            "title": "NVIDIA GB200 NVL Multi-Node Tuning Guide — Grace Blackwell Superchip",
            "source_url": "https://docs.nvidia.com/multi-node-nvlink-systems/multi-node-tuning-guide/overview.html",
            "publisher": "NVIDIA",
            "retrieved_at": RECORDED_AT,
            "published_at": "2025-04-21",
            "source_family": "nvidia-gb200-documentation",
            "license": "NVIDIA documentation terms",
            "excerpt": "NVIDIA describes 72 Blackwell GPUs and two reticle-limited dies per Blackwell GPU on a custom TSMC 4NP process.",
            "content_hash": None,
        },
        {
            "id": "synthetic:capacity",
            "kind": "synthetic",
            "title": "Illustrative capacity and yield assumptions",
            "source_url": "urn:synthetic:gb200-capacity-demo",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-demo",
            "license": "CC0-1.0",
            "excerpt": "All capacity, yield, and platform-share values linked here are deliberately synthetic.",
            "content_hash": None,
        },
        {
            "id": "synthetic:allocation",
            "kind": "synthetic",
            "title": "Illustrative customer allocation assumptions",
            "source_url": "urn:synthetic:gb200-allocation-demo",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-demo",
            "license": "CC0-1.0",
            "excerpt": "All customer shares and demand caps linked here are deliberately synthetic.",
            "content_hash": None,
        },
        {
            "id": "synthetic:economics",
            "kind": "synthetic",
            "title": "Illustrative supplier economics assumptions",
            "source_url": "urn:synthetic:gb200-economics-demo",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-demo",
            "license": "CC0-1.0",
            "excerpt": "Revenue per system and gross margin are demonstration inputs, not company guidance or estimates.",
            "content_hash": None,
        },
        {
            "id": "synthetic:consensus",
            "kind": "synthetic",
            "title": "Illustrative consensus comparator and opportunity factors",
            "source_url": "urn:synthetic:gb200-consensus-demo",
            "publisher": "AI Supply Intelligence demo",
            "retrieved_at": RECORDED_AT,
            "published_at": AS_OF,
            "source_family": "synthetic-demo",
            "license": "CC0-1.0",
            "excerpt": "The comparator and ranking factors are synthetic and must not be represented as sell-side consensus.",
            "content_hash": None,
        },
    ]

    constraints = [
        constraint(
            "blackwell-reticle-dies",
            "accelerator_die",
            "Blackwell reticle-limited dies",
            "accelerator_package",
            "nameplate_input",
            synthetic(150000, 180000, 215000, "die", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "front-end"),
            synthetic(0.62, 0.70, 0.78, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "front-end"),
            synthetic(0.34, 0.40, 0.47, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            derived(144, 144, 144, "die", "72 disclosed Blackwell GPUs multiplied by two reticle-limited dies per GPU.", "nvidia:blackwell-tuning", "A manufacturing BOM shows a different die count per delivered 72-GPU rack."),
            "Wafer starts are not yet modeled directly because die area, wafer gross die count, and yield need independent primary evidence.",
        ),
        constraint(
            "blackwell-packages",
            "advanced_packaging",
            "Blackwell advanced-package throughput",
            "accelerator_package",
            "tool_throughput",
            synthetic(33000, 39000, 46000, "package", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "packaging"),
            synthetic(0.86, 0.92, 0.96, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "packaging"),
            synthetic(0.72, 0.80, 0.88, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            derived(72, 72, 72, "package", "Treats each of the 72 disclosed Blackwell GPUs as one accelerator package for the first platform abstraction.", "nvidia:gb200-product", "A manufacturing BOM uses a different package/module definition.", 0.82),
            "Package is the first-release abstraction; future packs should separate compute dies, package modules, and superchips.",
        ),
        constraint(
            "hbm3e-capacity",
            "hbm_capacity",
            "HBM3E capacity",
            "accelerator_package",
            "known_good_output",
            synthetic(5500, 6500, 7800, "TB", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "memory"),
            synthetic(0.91, 0.95, 0.98, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "memory"),
            synthetic(0.72, 0.80, 0.88, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            reported(13.4, "TB", "Uses NVIDIA's aggregate HBM3E specification per GB200 NVL72 rack.", "nvidia:gb200-product", "A current NVIDIA specification reports materially different installed HBM capacity."),
            "Stack count remains unmodeled until stack density and configuration are supported by primary evidence.",
        ),
        constraint(
            "silicon-interposers",
            "silicon_interposer",
            "Silicon interposer equivalents",
            "accelerator_package",
            "known_good_output",
            synthetic(30000, 38000, 47000, "interposer", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "packaging"),
            synthetic(0.90, 0.94, 0.97, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "packaging"),
            synthetic(0.70, 0.78, 0.86, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            synthetic(64, 72, 80, "interposer", "Illustrative one-interposer-per-GPU-package abstraction; not a disclosed manufacturing BOM.", "synthetic:capacity", "Package cross-sections or supplier BOM evidence support the count.", "A manufacturing BOM shows a materially different interposer topology."),
            "Explicitly modeled rather than silently assuming packaging capacity includes interposers.",
        ),
        constraint(
            "abf-substrates",
            "abf_substrate",
            "ABF substrate equivalents",
            "accelerator_package",
            "known_good_output",
            synthetic(39000, 47000, 56000, "substrate", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "substrates"),
            synthetic(0.92, 0.96, 0.985, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "substrates"),
            synthetic(0.70, 0.79, 0.87, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            synthetic(64, 72, 80, "substrate", "Illustrative package-substrate requirement; not a disclosed manufacturing BOM.", "synthetic:capacity", "Supplier BOM evidence supports the count and substrate class.", "Package construction uses a materially different substrate count or technology."),
            "Substrate count and dimensions are a priority evidence gap.",
        ),
        constraint(
            "compute-tray-assembly",
            "server_assembly",
            "GB200 compute-tray assembly",
            "server_assembly",
            "sellable_output",
            synthetic(7200, 8600, 10200, "tray", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "odm"),
            synthetic(0.88, 0.93, 0.97, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "odm"),
            synthetic(0.86, 0.92, 0.97, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            reported(18, "tray", "NVIDIA reports 18 1RU compute trays per NVL72 rack.", "nvidia:dgx-gb-hardware", "A current rack BOM reports a different compute-tray count."),
            "The engine treats one compute tray as one complete server for the server-output metric.",
        ),
        constraint(
            "connectx7-nics",
            "retimer",
            "ConnectX-7 400G NICs",
            "server_assembly",
            "sellable_output",
            synthetic(30000, 37000, 45000, "NIC", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "networking"),
            synthetic(0.96, 0.98, 0.995, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "networking"),
            synthetic(0.82, 0.89, 0.95, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            derived(72, 72, 72, "NIC", "18 trays multiplied by four disclosed ConnectX-7 NICs per tray.", "nvidia:dgx-gb-hardware", "A current tray BOM reports a different NIC count."),
            "Retimer and NIC resources should be split when component-level board BOM evidence is available.",
        ),
        constraint(
            "bluefield3-dpus",
            "network_switch",
            "BlueField-3 DPUs",
            "server_assembly",
            "sellable_output",
            synthetic(15500, 19000, 23000, "DPU", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "networking"),
            synthetic(0.96, 0.985, 0.997, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "networking"),
            synthetic(0.82, 0.89, 0.95, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            derived(36, 36, 36, "DPU", "18 trays multiplied by two disclosed BlueField-3 DPUs per tray.", "nvidia:dgx-gb-hardware", "A current tray BOM reports a different DPU count."),
            "Network components are modeled independently so rack shipments cannot exceed them.",
        ),
        constraint(
            "nvlink-switch-trays",
            "network_switch",
            "NVLink switch trays",
            "rack_integration",
            "sellable_output",
            synthetic(3600, 4400, 5200, "switch_tray", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "networking"),
            synthetic(0.93, 0.97, 0.99, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "networking"),
            synthetic(0.86, 0.92, 0.97, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            reported(9, "switch_tray", "NVIDIA reports nine NVLink switch trays per NVL72 rack.", "nvidia:dgx-gb-hardware", "A current rack BOM reports a different switch-tray count."),
            "The switch tray is distinct from external scale-out network switches.",
        ),
        constraint(
            "management-tor-switches",
            "network_switch",
            "Management top-of-rack switches",
            "rack_integration",
            "sellable_output",
            synthetic(900, 1150, 1400, "switch", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "networking"),
            synthetic(0.97, 0.99, 0.999, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "networking"),
            synthetic(0.86, 0.92, 0.97, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            reported(2, "switch", "NVIDIA reports two management TOR switches per NVL72 rack.", "nvidia:dgx-gb-hardware", "A current rack BOM reports a different TOR-switch count."),
            "External compute and storage fabrics are not yet included in this single-rack scenario.",
        ),
        constraint(
            "power-shelves",
            "power_delivery",
            "Rack power shelves",
            "rack_integration",
            "sellable_output",
            synthetic(3500, 4200, 5000, "power_shelf", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "power-components"),
            synthetic(0.96, 0.985, 0.997, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "power-components"),
            synthetic(0.86, 0.92, 0.97, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            reported(8, "power_shelf", "NVIDIA reports eight power shelves per DGX GB200 NVL72 rack.", "nvidia:dgx-gb-hardware", "A current rack BOM reports a different power-shelf count."),
            "This does not include upstream switchgear, transformers, or backup generation.",
        ),
        constraint(
            "liquid-cooling-integration",
            "cooling",
            "Liquid-cooling rack integration",
            "rack_integration",
            "sellable_output",
            synthetic(380, 465, 560, "rack_cooling_set", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "rack-integration"),
            synthetic(0.88, 0.94, 0.98, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "rack-integration"),
            identity("ratio", "synthetic:capacity", "Capacity is already defined as GB200-compatible cooling sets."),
            derived(1, 1, 1, "rack_cooling_set", "One complete liquid-cooling integration set per liquid-cooled rack-scale system.", "nvidia:gb200-product", "The rack design is changed to require a different integration-set count."),
            "Facility-side CDUs and heat rejection are represented later through installation and power constraints.",
        ),
        constraint(
            "factory-qualification",
            "qualification",
            "Factory qualification slots",
            "shipped",
            "sellable_output",
            synthetic(350, 430, 520, "qualification_slot", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "system-qualification"),
            synthetic(0.90, 0.95, 0.98, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "system-qualification"),
            identity("ratio", "synthetic:capacity", "Qualification capacity is already scoped to the platform."),
            synthetic(1, 1, 1, "qualification_slot", "One end-to-end factory qualification slot per shipped system.", "synthetic:capacity", "ODM test flow confirms one slot per rack.", "Qualification requires materially different repeated or parallel slots."),
            "Qualification is separated from assembly to expose late-stage rack fallout.",
        ),
        constraint(
            "rack-logistics",
            "logistics",
            "Qualified rack logistics slots",
            "shipped",
            "sellable_output",
            synthetic(365, 450, 540, "shipment_slot", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "logistics"),
            synthetic(0.96, 0.985, 0.997, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "logistics"),
            identity("ratio", "synthetic:capacity", "Shipment capacity is already scoped to qualified rack systems."),
            synthetic(1, 1, 1, "shipment_slot", "One specialized shipment slot per rack-scale system.", "synthetic:capacity", "Freight bookings and delivery records support one slot per system.", "Observed shipment topology requires materially different logistics units."),
            "No real freight or customs data are used in this demonstration.",
        ),
        constraint(
            "site-installation",
            "rack_integration",
            "Customer-site installation slots",
            "installed",
            "installed_resource",
            synthetic(330, 410, 500, "installation_slot", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "site-readiness"),
            synthetic(0.92, 0.96, 0.99, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "site-readiness"),
            identity("ratio", "synthetic:capacity", "Installation slots are already scoped to the modeled system."),
            synthetic(1, 1, 1, "installation_slot", "One physical installation and facility-integration slot per rack-scale system.", "synthetic:capacity", "Site commissioning records support one slot per system.", "Observed installation flow requires materially different units."),
            "Separates shipped systems from installed systems.",
        ),
        constraint(
            "energized-datacenter-power",
            "datacenter_power",
            "Energized critical IT power",
            "operational",
            "energized_resource",
            synthetic(39, 49, 62, "MW", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "site-readiness"),
            identity("ratio", "synthetic:capacity", "Power input is already defined as energized critical IT MW."),
            synthetic(0.76, 0.84, 0.91, "ratio", synthetic_share_method, "synthetic:capacity", share_confirm, share_falsify, "platform-share"),
            derived(0.11, 0.12, 0.13, "MW", "Converts NVIDIA's approximately 120 kW rack consumption into a 0.12 MW base with a narrow interpretation range.", "nvidia:dgx-gb-hardware", "Metered steady-state critical IT load falls outside 110–130 kW per rack.", 0.88),
            "Power is an energized deployment constraint, not a substitute for grid interconnection or facility gross load.",
        ),
        constraint(
            "datacenter-commissioning",
            "datacenter_commissioning",
            "Data-center commissioning slots",
            "operational",
            "installed_resource",
            synthetic(300, 385, 475, "commissioning_slot", synthetic_capacity_method, "synthetic:capacity", capacity_confirm, capacity_falsify, "site-readiness"),
            synthetic(0.91, 0.96, 0.99, "ratio", synthetic_yield_method, "synthetic:capacity", yield_confirm, yield_falsify, "site-readiness"),
            identity("ratio", "synthetic:capacity", "Commissioning capacity is already scoped to this rack class."),
            synthetic(1, 1, 1, "commissioning_slot", "One burn-in, network, cooling, and acceptance commissioning slot per installed system.", "synthetic:capacity", "Commissioning records support one slot per system.", "Acceptance workflow requires materially different units or repeated attempts."),
            "This keeps installed hardware distinct from operational hardware.",
        ),
    ]

    allocations = [
        {"id": "allocation:hyperscaler-a", "customer": "Hyperscaler cohort A", "category": "hyperscaler", "share": share(0.30), "demand_cap": demand_cap(110, 150, 190), "notes": "Anonymous demonstration cohort."},
        {"id": "allocation:hyperscaler-b", "customer": "Hyperscaler cohort B", "category": "hyperscaler", "share": share(0.23), "demand_cap": demand_cap(90, 125, 165), "notes": "Anonymous demonstration cohort."},
        {"id": "allocation:model-labs", "customer": "Model laboratories", "category": "model_lab", "share": share(0.17), "demand_cap": demand_cap(60, 95, 130), "notes": "Category-level demonstration only."},
        {"id": "allocation:neoclouds", "customer": "Neoclouds", "category": "neocloud", "share": share(0.12), "demand_cap": demand_cap(40, 70, 100), "notes": "Category-level demonstration only."},
        {"id": "allocation:sovereign", "customer": "Sovereign projects", "category": "sovereign", "share": share(0.09), "demand_cap": demand_cap(25, 50, 80), "notes": "Category-level demonstration only."},
        {"id": "allocation:enterprise", "customer": "Enterprises", "category": "enterprise", "share": share(0.07), "demand_cap": demand_cap(20, 40, 65), "notes": "Category-level demonstration only."},
        {"id": "allocation:china", "customer": "Chinese buyers", "category": "china", "share": share(0.02), "demand_cap": demand_cap(0, 10, 25), "notes": "Purely illustrative; no claim about product eligibility, licensing, routing, or actual shipments."},
    ]

    supplier_economics = [
        {
            "id": "economics:nvidia-gb200",
            "supplier": "NVIDIA",
            "ticker": "NVDA",
            "revenue_category": "Illustrative GB200 NVL72 platform-linked revenue",
            "recognition_stage": "shipped",
            "units_per_system": synthetic(1, 1, 1, "unit/system", "One modeled platform revenue unit per shipped rack.", "synthetic:economics", "Revenue recognition maps one shipped rack to one platform unit.", "Company accounting or bundle structure maps revenue differently."),
            "revenue_per_unit": synthetic(2500000, 3200000, 4000000, "USD/unit", "Illustrative system-level revenue range; not disclosed ASP or guidance.", "synthetic:economics", "Contracts, distributor quotes, or filings support the platform revenue range.", "Verified pricing or accounting allocation falls outside the range."),
            "gross_margin": synthetic(0.58, 0.66, 0.73, "ratio", "Illustrative platform contribution margin; not NVIDIA company gross margin guidance.", "synthetic:economics", "Segment cost structure supports the range.", "Reported or reconstructed platform contribution margin falls outside the range."),
        }
    ]

    consensus = [
        {
            "id": "consensus:nvidia-platform-demo",
            "supplier": "NVIDIA",
            "ticker": "NVDA",
            "revenue": synthetic(850000000, 1100000000, 1450000000, "USD", "Synthetic platform-linked comparator used only to exercise discrepancy math; not sell-side consensus or total-company revenue.", "synthetic:consensus", "A sourced platform-specific consensus bridge supports the range.", "A sourced estimate set places the comparable revenue outside the range."),
        }
    ]

    opportunity_factors = [
        {
            "id": "opportunity:nvidia-demo",
            "supplier": "NVIDIA",
            "ticker": "NVDA",
            "confidence": synthetic(0.25, 0.35, 0.48, "ratio", "Illustrative confidence penalty for a mostly synthetic scenario.", "synthetic:consensus", "Multiple independent sources converge on the physical and economic bridge.", "Source conflicts or failed backtests reduce calibration."),
            "liquidity": synthetic(0.95, 0.99, 1.0, "ratio", "Illustrative normalized liquidity factor for ranking demonstrations.", "synthetic:consensus", "Current traded value and depth support a near-one factor.", "Liquidity deteriorates materially."),
            "timing": synthetic(0.55, 0.70, 0.82, "ratio", "Illustrative timing factor for a next-quarter estimate-revision window.", "synthetic:consensus", "A dated earnings or supplier catalyst falls inside the modeled window.", "The evidence cannot affect estimates within the window."),
            "catalyst_strength": synthetic(0.35, 0.50, 0.68, "ratio", "Illustrative catalyst strength pending real shipment and supplier evidence.", "synthetic:consensus", "Shipment data and supplier commentary create a visible estimate bridge.", "No identifiable public catalyst links the evidence to estimates."),
            "actionability": "Wait for proof; this row is plumbing validation, not an investable signal.",
            "variant_wedge": "No investable variant wedge exists yet. The displayed revision is produced from synthetic capacity, economics, and comparator inputs.",
            "what_is_priced_in": "Unavailable. No current share price, valuation, positioning, or sourced sell-side estimate set is included.",
            "why_now": "The physical model can now define which shipment, HBM, packaging, power, and commissioning evidence must be collected before the next earnings window.",
            "catalyst": "Sourced shipment, HBM, packaging, and data-center commissioning evidence followed by the next earnings cycle.",
            "first_rejection": "The modeled capacity and economics are still synthetic, so exposure attribution is not investable.",
            "investable_if": "Primary evidence replaces the synthetic capacity ranges, a platform-to-company earnings bridge is sourced, current consensus and valuation are frozen, and the gap survives downside testing.",
            "thesis_kill": "Primary evidence fails to support the shipment range or the platform-to-revenue bridge.",
            "next_workflow": "Build a source-backed earnings bridge, verify current consensus and valuation, then underwrite a dated long/short pitch only if a variant wedge remains.",
        }
    ]

    document = {
        "format": "ai-supply-scenario.v1",
        "scenario": {
            "id": "gb200-nvl72-illustrative-2026q3",
            "name": "GB200 NVL72 illustrative chain reconciliation",
            "quarter": "2026-Q3",
            "as_of_date": AS_OF,
            "recorded_at": RECORDED_AT,
            "synthetic": True,
            "samples": 20000,
            "seed": 20260717,
            "notes": "NVIDIA product configuration is source-backed. All supply capacity, yield, platform allocation, customer allocation, economics, consensus, and opportunity factors are explicitly synthetic demonstration inputs.",
        },
        "platform": {
            "id": "nvidia-gb200-nvl72",
            "name": "NVIDIA GB200 NVL72",
            "vendor": "NVIDIA",
            "system_unit": "rack-scale system",
            "accelerator_packages_per_system": derived(72, 72, 72, "package/system", "Treats each disclosed Blackwell GPU as one accelerator package for the first-release output metric.", "nvidia:gb200-product", "A manufacturing BOM uses a different package or module definition.", 0.82),
            "servers_per_system": reported(18, "server/system", "Treats each of the 18 disclosed compute trays as one server node.", "nvidia:dgx-gb-hardware", "A current rack specification reports a different compute-node count."),
            "racks_per_system": reported(1, "rack/system", "The platform system unit is one NVL72 rack.", "nvidia:gb200-product", "The modeled system boundary changes from one rack."),
            "notes": "Actual disclosed rack configuration; manufacturing package semantics remain an explicit abstraction.",
        },
        "evidence": evidence,
        "constraints": constraints,
        "allocations": allocations,
        "supplier_economics": supplier_economics,
        "consensus": consensus,
        "opportunity_factors": opportunity_factors,
    }
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
