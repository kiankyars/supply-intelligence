"""Build the checked synthetic manufacturing calibration scorecard dataset."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


AS_OF = "2026-07-19"
RECORDED_AT = "2026-07-19T23:15:00Z"
ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "releases"
    / "2026-07-17-blackwell-manufacturing-illustrative"
    / "result.json"
)
OUTPUT = (
    Path(__file__).with_name("calibration")
    / "blackwell-manufacturing-calibration-synthetic-2026-07-19.json"
)


METRICS = [
    ("logic_gross_dies", "logic_conversion", 0.92, "at_least", 0.95),
    ("logic_known_good_dies", "logic_conversion", 1.08, "at_least", 1.00),
    ("logic_binned_dies", "logic_conversion", 0.74, "at_least", 0.80),
    ("hbm_good_stacks", "memory_output", 1.12, "at_least", 1.10),
    (
        "finished_accelerator_packages",
        "packaging_output",
        0.95,
        "at_most",
        0.90,
    ),
    (
        "complete_system_equivalents",
        "system_conversion",
        1.25,
        "at_least",
        1.20,
    ),
]


def main() -> None:
    forecast = json.loads(SOURCE.read_text(encoding="utf-8"))
    outcomes = []
    for metric, metric_class, actual_multiplier, operator, threshold_multiplier in METRICS:
        distribution = forecast["conversion_outputs"][metric]
        unit = {
            "logic_gross_dies": "die",
            "logic_known_good_dies": "die",
            "logic_binned_dies": "die",
            "hbm_good_stacks": "stack",
            "finished_accelerator_packages": "package",
            "complete_system_equivalents": "system",
        }[metric]
        outcomes.append(
            {
                "id": f"synthetic-{metric.replace('_', '-')}",
                "forecast_id": "blackwell-manufacturing-2026q3-v1",
                "metric_class": metric_class,
                "forecast_metric": metric,
                "period": forecast["scenario"]["quarter"],
                "actual_value": distribution["p50"] * actual_multiplier,
                "unit": unit,
                "posture": "synthetic",
                "observed_at": AS_OF,
                "source_family": "synthetic-calibration-fixture",
                "evidence_ids": ["synthetic:blackwell-calibration-outcomes"],
                "methodology": (
                    f"Synthetic outcome set to {actual_multiplier:.2f} times the "
                    "frozen forecast P50 solely to exercise calibration scoring."
                ),
                "revision_risk": (
                    "Not a realized production observation; replace the full record "
                    "with a dated, scope-matched outcome before interpretation."
                ),
                "event": {
                    "operator": operator,
                    "threshold": distribution["p50"] * threshold_multiplier,
                    "unit": unit,
                },
            }
        )
    dataset = {
        "format": "ai-supply-calibration-dataset.v1",
        "id": "blackwell-manufacturing-synthetic-scorecard-2026-07-19",
        "as_of_date": AS_OF,
        "recorded_at": RECORDED_AT,
        "synthetic": True,
        "minimum_group_size": 10,
        "forecasts": [
            {
                "id": "blackwell-manufacturing-2026q3-v1",
                "path": SOURCE.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                "format": forecast["format"],
                "scenario_id": forecast["scenario"]["id"],
            }
        ],
        "evidence": [
            {
                "id": "synthetic:blackwell-calibration-outcomes",
                "kind": "synthetic",
                "title": "Synthetic Blackwell calibration outcome fixtures",
                "source_url": "urn:synthetic:blackwell-calibration-outcomes",
                "publisher": "AI Supply Intelligence",
                "published_at": None,
                "retrieved_at": "2026-07-19T23:00:00Z",
                "source_family": "synthetic-calibration-fixture",
                "license": "Internal demonstration",
                "excerpt": (
                    "Six deliberately varied synthetic outcomes; not historical "
                    "production, shipment, or deployment observations."
                ),
                "content_hash": None,
            }
        ],
        "outcomes": outcomes,
        "notes": (
            "Contract fixture for coverage, bias, pinball, Brier, grouping, and "
            "replay tests. It must never be presented as measured Blackwell output."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(dataset, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
