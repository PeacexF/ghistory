from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pytest

from ghistory.cli import build_parser, main, parse_iso_date, today_utc
from support import (
    StubAdapter,
    make_response,
    release_payload,
    repository_payload,
    run_cli,
    stub_api,
)


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


def healthy_api(monkeypatch: pytest.MonkeyPatch) -> StubAdapter:
    return stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, [release_payload("v1")]),
    )


def test_collection_writes_a_snapshot(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthy_api(monkeypatch)

    assert run_cli(workspace) == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["date"] == "2026-08-17"
    assert snapshot["repositories"][0]["stars"] == 112340


def test_collection_writes_a_report(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthy_api(monkeypatch)

    assert run_cli(workspace) == 0

    report = (workspace / "reports/2026/08/17.md").read_text(encoding="utf-8")
    assert report.startswith("# ghistory — 2026-08-17")
    assert "First observation" in report


def test_dry_run_writes_nothing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthy_api(monkeypatch)

    assert run_cli(workspace, "--dry-run") == 0
    assert not (workspace / "data").exists()
    assert not (workspace / "reports").exists()


def test_a_second_day_reports_growth_against_the_first(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run_cli(workspace)

    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count=112900)),
        make_response(200, [release_payload("v2"), release_payload("v1")]),
    )
    assert run_cli(workspace, day="2026-08-18") == 0

    report = (workspace / "reports/2026/08/18.md").read_text(encoding="utf-8")
    assert "Compared with 2026-08-17." in report
    assert "+560" in report
    assert "**owner/one** — [v2]" in report


def test_an_existing_snapshot_is_not_recollected(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run_cli(workspace)
    original = (workspace / "data/2026/08/17.json").read_text(encoding="utf-8")

    # No stubbed responses left: a second collection would raise on the first request.
    stub_api(monkeypatch)
    assert run_cli(workspace) == 0
    assert (workspace / "data/2026/08/17.json").read_text(encoding="utf-8") == original


def test_repair_overwrites_an_existing_snapshot(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run_cli(workspace)

    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count=999999)),
        make_response(200, []),
    )
    assert run_cli(workspace, "--repair") == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["repositories"][0]["stars"] == 999999


def test_a_total_failure_writes_nothing_and_exits_non_zero(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_api(monkeypatch, make_response(404, {"message": "Not Found"}))

    assert run_cli(workspace) == 1
    assert not (workspace / "data/2026/08/17.json").exists()


def test_a_partial_collection_is_still_recorded(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (workspace / "config/repositories.txt").write_text("owner/one\nowner/gone\n", encoding="utf-8")
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, []),
        make_response(404, {"message": "Not Found"}),
    )

    assert run_cli(workspace) == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert snapshot["counts"] == {"requested": 2, "ok": 1, "failed": 1}


def test_a_report_can_be_rebuilt_from_a_stored_snapshot(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run_cli(workspace)
    (workspace / "reports/2026/08/17.md").unlink()

    # No stubbed responses left: rebuilding must not touch the API.
    stub_api(monkeypatch)
    assert run_cli(workspace, "--report-only") == 0
    assert (workspace / "reports/2026/08/17.md").exists()


def test_rebuilding_a_report_for_a_date_never_collected_fails(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stub_api(monkeypatch)

    assert run_cli(workspace, "--report-only") == 1
    assert "no such file" in capsys.readouterr().err


def test_report_only_refuses_to_combine_with_collection_flags() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--report-only", "--repair"])
    assert excinfo.value.code == 2


def test_a_broken_config_is_reported_before_any_request(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (workspace / "config/settings.json").write_text('{"nope": 1}', encoding="utf-8")
    stub_api(monkeypatch)

    assert run_cli(workspace) == 1
    assert "unknown setting" in capsys.readouterr().err


def test_a_missing_token_is_reported(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")

    assert run_cli(workspace) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err
