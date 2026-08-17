from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from ghistory import __version__

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

    observation_date = args.date or today_utc()

    print(f"ghistory {__version__}")
    print(f"Date: {observation_date.isoformat()}")
    print("Collector not implemented yet — nothing to do.")
    return 0
