from __future__ import annotations

from dataclasses import replace

from supply_intelligence.manufacturing_models import (
    HbmStackFlow,
    LogicDieFlow,
    ManufacturingScenario,
    PackageAssemblyFlow,
    WaferFlow,
)
from supply_intelligence.models import Evidence, EvidenceKind

from tests.helpers import estimate


def deterministic_manufacturing() -> ManufacturingScenario:
    evidence = Evidence(
        id="evidence:test",
        kind=EvidenceKind.SYNTHETIC,
        title="Synthetic manufacturing test evidence",
        source_url="urn:synthetic:manufacturing-test",
        publisher="Test suite",
        retrieved_at="2026-07-17T12:00:00Z",
    )
    logic_wafer = WaferFlow(
        id="logic-wafer",
        name="Logic wafer",
        wafer_starts=estimate(1, "wafer"),
        wafer_diameter_mm=estimate(300, "mm"),
        edge_exclusion_mm=estimate(0, "mm"),
        die_width_mm=estimate(30, "mm"),
        die_height_mm=estimate(30, "mm"),
        scribe_width_mm=estimate(0, "mm"),
    )
    hbm_wafer = WaferFlow(
        id="hbm-wafer",
        name="HBM wafer",
        wafer_starts=estimate(1, "wafer"),
        wafer_diameter_mm=estimate(300, "mm"),
        edge_exclusion_mm=estimate(0, "mm"),
        die_width_mm=estimate(10, "mm"),
        die_height_mm=estimate(10, "mm"),
        scribe_width_mm=estimate(0, "mm"),
    )
    return ManufacturingScenario(
        id="manufacturing:test",
        name="Deterministic manufacturing test",
        quarter="2026-Q3",
        as_of_date="2026-07-17",
        recorded_at="2026-07-17T12:00:00Z",
        synthetic=True,
        samples=100,
        seed=23,
        evidence=(evidence,),
        logic=LogicDieFlow(
            wafer=logic_wafer,
            defect_density_per_cm2=estimate(0, "defects/cm2"),
            clustering_alpha=estimate(2, "alpha"),
            wafer_sort_yield=estimate(1, "ratio"),
            performance_bin_share=estimate(1, "ratio"),
        ),
        hbm=HbmStackFlow(
            wafer=hbm_wafer,
            known_good_die_yield=estimate(1, "ratio"),
            memory_dies_per_stack=estimate(8, "die/stack"),
            stack_assembly_yield=estimate(1, "ratio"),
            stack_final_test_yield=estimate(1, "ratio"),
            stack_capacity_gb=estimate(24, "GB/stack"),
            stacks_per_accelerator=estimate(8, "stack/accelerator"),
        ),
        package=PackageAssemblyFlow(
            assembly_starts=estimate(100, "package"),
            assembly_yield=estimate(1, "ratio"),
            logic_dies_per_accelerator=estimate(2, "die/accelerator"),
            accelerators_per_system=estimate(2, "accelerator/system"),
        ),
    )


def with_logic_wafer_starts(
    scenario: ManufacturingScenario,
    value: float,
) -> ManufacturingScenario:
    wafer = replace(scenario.logic.wafer, wafer_starts=estimate(value, "wafer"))
    return replace(scenario, logic=replace(scenario.logic, wafer=wafer))
