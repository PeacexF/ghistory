from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ghistory import __version__
from ghistory.analyzer import (
    Analysis,
    AnalysisError,
    analyze,
    find_previous_snapshot,
    load_snapshot,
)
from ghistory.collector import (
    ConfigError,
    Settings,
    collect,
    load_repositories,
    load_settings,
    snapshot_path,
    write_snapshot,
)
from ghistory.github import GitHubClient, GitHubError
from ghistory.report import report_path, write_report

DEFAULT_CONFIG_DIR = Path("config")
DEFAULT_DATA_DIR = Path("data")
DEFAULT_REPORTS_DIR = Path("reports")


def parse_iso_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a date as YYYY-MM-DD, got {value!r}") from None


def today_utc() -> date:
    return datetime.now(UTC).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghistory",
        description="Collect a daily snapshot of the GitHub ecosystem.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ghistory {__version__}",
    )
    parser.add_argument(
        "--date",
        type=parse_iso_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="observation date (default: today in UTC)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="contact the API and print a summary, but write nothing to disk",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="overwrite an existing snapshot for the date (off by default)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="rebuild the report from stored snapshots without contacting the API",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help=f"directory holding repositories.txt and settings.json "
        f"(default: {DEFAULT_CONFIG_DIR})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"snapshot output directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help=f"report output directory (default: {DEFAULT_REPORTS_DIR})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.dry_run and args.repair:
        parser.error("--dry-run and --repair are mutually exclusive")
    if args.report_only and (args.dry_run or args.repair):
        parser.error("--report-only cannot be combined with --dry-run or --repair")

    observation_date = args.date or today_utc()
    destination = snapshot_path(args.data_dir, observation_date)

    print(f"ghistory {__version__}")
    print(f"Date: {observation_date.isoformat()}")

    if args.report_only:
        return rebuild_report(args, observation_date, destination)

    if destination.exists() and not args.repair and not args.dry_run:
        print(f"{destination} already exists. Nothing to do.")
        return 0

    try:
        settings = load_settings(args.config_dir / "settings.json")
        slugs = load_repositories(args.config_dir / "repositories.txt")
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        client = GitHubClient.from_env(
            timeout=settings.request_timeout_seconds,
            max_attempts=settings.max_attempts,
        )
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with client:
        snapshot = collect(client, slugs, settings, observation_date=observation_date)

    print_summary(snapshot)

    if snapshot["counts"]["ok"] == 0:
        print("error: no repository could be collected; nothing written", file=sys.stderr)
        return 1

    try:
        analysis = build_analysis(snapshot, args.data_dir, observation_date, settings)
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_growth(analysis)

    if args.dry_run:
        print("Dry run — nothing written.")
        return 0

    write_snapshot(snapshot, destination)
    print(f"Wrote {destination}")

    report_destination = report_path(args.reports_dir, observation_date)
    write_report(analysis, report_destination)
    print(f"Wrote {report_destination}")
    return 0


def build_analysis(
    snapshot: dict[str, Any],
    data_dir: Path,
    observation_date: date,
    settings: Settings,
) -> Analysis:
    previous_path = find_previous_snapshot(data_dir, observation_date)
    previous = None if previous_path is None else load_snapshot(previous_path)
    return analyze(snapshot, previous, top_growth_limit=settings.top_growth_limit)


def rebuild_report(args: argparse.Namespace, observation_date: date, source: Path) -> int:
    try:
        settings = load_settings(args.config_dir / "settings.json")
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        snapshot = load_snapshot(source)
        analysis = build_analysis(snapshot, args.data_dir, observation_date, settings)
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_summary(snapshot)
    print_growth(analysis)

    destination = report_path(args.reports_dir, observation_date)
    write_report(analysis, destination)
    print(f"Wrote {destination}")
    return 0


def print_summary(snapshot: dict[str, Any]) -> None:
    counts = snapshot["counts"]
    print(f"Repositories: {counts['requested']}")
    print(f"Successful:   {counts['ok']}")
    print(f"Failed:       {counts['failed']}")

    failures = [entry for entry in snapshot["repositories"] if entry["status"] == "error"]
    if failures:
        print("Failures:")
        for entry in failures:
            print(f"  - {entry['slug']} ({entry['error']})")

    print(f"Status: {snapshot['status'].upper()}")


def print_growth(analysis: Analysis) -> None:
    if analysis.previous_date is None:
        print("No previous snapshot; growth starts with the next run.")
        return

    if analysis.top_growth:
        print("Top growth:")
        for rank, delta in enumerate(analysis.top_growth[:3], start=1):
            change = delta.change("stars")
            if change is not None:
                print(f"  {rank}. {delta.full_name} +{change.delta:,} stars")

    print(f"New releases: {len(analysis.new_releases)}")
    print(f"Significant changes: {len(analysis.significant_changes)}")
