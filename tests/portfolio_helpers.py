from __future__ import annotations

from supply_intelligence.models import (
    CapacityBasis,
    Evidence,
    EvidenceKind,
    Platform,
    ResourceKind,
    Stage,
)
from supply_intelligence.portfolio_models import (
    PlatformDemand,
    PlatformRequirement,
    PortfolioScenario,
    SharedResourcePool,
)

from tests.helpers import estimate


def platform(identifier: str, packages: float) -> PlatformDemand:
    return PlatformDemand(
        platform=Platform(
            id=identifier,
            name=f"Platform {identifier.upper()}",
            vendor="Example",
            system_unit="rack",
            accelerator_packages_per_system=estimate(packages, "package/system"),
            servers_per_system=estimate(2, "server/system"),
            racks_per_system=estimate(1, "rack/system"),
        ),
        demand=estimate(100, "system"),
        priority_weight=estimate(1, "weight"),
    )


def pool(
    identifier: str,
    stage: Stage,
    capacity: float,
    unit: str,
    kind: ResourceKind = ResourceKind.OTHER,
) -> SharedResourcePool:
    return SharedResourcePool(
        id=identifier,
        resource_kind=kind,
        resource_name=identifier.replace("_", " ").title(),
        stage=stage,
        capacity_basis=CapacityBasis.ALLOCATED_OUTPUT,
        capacity=estimate(capacity, unit),
        effective_yield=estimate(1, "ratio"),
    )


def requirement(
    identifier: str,
    platform_id: str,
    resource_id: str,
    unit: str,
    quantity: float = 1,
) -> PlatformRequirement:
    return PlatformRequirement(
        id=identifier,
        platform_id=platform_id,
        resource_pool_id=resource_id,
        units_per_system=estimate(quantity, unit),
    )


def deterministic_portfolio() -> PortfolioScenario:
    evidence = Evidence(
        id="evidence:test",
        kind=EvidenceKind.SYNTHETIC,
        title="Synthetic portfolio test evidence",
        source_url="urn:synthetic:portfolio-test",
        publisher="Test suite",
        retrieved_at="2026-07-17T12:00:00Z",
    )
    resources = (
        pool(
            "shared_wafers",
            Stage.ACCELERATOR_PACKAGE,
            100,
            "wafer_set",
            ResourceKind.LEADING_EDGE_WAFER,
        ),
        pool(
            "assembly_a",
            Stage.SERVER_ASSEMBLY,
            20,
            "assembly_slot",
            ResourceKind.SERVER_ASSEMBLY,
        ),
        pool(
            "assembly_b",
            Stage.SERVER_ASSEMBLY,
            100,
            "assembly_slot",
            ResourceKind.SERVER_ASSEMBLY,
        ),
        pool(
            "shared_rack_integration",
            Stage.RACK_INTEGRATION,
            60,
            "rack_slot",
            ResourceKind.RACK_INTEGRATION,
        ),
        pool(
            "shared_shipping",
            Stage.SHIPPED,
            50,
            "shipment_slot",
            ResourceKind.LOGISTICS,
        ),
        pool(
            "shared_installation",
            Stage.INSTALLED,
            45,
            "installation_slot",
            ResourceKind.QUALIFICATION,
        ),
        pool(
            "shared_power",
            Stage.OPERATIONAL,
            30,
            "power_unit",
            ResourceKind.DATACENTER_POWER,
        ),
    )
    requirements = (
        requirement("a-wafers", "a", "shared_wafers", "wafer_set"),
        requirement("b-wafers", "b", "shared_wafers", "wafer_set"),
        requirement("a-assembly", "a", "assembly_a", "assembly_slot"),
        requirement("b-assembly", "b", "assembly_b", "assembly_slot"),
        requirement("a-rack", "a", "shared_rack_integration", "rack_slot"),
        requirement("b-rack", "b", "shared_rack_integration", "rack_slot"),
        requirement("a-ship", "a", "shared_shipping", "shipment_slot"),
        requirement("b-ship", "b", "shared_shipping", "shipment_slot"),
        requirement("a-install", "a", "shared_installation", "installation_slot"),
        requirement("b-install", "b", "shared_installation", "installation_slot"),
        requirement("a-power", "a", "shared_power", "power_unit", 2),
        requirement("b-power", "b", "shared_power", "power_unit", 1),
    )
    return PortfolioScenario(
        id="portfolio:test",
        name="Deterministic shared-resource portfolio",
        quarter="2026-Q3",
        as_of_date="2026-07-17",
        recorded_at="2026-07-17T12:00:00Z",
        synthetic=True,
        samples=100,
        seed=19,
        evidence=(evidence,),
        platforms=(platform("a", 4), platform("b", 8)),
        resource_pools=resources,
        requirements=requirements,
    )
