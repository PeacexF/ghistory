from __future__ import annotations

import argparse
from datetime import date

import pytest

from ghistory.cli import build_parser, main, parse_iso_date, today_utc


def test_parse_iso_date_accepts_iso_format() -> None:
    assert parse_iso_date("2026-08-17") == date(2026, 8, 17)


@pytest.mark.parametrize("value", ["17-08-2026", "2026/08/17", "2026-13-01", "today", ""])
def test_parse_iso_date_rejects_everything_else(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        parse_iso_date(value)


def test_date_defaults_to_none_so_the_caller_can_use_utc_today() -> None:
    args = build_parser().parse_args([])
    assert args.date is None
    assert args.dry_run is False
    assert args.repair is False


def test_today_utc_returns_a_date() -> None:
    assert isinstance(today_utc(), date)


def test_dry_run_and_repair_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--dry-run", "--repair"])
    assert excinfo.value.code == 2


def test_main_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--date", "2026-08-17"]) == 0
    assert "2026-08-17" in capsys.readouterr().out
