from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import requests
from requests.models import Response

from ghistory.cli import build_parser, main, parse_iso_date, today_utc
from ghistory.github import GitHubClient
from support import TOKEN, StubAdapter, make_response, release_payload, repository_payload


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


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "repositories.txt").write_text("owner/one\n", encoding="utf-8")
    (config / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    return tmp_path


def run(workspace: Path, *extra: str) -> int:
    return main(
        [
            "--date",
            "2026-08-17",
            "--config-dir",
            str(workspace / "config"),
            "--data-dir",
            str(workspace / "data"),
            *extra,
        ]
    )


def stub_api(monkeypatch: pytest.MonkeyPatch, *outcomes: Response | Exception) -> StubAdapter:
    adapter = StubAdapter(outcomes)

    def from_env(**kwargs: Any) -> GitHubClient:
        session = requests.Session()
        session.mount("https://", adapter)
        return GitHubClient(TOKEN, session=session, **kwargs)

    monkeypatch.setattr(GitHubClient, "from_env", staticmethod(from_env))
    return adapter


def healthy_api(monkeypatch: pytest.MonkeyPatch) -> StubAdapter:
    return stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, [release_payload("v1")]),
    )


def test_collection_writes_a_snapshot(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthy_api(monkeypatch)

    assert run(workspace) == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["date"] == "2026-08-17"
    assert snapshot["repositories"][0]["stars"] == 112340


def test_dry_run_writes_nothing(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthy_api(monkeypatch)

    assert run(workspace, "--dry-run") == 0
    assert not (workspace / "data").exists()


def test_an_existing_snapshot_is_not_recollected(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run(workspace)
    original = (workspace / "data/2026/08/17.json").read_text(encoding="utf-8")

    # No stubbed responses left: a second collection would raise on the first request.
    stub_api(monkeypatch)
    assert run(workspace) == 0
    assert (workspace / "data/2026/08/17.json").read_text(encoding="utf-8") == original


def test_repair_overwrites_an_existing_snapshot(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    healthy_api(monkeypatch)
    run(workspace)

    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count=999999)),
        make_response(200, []),
    )
    assert run(workspace, "--repair") == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["repositories"][0]["stars"] == 999999


def test_a_total_failure_writes_nothing_and_exits_non_zero(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_api(monkeypatch, make_response(404, {"message": "Not Found"}))

    assert run(workspace) == 1
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

    assert run(workspace) == 0

    snapshot = json.loads((workspace / "data/2026/08/17.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "partial"
    assert snapshot["counts"] == {"requested": 2, "ok": 1, "failed": 1}


def test_a_broken_config_is_reported_before_any_request(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (workspace / "config/settings.json").write_text('{"nope": 1}', encoding="utf-8")
    stub_api(monkeypatch)

    assert run(workspace) == 1
    assert "unknown setting" in capsys.readouterr().err


def test_a_missing_token_is_reported(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")

    assert run(workspace) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().err
