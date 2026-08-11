"""Self-contained releases for linked manufacturing-to-deployment scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .chain_linker import LinkedChainCase
from .release import _csv, _json, _sha256, build_release_documents


LINKED_CHAIN_RELEASE_FORMAT = "ai-supply-linked-chain-release.v1"
LINKED_CHAIN_DRAW_RELEASE_FORMAT = "ai-supply-linked-chain-release.v2"


def build_linked_chain_release_documents(case: LinkedChainCase) -> dict[str, str]:
    chain_draws: list[dict[str, float]] = []
    draw_link = bool(case.constraint_capacity_draws)
    documents = build_release_documents(
        case.scenario,
        source_document=case.scenario_document,
        constraint_capacity_draws=case.constraint_capacity_draws,
        output_draws=chain_draws if draw_link else None,
    )
    documents.pop("manifest.json")
    documents["base_scenario.json"] = case.base_document
    documents["link_recipe.json"] = case.recipe_document
    documents["manufacturing_result.json"] = case.source_documents["manufacturing"]
    documents["datacenter_operational_result.json"] = case.source_documents[
        "datacenter_operational"
    ]
    if "system_assembly" in case.source_documents:
        documents["system_assembly_result.json"] = case.source_documents[
            "system_assembly"
        ]
    source_draw_names = {
        "manufacturing": "manufacturing_draws.csv",
        "system_assembly": "system_assembly_draws.csv",
        "datacenter_operational": "datacenter_operational_draws.csv",
    }
    for key, document in case.source_draw_documents.items():
        documents[source_draw_names[key]] = document
    chain_draw_fields = list(chain_draws[0]) if chain_draws else []
    if draw_link:
        documents["chain_draws.csv"] = _csv(chain_draw_fields, chain_draws)
    documents["link_lineage.json"] = _json(case.lineage)
    if draw_link:
        documents["README.md"] = (
            f"# {case.scenario.name}\n\n"
            f"Quarter: `{case.scenario.quarter}`. As of: `{case.scenario.as_of_date}`. "
            f"Monte Carlo draws: `{case.scenario.samples:,}`.\n\n"
            "**This is a linked illustrative run. Frozen manufacturing, system-assembly, "
            "and site-operational results, the site-allocation share, and remaining chain "
            "constraints contain synthetic inputs. It is not a global production estimate "
            "or an estimate of actual shipments or deployments.**\n\n"
            "Open `dashboard.html` first. Every source result and capacity-draw file is "
            "preserved byte for byte. `chain_draws.csv` retains the resulting stage and "
            "constraint draws. `link_lineage.json` records exact coverage replacement and "
            "the deterministic independent permutation used across source engines.\n"
        )
    elif "system_assembly" in case.source_documents:
        documents["README.md"] = (
            f"# {case.scenario.name}\n\n"
            f"Quarter: `{case.scenario.quarter}`. As of: `{case.scenario.as_of_date}`. "
            f"Monte Carlo draws: `{case.scenario.samples:,}`.\n\n"
            "**This is a linked illustrative run. Frozen manufacturing, system-assembly, "
            "and site-operational results, the site-allocation share, and remaining chain "
            "constraints contain synthetic inputs. It is not a global production estimate "
            "or an estimate of actual shipments or deployments.**\n\n"
            "Open `dashboard.html` first. `scenario.json` is the generated linked scenario. "
            "The base scenario, link recipe, and all three source results are preserved byte "
            "for byte; `link_lineage.json` records every replacement, coverage guard, and "
            "quantile-to-triangular distribution mapping.\n"
        )
    else:
        documents["README.md"] = (
            f"# {case.scenario.name}\n\n"
            f"Quarter: `{case.scenario.quarter}`. As of: `{case.scenario.as_of_date}`. "
            f"Monte Carlo draws: `{case.scenario.samples:,}`.\n\n"
            "**This is a linked illustrative run. Frozen manufacturing and site-operational "
            "results, the site-allocation share, and remaining chain constraints contain "
            "synthetic inputs. It is not a global production estimate or an estimate of "
            "actual Abilene shipments or deployments.**\n\n"
            "Open `dashboard.html` first. `scenario.json` is the generated linked scenario. "
            "The base scenario, link recipe, and both source results are preserved byte for "
            "byte; `link_lineage.json` records every replacement and the quantile-to-triangular "
            "distribution mapping. Standard result, input, evidence, bottleneck, allocation, "
            "and supplier CSVs retain the complete audit surface.\n"
        )
    sources = case.lineage["sources"]
    manifest = {
        "format": (
            LINKED_CHAIN_DRAW_RELEASE_FORMAT
            if draw_link
            else LINKED_CHAIN_RELEASE_FORMAT
        ),
        "scenario_id": case.scenario.id,
        "quarter": case.scenario.quarter,
        "as_of_date": case.scenario.as_of_date,
        "recorded_at": case.scenario.recorded_at,
        "synthetic": case.scenario.synthetic,
        "base_scenario_sha256": case.lineage["base_scenario"]["sha256"],
        "source_result_sha256": {
            key: value["sha256"] for key, value in sources.items()
        },
        "files": {
            name: {
                "bytes": len(text.encode("utf-8")),
                "sha256": _sha256(text),
            }
            for name, text in sorted(documents.items())
        },
    }
    if draw_link:
        manifest["source_capacity_draws_sha256"] = {
            key: value["capacity_draws_sha256"]
            for key, value in sources.items()
        }
        manifest["chain_draw_count"] = len(chain_draws)
        manifest["chain_draw_fields"] = chain_draw_fields
    documents["manifest.json"] = _json(manifest)
    return documents


def write_linked_chain_release(
    case: LinkedChainCase,
    output_dir: str | Path,
) -> dict[str, Any]:
    destination = Path(output_dir)
    documents = build_linked_chain_release_documents(case)
    if destination.exists() and not destination.is_dir():
        raise ValueError("output_dir must be a directory")
    if destination.exists() and any(destination.iterdir()):
        existing = {
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        }
        if existing != set(documents) or any(
            (destination / name).read_bytes() != text.encode("utf-8")
            for name, text in documents.items()
        ):
            raise ValueError("output_dir contains a different or incomplete release")
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, text in documents.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    return {
        "output_dir": str(destination.resolve()),
        **json.loads(documents["manifest.json"]),
    }
