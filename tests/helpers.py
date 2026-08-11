from __future__ import annotations

from supply_intelligence.models import (
    AllocationRule,
    CapacityBasis,
    ConsensusEstimate,
    Constraint,
    CustomerCategory,
    Estimate,
    EstimatePosture,
    Evidence,
    EvidenceKind,
    OpportunityFactors,
    Platform,
    QuarterlyScenario,
    ResourceKind,
    Stage,
    SupplierEconomics,
)


def estimate(
    value: float,
    unit: str,
    *,
    low: float | None = None,
    high: float | None = None,
    evidence_id: str = "evidence:test",
    posture: EstimatePosture = EstimatePosture.SYNTHETIC,
    correlation_group: str | None = None,
) -> Estimate:
    return Estimate(
        low=value if low is None else low,
        base=value,
        high=value if high is None else high,
        unit=unit,
        posture=posture,
        methodology="Deterministic test input.",
        confidence=1.0,
        last_updated="2026-07-17",
        evidence_ids=(evidence_id,),
        confirming_evidence="Replace the fixture with a matching observed value.",
        falsifying_evidence="Replace the fixture with a conflicting observed value.",
        correlation_group=correlation_group,
    )


def constraint(
    identifier: str,
    stage: Stage,
    capacity: float,
    unit: str,
    resource_kind: ResourceKind = ResourceKind.OTHER,
) -> Constraint:
    return Constraint(
        id=identifier,
        resource_kind=resource_kind,
        resource_name=identifier.replace("_", " ").title(),
        stage=stage,
        capacity_basis=CapacityBasis.ALLOCATED_OUTPUT,
        capacity=estimate(capacity, unit),
        effective_yield=estimate(1.0, "ratio"),
        platform_allocation=estimate(1.0, "ratio"),
        units_per_system=estimate(1.0, unit),
    )


def deterministic_scenario() -> QuarterlyScenario:
    evidence = Evidence(
        id="evidence:test",
        kind=EvidenceKind.SYNTHETIC,
        title="Synthetic test evidence",
        source_url="urn:synthetic:test",
        publisher="Test suite",
        retrieved_at="2026-07-17T12:00:00Z",
    )
    platform = Platform(
        id="platform:test",
        name="Test Rack",
        vendor="Example",
        system_unit="rack-scale system",
        accelerator_packages_per_system=estimate(4, "package/system"),
        servers_per_system=estimate(2, "server/system"),
        racks_per_system=estimate(1, "rack/system"),
    )
    constraints = (
        constraint(
            "packages",
            Stage.ACCELERATOR_PACKAGE,
            100,
            "package-set",
            ResourceKind.ACCELERATOR_PACKAGE,
        ),
        constraint(
            "servers",
            Stage.SERVER_ASSEMBLY,
            80,
            "server-set",
            ResourceKind.SERVER_ASSEMBLY,
        ),
        constraint(
            "racks",
            Stage.RACK_INTEGRATION,
            70,
            "rack-set",
            ResourceKind.RACK_INTEGRATION,
        ),
        constraint(
            "shipping",
            Stage.SHIPPED,
            60,
            "shipment-slot",
            ResourceKind.LOGISTICS,
        ),
        constraint(
            "installation",
            Stage.INSTALLED,
            50,
            "installation-slot",
            ResourceKind.QUALIFICATION,
        ),
        constraint(
            "power",
            Stage.OPERATIONAL,
            40,
            "power-slot",
            ResourceKind.DATACENTER_POWER,
        ),
    )
    allocations = (
        AllocationRule(
            id="customer:a",
            customer="Customer A",
            category=CustomerCategory.HYPERSCALER,
            share=estimate(0.75, "ratio"),
            demand_cap=estimate(30, "system"),
        ),
        AllocationRule(
            id="customer:b",
            customer="Customer B",
            category=CustomerCategory.MODEL_LAB,
            share=estimate(0.25, "ratio"),
            demand_cap=estimate(100, "system"),
        ),
    )
    economics = (
        SupplierEconomics(
            id="economics:example",
            supplier="Example Supplier",
            ticker="EXM",
            revenue_category="rack systems",
            recognition_stage=Stage.SHIPPED,
            units_per_system=estimate(1, "unit/system"),
            revenue_per_unit=estimate(10, "USD/unit"),
            gross_margin=estimate(0.5, "ratio"),
        ),
    )
    consensus = (
        ConsensusEstimate(
            id="consensus:example",
            supplier="Example Supplier",
            ticker="EXM",
            revenue=estimate(500, "USD"),
        ),
    )
    factors = (
        OpportunityFactors(
            id="factors:example",
            supplier="Example Supplier",
            ticker="EXM",
            confidence=estimate(1, "ratio"),
            liquidity=estimate(1, "ratio"),
            timing=estimate(1, "ratio"),
            catalyst_strength=estimate(1, "ratio"),
            actionability="Wait for proof.",
            variant_wedge="Deterministic test wedge.",
            what_is_priced_in="Deterministic test comparator.",
            why_now="The test runs now.",
            catalyst="Quarterly results.",
            first_rejection="No exposure attribution.",
            investable_if="The fixture is replaced by sourced evidence.",
            thesis_kill="Observed shipments below the modeled range.",
            next_workflow="Run a source-backed earnings bridge.",
        ),
    )
    return QuarterlyScenario(
        id="scenario:test",
        name="Deterministic test",
        quarter="2026-Q3",
        as_of_date="2026-07-17",
        recorded_at="2026-07-17T12:00:00Z",
        synthetic=True,
        samples=100,
        seed=17,
        platform=platform,
        evidence=(evidence,),
        constraints=constraints,
        allocations=allocations,
        supplier_economics=economics,
        consensus=consensus,
        opportunity_factors=factors,
    )
