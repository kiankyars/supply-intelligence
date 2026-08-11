from __future__ import annotations

from supply_intelligence.datacenter_operational_models import (
    DatacenterOperationalCase,
    DatacenterOperationalScenario,
    GrossPowerReference,
    PowerDeductions,
)
from supply_intelligence.models import Evidence, EvidenceKind, EstimatePosture

from tests.helpers import estimate


def deterministic_operational_case() -> DatacenterOperationalCase:
    gross_evidence = Evidence(
        id="evidence:gross",
        kind=EvidenceKind.THIRD_PARTY_RESEARCH,
        title="Gross power fixture",
        source_url="https://example.com/gross-power",
        publisher="Fixture publisher",
        retrieved_at="2026-07-17T12:00:00Z",
    )
    local_evidence = Evidence(
        id="evidence:test",
        kind=EvidenceKind.SYNTHETIC,
        title="Operational fixture",
        source_url="urn:synthetic:operational-fixture",
        publisher="Test suite",
        retrieved_at="2026-07-17T12:00:00Z",
    )
    reference = GrossPowerReference(
        sha256="a" * 64,
        expected_entity_ids=("site-a",),
        expected_datacenter_manifest_sha256="b" * 64,
    )
    scenario = DatacenterOperationalScenario(
        id="datacenter-operational:test",
        name="Deterministic operational test",
        quarter="2026-Q3",
        as_of_date="2026-07-17",
        recorded_at="2026-07-17T12:00:00Z",
        synthetic=True,
        samples=100,
        seed=31,
        scope_description="One deterministic test site.",
        gross_power=reference,
        deductions=PowerDeductions(
            current_critical_it_load=estimate(20, "MW"),
            contracted_reservations=estimate(10, "MW"),
            other_platform_commitments=estimate(5, "MW"),
            rack_incompatible_capacity=estimate(5, "MW"),
            non_overlap_rationale=(
                "Each fixture deduction represents a distinct mutually exclusive pool."
            ),
        ),
        target_platform_share=estimate(0.5, "ratio"),
        rack_it_load=estimate(0.1, "MW/rack"),
        commissioning_slots=estimate(200, "rack"),
        commissioning_completion_ratio=estimate(0.5, "ratio"),
        evidence=(local_evidence,),
    )
    return DatacenterOperationalCase(
        scenario=scenario,
        gross_estimate=estimate(
            100,
            "MW",
            evidence_id="evidence:gross",
            posture=EstimatePosture.MODELED,
        ),
        gross_evidence=(gross_evidence,),
        sites=(
            {
                "entity_id": "site-a",
                "name": "Fixture site",
                "capacity": {"low": 100, "base": 100, "high": 100},
            },
        ),
        gross_lineage={
            "capacity_semantics": "gross_site_critical_it_envelope",
            "availability_status": "not_net_incremental_capacity",
        },
        gross_import_sha256="a" * 64,
    )
