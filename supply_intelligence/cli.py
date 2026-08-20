"""Command-line entry point for scenario validation and reconciliation."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from .alert_release import write_revision_alert_release
from .atlas_adapter import load_atlas_capacity, load_atlas_selection
from .blackwell_pulse_release import write_blackwell_pulse_release
from .chain_link_release import write_linked_chain_release
from .chain_linker import load_linked_chain_case
from .claim_cycle import run_claim_cycle
from .claim_ledger import (
    diff_claim_snapshots,
    ingest_claim_pack,
    query_claim_snapshot,
)
from .calibration import load_calibration_dataset
from .calibration_release import write_calibration_release
from .datacenter_adapter import load_datacenter_power, load_datacenter_selection
from .datacenter_operational_loader import load_datacenter_operational_case
from .datacenter_operational_release import write_datacenter_operational_release
from .earnings_loader import load_earnings_case
from .earnings_release import write_earnings_release
from .forecast_registry import (
    evaluate_forecast_registry_maturity,
    load_forecast_registry,
)
from .forecast_registry_release import write_forecast_registry_release
from .forecast_outcome_review import load_forecast_outcome_review
from .forecast_outcome_review_release import write_forecast_outcome_review_release
from .guidance_backtest import load_guidance_backtest
from .guidance_backtest_release import write_guidance_backtest_release
from .hbm_manufacturing_link import load_hbm_manufacturing_link_case
from .hbm_manufacturing_release import write_hbm_manufacturing_link_release
from .hbm_supplier_loader import load_hbm_supplier_scenario
from .hbm_supplier_release import write_hbm_supplier_release
from .loader import load_scenario
from .manufacturing_loader import load_manufacturing
from .manufacturing_claim_gate import assess_manufacturing_claim
from .manufacturing_evidence_coverage import (
    write_manufacturing_evidence_coverage_release,
)
from .manufacturing_release import write_manufacturing_release
from .manufacturing_revision import (
    load_manufacturing_revision,
    write_manufacturing_revision_release,
)
from .notifications import (
    acknowledge_claim_notification,
    deliver_claim_notifications_to_jsonl,
    enqueue_claim_notifications,
    list_claim_notifications,
)
from .portfolio_loader import load_portfolio
from .portfolio_release import write_portfolio_release
from .release import write_release
from .sec_filings_adapter import (
    fetch_sec_filings_release,
    load_local_sec_sources,
    load_sec_watch,
    write_sec_filings_release,
)
from .sec_filing_documents import (
    fetch_sec_filing_documents_release,
    load_local_sec_filing_documents,
    load_sec_filing_document_selection,
    resolve_sec_filing_document_selection,
    write_sec_filing_documents_release,
)
from .sec_filing_text_index import (
    load_sec_filing_text_recipe,
    write_sec_filing_text_release,
)
from .sec_reviewed_claims import (
    load_sec_reviewed_claims_recipe,
    write_sec_reviewed_claims_release,
)
from .system_assembly_loader import load_system_assembly_scenario
from .system_assembly_release import write_system_assembly_release
from .upstream_release import (
    fetch_and_load_locked_release,
    load_upstream_release_lock,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-supply")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate an auditable scenario pack")
    validate.add_argument("--scenario", required=True, type=Path)

    reconcile = subparsers.add_parser(
        "reconcile", help="reconcile and export an audit dashboard release"
    )
    reconcile.add_argument("--scenario", required=True, type=Path)
    reconcile.add_argument("--output-dir", required=True, type=Path)

    validate_portfolio = subparsers.add_parser(
        "validate-portfolio", help="validate a shared-resource portfolio pack"
    )
    validate_portfolio.add_argument("--portfolio", required=True, type=Path)

    reconcile_portfolio = subparsers.add_parser(
        "reconcile-portfolio",
        help="allocate shared resources and export a portfolio dashboard",
    )
    reconcile_portfolio.add_argument("--portfolio", required=True, type=Path)
    reconcile_portfolio.add_argument("--output-dir", required=True, type=Path)

    validate_manufacturing = subparsers.add_parser(
        "validate-manufacturing",
        help="validate a wafer-to-package manufacturing scenario",
    )
    validate_manufacturing.add_argument("--scenario", required=True, type=Path)

    reconcile_manufacturing = subparsers.add_parser(
        "reconcile-manufacturing",
        help="convert wafer and HBM inputs and export a manufacturing dashboard",
    )
    reconcile_manufacturing.add_argument("--scenario", required=True, type=Path)
    reconcile_manufacturing.add_argument("--output-dir", required=True, type=Path)

    validate_hbm_suppliers = subparsers.add_parser(
        "validate-hbm-suppliers",
        help="validate non-overlapping supplier HBM capacity and allocation scopes",
    )
    validate_hbm_suppliers.add_argument("--scenario", required=True, type=Path)
    validate_hbm_suppliers.add_argument("--source-root", required=True, type=Path)

    reconcile_hbm_suppliers = subparsers.add_parser(
        "reconcile-hbm-suppliers",
        help="aggregate supplier HBM stacks and export an allocation dashboard",
    )
    reconcile_hbm_suppliers.add_argument("--scenario", required=True, type=Path)
    reconcile_hbm_suppliers.add_argument("--source-root", required=True, type=Path)
    reconcile_hbm_suppliers.add_argument("--output-dir", required=True, type=Path)
    reconcile_hbm_suppliers.add_argument(
        "--include-capacity-draws",
        action="store_true",
        help="preserve every sampled supplier and aggregate capacity draw",
    )

    for command, help_text in (
        (
            "validate-system-assembly",
            "validate non-overlapping ODM and rack-component capacity scopes",
        ),
        (
            "reconcile-system-assembly",
            "reconcile ODM tray, rack, and component capacity into complete racks",
        ),
    ):
        assembly = subparsers.add_parser(command, help=help_text)
        assembly.add_argument("--scenario", required=True, type=Path)
        assembly.add_argument("--source-root", required=True, type=Path)
        if command == "reconcile-system-assembly":
            assembly.add_argument("--output-dir", required=True, type=Path)

    for command, help_text in (
        (
            "validate-hbm-manufacturing-link",
            "validate replacement of aggregate HBM with a frozen supplier result",
        ),
        (
            "reconcile-hbm-manufacturing-link",
            "reconcile manufacturing with a frozen supplier-allocated HBM pool",
        ),
    ):
        hbm_link = subparsers.add_parser(command, help=help_text)
        hbm_link.add_argument(
            "--manufacturing-scenario",
            required=True,
            type=Path,
        )
        hbm_link.add_argument("--hbm-result", required=True, type=Path)
        hbm_link.add_argument("--link-recipe", required=True, type=Path)
        hbm_link.add_argument("--hbm-capacity-draws", type=Path)
        if command == "reconcile-hbm-manufacturing-link":
            hbm_link.add_argument("--output-dir", required=True, type=Path)
            hbm_link.add_argument(
                "--include-output-draws",
                action="store_true",
                help="preserve every linked manufacturing output draw",
            )

    filing_text = subparsers.add_parser(
        "build-sec-filing-text-index",
        help="index visible filing text for configured literal evidence terms",
    )
    filing_text.add_argument("--documents-release", required=True, type=Path)
    filing_text.add_argument("--recipe", required=True, type=Path)
    filing_text.add_argument("--output-dir", required=True, type=Path)

    reviewed_claims = subparsers.add_parser(
        "build-sec-reviewed-claims",
        help="author ledger-ready claims pinned to exact normalized filing text",
    )
    reviewed_claims.add_argument("--text-release", required=True, type=Path)
    reviewed_claims.add_argument("--recipe", required=True, type=Path)
    reviewed_claims.add_argument("--output-dir", required=True, type=Path)

    for command, help_text in (
        (
            "build-sec-filing-documents-release",
            "preserve captured primary filing documents for reviewed extraction",
        ),
        (
            "fetch-sec-filing-documents",
            "fetch selected SEC primary documents into an immutable review release",
        ),
    ):
        filing_documents = subparsers.add_parser(command, help=help_text)
        filing_documents.add_argument("--filings-release", required=True, type=Path)
        filing_documents.add_argument("--selection", required=True, type=Path)
        filing_documents.add_argument("--retrieved-at", required=True)
        filing_documents.add_argument("--output-dir", required=True, type=Path)
        if command == "build-sec-filing-documents-release":
            filing_documents.add_argument("--source-dir", required=True, type=Path)
        else:
            filing_documents.add_argument(
                "--user-agent",
                required=True,
                help="SEC-compliant organization and contact email",
            )

    for command, help_text in (
        ("validate-earnings", "validate a frozen physical-to-company earnings bridge"),
        (
            "reconcile-earnings",
            "build supplier earnings, consensus discrepancies, and a research ranking",
        ),
    ):
        earnings = subparsers.add_parser(command, help=help_text)
        earnings.add_argument("--source-result", required=True, type=Path)
        earnings.add_argument("--scenario", required=True, type=Path)
        if command == "reconcile-earnings":
            earnings.add_argument("--output-dir", required=True, type=Path)

    for command, help_text in (
        (
            "validate-forecast-outcome-review",
            "validate complete post-period dispositions for a frozen forecast registry",
        ),
        (
            "build-forecast-outcome-review",
            "export observed, mismatched, pending, and unobservable outcome dispositions",
        ),
    ):
        outcome_review = subparsers.add_parser(command, help=help_text)
        outcome_review.add_argument("--review", required=True, type=Path)
        outcome_review.add_argument("--source-root", required=True, type=Path)
        if command == "build-forecast-outcome-review":
            outcome_review.add_argument("--output-dir", required=True, type=Path)

    for command, help_text in (
        (
            "validate-forecast-registry",
            "validate a pre-outcome native forecast vintage and its raw draws",
        ),
        (
            "build-forecast-registry",
            "freeze native forecasts, maturity contracts, and raw draws",
        ),
    ):
        forecast_registry = subparsers.add_parser(command, help=help_text)
        forecast_registry.add_argument("--registry", required=True, type=Path)
        forecast_registry.add_argument("--source-root", required=True, type=Path)
        if command == "build-forecast-registry":
            forecast_registry.add_argument("--output-dir", required=True, type=Path)
        else:
            forecast_registry.add_argument("--status-as-of")

    for command, help_text in (
        (
            "validate-calibration",
            "validate frozen forecast vintages and realized-outcome definitions",
        ),
        (
            "build-calibration-scorecard",
            "score frozen forecasts and export a replayable calibration release",
        ),
    ):
        calibration = subparsers.add_parser(command, help=help_text)
        calibration.add_argument("--dataset", required=True, type=Path)
        calibration.add_argument("--source-root", required=True, type=Path)
        if command == "build-calibration-scorecard":
            calibration.add_argument("--output-dir", required=True, type=Path)

    validate_datacenter_operational = subparsers.add_parser(
        "validate-datacenter-operational",
        help="validate a hash-pinned gross-to-net power and commissioning scenario",
    )
    validate_datacenter_operational.add_argument(
        "--gross-import",
        required=True,
        type=Path,
    )
    validate_datacenter_operational.add_argument(
        "--scenario",
        required=True,
        type=Path,
    )

    reconcile_datacenter_operational = subparsers.add_parser(
        "reconcile-datacenter-operational",
        help="convert gross site power into operational target-platform racks",
    )
    reconcile_datacenter_operational.add_argument(
        "--gross-import",
        required=True,
        type=Path,
    )
    reconcile_datacenter_operational.add_argument(
        "--scenario",
        required=True,
        type=Path,
    )
    reconcile_datacenter_operational.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )
    reconcile_datacenter_operational.add_argument(
        "--include-capacity-draws",
        action="store_true",
        help="preserve every gross-to-net operational draw",
    )

    for command, help_text in (
        (
            "validate-linked-chain",
            "validate frozen manufacturing, assembly, and operational links",
        ),
        (
            "reconcile-linked-chain",
            "reconcile a scoped chain using frozen source results",
        ),
    ):
        linked = subparsers.add_parser(command, help=help_text)
        linked.add_argument("--base-scenario", required=True, type=Path)
        linked.add_argument("--link-recipe", required=True, type=Path)
        linked.add_argument("--manufacturing-result", required=True, type=Path)
        linked.add_argument("--operational-result", required=True, type=Path)
        linked.add_argument("--assembly-result", type=Path)
        linked.add_argument("--manufacturing-draws", type=Path)
        linked.add_argument("--operational-draws", type=Path)
        linked.add_argument("--assembly-draws", type=Path)
        if command == "reconcile-linked-chain":
            linked.add_argument("--output-dir", required=True, type=Path)

    compare_releases = subparsers.add_parser(
        "compare-releases",
        help="compare two frozen result files and export deterministic alerts",
    )
    compare_releases.add_argument("--previous-result", required=True, type=Path)
    compare_releases.add_argument("--current-result", required=True, type=Path)
    compare_releases.add_argument("--output-dir", required=True, type=Path)
    compare_releases.add_argument(
        "--output-relative-threshold",
        type=float,
        default=0.10,
    )
    compare_releases.add_argument(
        "--bottleneck-probability-threshold",
        type=float,
        default=0.15,
    )

    ingest_claims = subparsers.add_parser(
        "ingest-claims",
        help="append a hash-verified source and claim pack to a SQLite ledger",
    )
    ingest_claims.add_argument("--database", required=True, type=Path)
    ingest_claims.add_argument("--pack", required=True, type=Path)

    query_claims = subparsers.add_parser(
        "query-claims",
        help="query claims valid on a date and known by a transaction-time cutoff",
    )
    query_claims.add_argument("--database", required=True, type=Path)
    query_claims.add_argument("--valid-at", required=True)
    query_claims.add_argument("--known-at", required=True)
    query_claims.add_argument("--claim-key")

    diff_claims = subparsers.add_parser(
        "diff-claims",
        help="compare two transaction-time views of the same valid-date claim set",
    )
    diff_claims.add_argument("--database", required=True, type=Path)
    diff_claims.add_argument("--valid-at", required=True)
    diff_claims.add_argument("--previous-known-at", required=True)
    diff_claims.add_argument("--current-known-at", required=True)

    enqueue_notifications = subparsers.add_parser(
        "enqueue-claim-notifications",
        help="enqueue a claim-diff file into a durable local notification outbox",
    )
    enqueue_notifications.add_argument("--outbox", required=True, type=Path)
    enqueue_notifications.add_argument("--diff", required=True, type=Path)
    enqueue_notifications.add_argument("--created-at", required=True)

    list_notifications = subparsers.add_parser(
        "list-claim-notifications",
        help="list durable claim notifications and acknowledgement state",
    )
    list_notifications.add_argument("--outbox", required=True, type=Path)
    list_notifications.add_argument(
        "--status",
        choices=("pending", "delivered", "acknowledged"),
    )

    deliver_notifications = subparsers.add_parser(
        "deliver-claim-notifications",
        help="append pending claim notifications to a local JSONL sink",
    )
    deliver_notifications.add_argument("--outbox", required=True, type=Path)
    deliver_notifications.add_argument("--sink", required=True, type=Path)
    deliver_notifications.add_argument("--delivered-at", required=True)
    deliver_notifications.add_argument("--limit", type=int, default=100)

    acknowledge_notification = subparsers.add_parser(
        "ack-claim-notification",
        help="acknowledge one durable claim notification",
    )
    acknowledge_notification.add_argument("--outbox", required=True, type=Path)
    acknowledge_notification.add_argument("--event-id", required=True)
    acknowledge_notification.add_argument("--acknowledged-at", required=True)
    acknowledge_notification.add_argument("--note")

    run_cycle = subparsers.add_parser(
        "run-claim-cycle",
        help="run one interval-gated ingest, snapshot, diff, and notification cycle",
    )
    run_cycle.add_argument("--job", required=True, type=Path)
    run_cycle.add_argument("--database", required=True, type=Path)
    run_cycle.add_argument("--outbox", required=True, type=Path)
    run_cycle.add_argument("--state-dir", required=True, type=Path)
    run_cycle.add_argument("--release-root", required=True, type=Path)
    run_cycle.add_argument("--run-at", required=True)
    run_cycle.add_argument("--force", action="store_true")
    run_cycle.add_argument("--notification-sink", type=Path)

    for command, help_text in (
        (
            "build-sec-filings-release",
            "normalize captured SEC submissions into filing events and a claim pack",
        ),
        (
            "fetch-sec-filings",
            "fetch official SEC submissions and build a filing-event release",
        ),
    ):
        sec_filings = subparsers.add_parser(command, help=help_text)
        sec_filings.add_argument("--watch", required=True, type=Path)
        sec_filings.add_argument("--retrieved-at", required=True)
        sec_filings.add_argument("--output-dir", required=True, type=Path)
        sec_filings.add_argument("--previous-release", type=Path)
        if command == "build-sec-filings-release":
            sec_filings.add_argument("--source-dir", required=True, type=Path)
        else:
            sec_filings.add_argument(
                "--user-agent",
                required=True,
                help="SEC-compliant organization and contact email",
            )

    assess_manufacturing = subparsers.add_parser(
        "assess-manufacturing-claim",
        help="assess a frozen ledger claim against a manufacturing input scope",
    )
    assess_manufacturing.add_argument("--snapshot", required=True, type=Path)
    assess_manufacturing.add_argument("--selection", required=True, type=Path)

    build_manufacturing_coverage = subparsers.add_parser(
        "build-manufacturing-evidence-coverage",
        help="join a frozen manufacturing research queue to claim-scope decisions",
    )
    build_manufacturing_coverage.add_argument("--recipe", required=True, type=Path)
    build_manufacturing_coverage.add_argument(
        "--source-root",
        required=True,
        type=Path,
    )
    build_manufacturing_coverage.add_argument(
        "--output-dir",
        required=True,
        type=Path,
    )

    for command, help_text in (
        (
            "validate-manufacturing-revision",
            "validate exact-scope replacements against a frozen manufacturing scenario",
        ),
        (
            "build-manufacturing-revision",
            "replace gated synthetic inputs and export a replay-safe manufacturing release",
        ),
    ):
        revision = subparsers.add_parser(command, help=help_text)
        revision.add_argument("--recipe", required=True, type=Path)
        revision.add_argument("--source-root", required=True, type=Path)
        if command == "build-manufacturing-revision":
            revision.add_argument("--output-dir", required=True, type=Path)

    for command, help_text in (
        (
            "validate-guidance-backtest",
            "validate pre-outcome company guidance against a later reported result",
        ),
        (
            "build-guidance-backtest",
            "score a reconstructed external guidance benchmark and export its audit release",
        ),
    ):
        backtest = subparsers.add_parser(command, help=help_text)
        backtest.add_argument("--case", required=True, type=Path)
        backtest.add_argument("--source-root", required=True, type=Path)
        if command == "build-guidance-backtest":
            backtest.add_argument("--output-dir", required=True, type=Path)

    import_atlas = subparsers.add_parser(
        "import-atlas-capacity",
        help="import a pinned quarterly capacity slice from a Semiconductor Atlas release",
    )
    import_atlas.add_argument("--release-dir", required=True, type=Path)
    import_atlas.add_argument("--selection", required=True, type=Path)

    import_datacenter = subparsers.add_parser(
        "import-datacenter-power",
        help="import a pinned gross critical IT power envelope from a Data Center Atlas release",
    )
    import_datacenter.add_argument("--release-dir", required=True, type=Path)
    import_datacenter.add_argument("--selection", required=True, type=Path)

    fetch_upstreams = subparsers.add_parser(
        "fetch-upstream-releases",
        help="fetch and verify immutable Atlas release assets into a content-addressed cache",
    )
    fetch_upstreams.add_argument("--lockfile", required=True, type=Path)
    fetch_upstreams.add_argument("--cache-dir", required=True, type=Path)

    build_pulse = subparsers.add_parser(
        "build-blackwell-pulse",
        help="build an offline, evidence-gated 2026-Q4 Blackwell weekly pulse",
    )
    build_pulse.add_argument("--config", required=True, type=Path)
    build_pulse.add_argument("--lockfile", required=True, type=Path)
    build_pulse.add_argument("--cache-dir", required=True, type=Path)
    build_pulse.add_argument("--synthetic-audit", required=True, type=Path)
    build_pulse.add_argument("--output-dir", required=True, type=Path)
    return parser


def _dump(value: object, *, stream: object | None = None) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False),
        file=stream or sys.stdout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "fetch-upstream-releases":
            lock = load_upstream_release_lock(args.lockfile)
            verified = [
                fetch_and_load_locked_release(entry, args.cache_dir)
                for entry in lock.upstreams
            ]
            _dump(
                {
                    "valid": True,
                    "lock_sha256": lock.sha256,
                    "verified_releases": [
                        {
                            "upstream_id": release.upstream_id,
                            "repository": release.repository,
                            "release_tag": release.release_tag,
                            "asset_sha256": release.entry.asset.sha256,
                            "manifest_sha256": release.manifest_sha256,
                            "claims_sha256": release.claims_sha256,
                            "manifest_as_of_date": release.manifest["as_of_date"],
                            "manifest_recorded_at": release.manifest["recorded_at"],
                            "comparison": release.manifest["comparison"],
                            "content_address": f"sha256:{release.entry.asset.sha256}",
                        }
                        for release in verified
                    ],
                }
            )
            return 0
        if args.command == "build-blackwell-pulse":
            _dump(
                write_blackwell_pulse_release(
                    args.config,
                    args.lockfile,
                    args.cache_dir,
                    args.synthetic_audit,
                    args.output_dir,
                )
            )
            return 0
        if args.command == "ingest-claims":
            _dump(ingest_claim_pack(args.database, args.pack))
            return 0
        if args.command == "query-claims":
            _dump(
                query_claim_snapshot(
                    args.database,
                    valid_at=args.valid_at,
                    known_at=args.known_at,
                    claim_key=args.claim_key,
                )
            )
            return 0
        if args.command == "diff-claims":
            _dump(
                diff_claim_snapshots(
                    args.database,
                    valid_at=args.valid_at,
                    previous_known_at=args.previous_known_at,
                    current_known_at=args.current_known_at,
                )
            )
            return 0
        if args.command == "enqueue-claim-notifications":
            _dump(
                enqueue_claim_notifications(
                    args.outbox,
                    json.loads(args.diff.read_text(encoding="utf-8")),
                    created_at=args.created_at,
                )
            )
            return 0
        if args.command == "list-claim-notifications":
            _dump(list_claim_notifications(args.outbox, status=args.status))
            return 0
        if args.command == "deliver-claim-notifications":
            _dump(
                deliver_claim_notifications_to_jsonl(
                    args.outbox,
                    args.sink,
                    delivered_at=args.delivered_at,
                    limit=args.limit,
                )
            )
            return 0
        if args.command == "ack-claim-notification":
            _dump(
                acknowledge_claim_notification(
                    args.outbox,
                    args.event_id,
                    acknowledged_at=args.acknowledged_at,
                    note=args.note,
                )
            )
            return 0
        if args.command == "run-claim-cycle":
            _dump(
                run_claim_cycle(
                    args.job,
                    database=args.database,
                    outbox=args.outbox,
                    state_dir=args.state_dir,
                    release_root=args.release_root,
                    run_at=args.run_at,
                    force=args.force,
                    notification_sink=args.notification_sink,
                )
            )
            return 0
        if args.command in {
            "build-sec-filings-release",
            "fetch-sec-filings",
        }:
            watch = load_sec_watch(args.watch)
            if args.command == "build-sec-filings-release":
                sources = load_local_sec_sources(watch, args.source_dir)
                _dump(
                    write_sec_filings_release(
                        watch,
                        sources,
                        args.output_dir,
                        retrieved_at=args.retrieved_at,
                        previous_release=args.previous_release,
                    )
                )
                return 0
            _dump(
                fetch_sec_filings_release(
                    watch,
                    args.output_dir,
                    retrieved_at=args.retrieved_at,
                    user_agent=args.user_agent,
                    previous_release=args.previous_release,
                )
            )
            return 0
        if args.command in {
            "build-sec-filing-documents-release",
            "fetch-sec-filing-documents",
        }:
            selection = load_sec_filing_document_selection(args.selection)
            if args.command == "build-sec-filing-documents-release":
                selected, _ = resolve_sec_filing_document_selection(
                    args.filings_release,
                    selection,
                )
                documents = load_local_sec_filing_documents(
                    selected,
                    args.source_dir,
                )
                _dump(
                    write_sec_filing_documents_release(
                        args.filings_release,
                        selection,
                        documents,
                        args.output_dir,
                        retrieved_at=args.retrieved_at,
                    )
                )
                return 0
            _dump(
                fetch_sec_filing_documents_release(
                    args.filings_release,
                    selection,
                    args.output_dir,
                    retrieved_at=args.retrieved_at,
                    user_agent=args.user_agent,
                )
            )
            return 0
        if args.command == "build-sec-filing-text-index":
            recipe = load_sec_filing_text_recipe(args.recipe)
            _dump(
                write_sec_filing_text_release(
                    args.documents_release,
                    recipe,
                    args.output_dir,
                )
            )
            return 0
        if args.command == "build-sec-reviewed-claims":
            recipe = load_sec_reviewed_claims_recipe(args.recipe)
            _dump(
                write_sec_reviewed_claims_release(
                    args.text_release,
                    recipe,
                    args.output_dir,
                )
            )
            return 0
        if args.command == "assess-manufacturing-claim":
            _dump(assess_manufacturing_claim(args.snapshot, args.selection))
            return 0
        if args.command == "build-manufacturing-evidence-coverage":
            _dump(
                write_manufacturing_evidence_coverage_release(
                    args.recipe,
                    args.output_dir,
                    source_root=args.source_root,
                )
            )
            return 0
        if args.command in {
            "validate-manufacturing-revision",
            "build-manufacturing-revision",
        }:
            revision_case = load_manufacturing_revision(
                args.recipe,
                source_root=args.source_root,
            )
            if args.command == "validate-manufacturing-revision":
                result = revision_case["revision_result"]
                _dump(
                    {
                        "valid": True,
                        "revision_id": result["revision_id"],
                        "scenario_id": result["scenario_id"],
                        "quarter": result["quarter"],
                        "replacement_count": result["replacement_count"],
                        "remaining_synthetic_input_count": result[
                            "remaining_synthetic_input_count"
                        ],
                        "all_numeric_values_unchanged": result[
                            "all_numeric_values_unchanged"
                        ],
                        "synthetic": revision_case["scenario"].synthetic,
                    }
                )
                return 0
            _dump(
                write_manufacturing_revision_release(
                    revision_case,
                    args.output_dir,
                )
            )
            return 0
        if args.command in {
            "validate-guidance-backtest",
            "build-guidance-backtest",
        }:
            backtest_case = load_guidance_backtest(
                args.case,
                source_root=args.source_root,
            )
            if args.command == "validate-guidance-backtest":
                _dump(
                    {
                        "valid": True,
                        "case_id": backtest_case["case"]["id"],
                        "entity_id": backtest_case["case"]["entity"]["id"],
                        "period": backtest_case["case"]["period"]["label"],
                        "metric_count": len(backtest_case["metric_pairs"]),
                        "native_model_forecast": False,
                        "eligible_for_model_calibration": False,
                    }
                )
                return 0
            _dump(write_guidance_backtest_release(backtest_case, args.output_dir))
            return 0
        if args.command in {"validate-linked-chain", "reconcile-linked-chain"}:
            case = load_linked_chain_case(
                args.base_scenario,
                args.link_recipe,
                args.manufacturing_result,
                args.operational_result,
                args.assembly_result,
                manufacturing_draws_path=args.manufacturing_draws,
                operational_draws_path=args.operational_draws,
                assembly_draws_path=args.assembly_draws,
            )
            if args.command == "validate-linked-chain":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": case.scenario.id,
                        "quarter": case.scenario.quarter,
                        "constraints": len(case.scenario.constraints),
                        "links": len(case.lineage["links"]),
                        "sources": sorted(case.lineage["sources"]),
                        "market_views_preserved": case.lineage[
                            "preserve_market_views"
                        ],
                        "synthetic": case.scenario.synthetic,
                    }
                )
                return 0
            _dump(write_linked_chain_release(case, args.output_dir))
            return 0
        if args.command in {
            "validate-datacenter-operational",
            "reconcile-datacenter-operational",
        }:
            case = load_datacenter_operational_case(
                args.scenario,
                args.gross_import,
            )
            scenario = case.scenario
            if args.command == "validate-datacenter-operational":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": scenario.id,
                        "quarter": scenario.quarter,
                        "gross_import_sha256": case.gross_import_sha256,
                        "sites": len(case.sites),
                        "operational_estimates": len(
                            tuple(scenario.iter_estimates())
                        ),
                        "evidence_records": len(case.evidence),
                        "synthetic": scenario.synthetic,
                    }
                )
                return 0
            _dump(
                write_datacenter_operational_release(
                    case,
                    args.output_dir,
                    scenario_document=args.scenario.read_text(encoding="utf-8"),
                    gross_import_document=args.gross_import.read_text(
                        encoding="utf-8"
                    ),
                    include_capacity_draws=args.include_capacity_draws,
                )
            )
            return 0
        if args.command == "compare-releases":
            _dump(
                write_revision_alert_release(
                    args.previous_result,
                    args.current_result,
                    args.output_dir,
                    output_relative_threshold=args.output_relative_threshold,
                    bottleneck_probability_threshold=(
                        args.bottleneck_probability_threshold
                    ),
                )
            )
            return 0
        if args.command in {"validate-earnings", "reconcile-earnings"}:
            earnings_case = load_earnings_case(
                args.scenario,
                args.source_result,
            )
            if args.command == "validate-earnings":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": earnings_case.scenario.id,
                        "quarter": earnings_case.scenario.quarter,
                        "companies": len(earnings_case.scenario.companies),
                        "line_items": sum(
                            len(company.line_items)
                            for company in earnings_case.scenario.companies
                        ),
                        "source_result_sha256": earnings_case.source_result_sha256,
                        "source_synthetic": earnings_case.source_synthetic,
                        "synthetic": earnings_case.scenario.synthetic,
                    }
                )
                return 0
            _dump(write_earnings_release(earnings_case, args.output_dir))
            return 0
        if args.command in {
            "validate-forecast-outcome-review",
            "build-forecast-outcome-review",
        }:
            outcome_case = load_forecast_outcome_review(
                args.review,
                source_root=args.source_root,
            )
            if args.command == "validate-forecast-outcome-review":
                statuses = {}
                for disposition in outcome_case["dispositions"]:
                    status = disposition["status"]
                    statuses[status] = statuses.get(status, 0) + 1
                _dump(
                    {
                        "valid": True,
                        "review_id": outcome_case["review"]["id"],
                        "registry_id": outcome_case["registry"]["registry_id"],
                        "as_of_date": outcome_case["review"]["as_of_date"],
                        "forecasts": outcome_case["registry"]["forecast_count"],
                        "dispositions": len(outcome_case["dispositions"]),
                        "disposition_status_counts": statuses,
                        "evidence_records": len(outcome_case["evidence"]),
                        "scores": sum(
                            item["score"] is not None
                            for item in outcome_case["dispositions"]
                        ),
                        "source_synthetic": outcome_case["registry"]["synthetic"],
                    }
                )
                return 0
            _dump(
                write_forecast_outcome_review_release(
                    outcome_case, args.output_dir
                )
            )
            return 0
        if args.command in {
            "validate-forecast-registry",
            "build-forecast-registry",
        }:
            forecast_case = load_forecast_registry(
                args.registry,
                source_root=args.source_root,
            )
            if args.command == "validate-forecast-registry":
                maturity = evaluate_forecast_registry_maturity(
                    forecast_case,
                    as_of_date=(
                        args.status_as_of
                        or forecast_case["registry"]["as_of_date"]
                    ),
                )
                _dump(
                    {
                        "valid": True,
                        "registry_id": forecast_case["registry"]["id"],
                        "as_of_date": forecast_case["registry"]["as_of_date"],
                        "forecast_vintages": 1,
                        "forecasts": len(forecast_case["forecasts"]),
                        "raw_draws": forecast_case["source"]["draw_count"],
                        "status_as_of_date": maturity["status_as_of_date"],
                        "maturity_status_counts": maturity[
                            "maturity_status_counts"
                        ],
                        "native_model_forecast": True,
                        "source_synthetic": forecast_case["source"]["synthetic"],
                        "outcomes": 0,
                        "scores": 0,
                    }
                )
                return 0
            _dump(write_forecast_registry_release(forecast_case, args.output_dir))
            return 0
        if args.command in {
            "validate-calibration",
            "build-calibration-scorecard",
        }:
            calibration_case = load_calibration_dataset(
                args.dataset,
                source_root=args.source_root,
            )
            if args.command == "validate-calibration":
                _dump(
                    {
                        "valid": True,
                        "dataset_id": calibration_case["dataset"]["id"],
                        "as_of_date": calibration_case["dataset"]["as_of_date"],
                        "forecast_vintages": len(calibration_case["forecasts"]),
                        "outcomes": len(calibration_case["outcomes"]),
                        "evidence_records": len(calibration_case["evidence"]),
                        "synthetic": calibration_case["dataset"]["synthetic"],
                    }
                )
                return 0
            _dump(write_calibration_release(calibration_case, args.output_dir))
            return 0
        if args.command == "import-datacenter-power":
            selection = load_datacenter_selection(args.selection)
            _dump(load_datacenter_power(args.release_dir, selection).as_dict())
            return 0
        if args.command == "import-atlas-capacity":
            selection = load_atlas_selection(args.selection)
            _dump(load_atlas_capacity(args.release_dir, selection).as_dict())
            return 0
        if args.command in {
            "validate-hbm-manufacturing-link",
            "reconcile-hbm-manufacturing-link",
        }:
            hbm_link = load_hbm_manufacturing_link_case(
                args.manufacturing_scenario,
                args.hbm_result,
                args.link_recipe,
                args.hbm_capacity_draws,
            )
            if args.command == "validate-hbm-manufacturing-link":
                validation = {
                    "valid": True,
                    "scenario_id": hbm_link.metadata["id"],
                    "quarter": hbm_link.metadata["quarter"],
                    "removed_hbm_wafer_flow_id": hbm_link.lineage[
                        "replacement"
                    ]["removed_aggregate_hbm_wafer_flow_id"],
                    "supplier_count": len(
                        hbm_link.lineage["sources"]["hbm_supplier_result"][
                            "supplier_ids"
                        ]
                    ),
                    "capacity_scope_count": len(
                        hbm_link.lineage["sources"]["hbm_supplier_result"][
                            "capacity_scope_ids"
                        ]
                    ),
                    "distribution_mapping": hbm_link.lineage["replacement"][
                        "distribution_mapping"
                    ],
                    "capacity_draw_count": len(hbm_link.capacity_draws),
                    "synthetic": hbm_link.lineage["synthetic"],
                }
                if hbm_link.package_coverage is not None:
                    validation["package_assembly_start_basis"] = (
                        hbm_link.package_coverage["assembly_start_basis"]
                    )
                    validation["absorbed_resource_kinds"] = list(
                        hbm_link.package_coverage["absorbed_resource_kinds"]
                    )
                _dump(validation)
                return 0
            _dump(
                write_hbm_manufacturing_link_release(
                    hbm_link,
                    args.output_dir,
                    include_output_draws=args.include_output_draws,
                )
            )
            return 0
        if args.command in {
            "validate-hbm-suppliers",
            "reconcile-hbm-suppliers",
        }:
            hbm_suppliers = load_hbm_supplier_scenario(
                args.scenario,
                source_root=args.source_root,
            )
            if args.command == "validate-hbm-suppliers":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": hbm_suppliers.id,
                        "quarter": hbm_suppliers.quarter,
                        "platform_id": hbm_suppliers.platform.id,
                        "suppliers": len(hbm_suppliers.suppliers),
                        "capacity_scope_ids": sorted(
                            item.capacity_scope_id
                            for item in hbm_suppliers.suppliers
                        ),
                        "evidence_records": len(hbm_suppliers.evidence),
                        "source_documents": len(
                            hbm_suppliers.source_documents
                        ),
                        "synthetic": hbm_suppliers.synthetic,
                    }
                )
                return 0
            _dump(
                write_hbm_supplier_release(
                    hbm_suppliers,
                    args.output_dir,
                    source_document=args.scenario.read_text(encoding="utf-8"),
                    include_capacity_draws=args.include_capacity_draws,
                )
            )
            return 0
        if args.command in {
            "validate-system-assembly",
            "reconcile-system-assembly",
        }:
            assembly = load_system_assembly_scenario(
                args.scenario,
                source_root=args.source_root,
            )
            if args.command == "validate-system-assembly":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": assembly.id,
                        "quarter": assembly.quarter,
                        "platform_id": assembly.platform.id,
                        "odms": len(assembly.odms),
                        "component_pools": len(assembly.components),
                        "capacity_scope_ids": sorted(
                            [
                                scope
                                for odm in assembly.odms
                                for scope in (
                                    odm.tray_capacity_scope_id,
                                    odm.rack_capacity_scope_id,
                                )
                            ]
                            + [
                                component.capacity_scope_id
                                for component in assembly.components
                            ]
                        ),
                        "complete_rack_output_basis": (
                            assembly.coverage.output_basis
                        ),
                        "absorbed_constraints": [
                            {
                                "stage": selector.stage,
                                "resource_kind": selector.resource_kind,
                            }
                            for selector in assembly.coverage.absorbed_constraints
                        ],
                        "source_documents": len(assembly.source_documents),
                        "synthetic": assembly.synthetic,
                    }
                )
                return 0
            _dump(
                write_system_assembly_release(
                    assembly,
                    args.output_dir,
                    source_document=args.scenario.read_text(encoding="utf-8"),
                )
            )
            return 0
        if args.command in {"validate-manufacturing", "reconcile-manufacturing"}:
            manufacturing = load_manufacturing(args.scenario)
            if args.command == "validate-manufacturing":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": manufacturing.id,
                        "quarter": manufacturing.quarter,
                        "logic_wafer_flow": manufacturing.logic.wafer.id,
                        "hbm_wafer_flow": manufacturing.hbm.wafer.id,
                        "external_references": len(manufacturing.references),
                        "evidence_records": len(manufacturing.evidence),
                        "synthetic": manufacturing.synthetic,
                    }
                )
                return 0
            _dump(
                write_manufacturing_release(
                    manufacturing,
                    args.output_dir,
                    source_document=args.scenario.read_text(encoding="utf-8"),
                )
            )
            return 0
        if args.command in {"validate-portfolio", "reconcile-portfolio"}:
            portfolio = load_portfolio(args.portfolio)
            if args.command == "validate-portfolio":
                _dump(
                    {
                        "valid": True,
                        "scenario_id": portfolio.id,
                        "quarter": portfolio.quarter,
                        "platforms": len(portfolio.platforms),
                        "resource_pools": len(portfolio.resource_pools),
                        "requirements": len(portfolio.requirements),
                        "evidence_records": len(portfolio.evidence),
                        "synthetic": portfolio.synthetic,
                    }
                )
                return 0
            _dump(
                write_portfolio_release(
                    portfolio,
                    args.output_dir,
                    source_document=args.portfolio.read_text(encoding="utf-8"),
                )
            )
            return 0

        scenario = load_scenario(args.scenario)
        if args.command == "validate":
            _dump(
                {
                    "valid": True,
                    "scenario_id": scenario.id,
                    "quarter": scenario.quarter,
                    "platform": scenario.platform.name,
                    "constraints": len(scenario.constraints),
                    "evidence_records": len(scenario.evidence),
                    "synthetic": scenario.synthetic,
                }
            )
            return 0
        if args.command == "reconcile":
            _dump(
                write_release(
                    scenario,
                    args.output_dir,
                    source_document=args.scenario.read_text(encoding="utf-8"),
                )
            )
            return 0
    except (OSError, ValueError, sqlite3.Error) as exc:
        _dump({"valid": False, "error": str(exc)}, stream=sys.stderr)
        return 2
    raise AssertionError(f"unhandled command: {args.command}")
