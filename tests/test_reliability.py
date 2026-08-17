from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from support import make_response, release_payload, repository_payload, run_cli, stub_api

QUOTA_SPENT = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}


def two_repositories(workspace: Path) -> None:
    (workspace / "config/repositories.txt").write_text("owner/one\nowner/two\n", encoding="utf-8")


def collect_day(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    day: str,
    stars: int = 1000,
    releases: list[str] | None = None,
) -> None:
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count=stars)),
        make_response(200, [release_payload(tag) for tag in (releases or ["v1"])]),
    )
    assert run_cli(workspace, day=day) == 0


def snapshot_of(workspace: Path, day: str) -> dict[str, Any]:
    year, month, dom = day.split("-")
    path = workspace / "data" / year / month / f"{dom}.json"
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def files_under(workspace: Path) -> dict[str, str]:
    return {
        str(path.relative_to(workspace)): path.read_text(encoding="utf-8")
        for path in sorted(workspace.rglob("*"))
        if path.is_file()
    }


def test_github_being_down_leaves_yesterday_untouched(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17")
    before = files_under(workspace)

    stub_api(monkeypatch, *[requests.ConnectionError("no route") for _ in range(3)])
    assert run_cli(workspace, day="2026-08-18") == 1

    assert files_under(workspace) == before
    assert not (workspace / "data/2026/08/18.json").exists()
    assert not (workspace / "reports/2026/08/18.md").exists()


def test_an_exhausted_quota_records_what_was_collected_and_nothing_more(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    two_repositories(workspace)
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one"), {"x-ratelimit-remaining": "1"}),
        make_response(403, {"message": "rate limit"}, QUOTA_SPENT),
    )

    assert run_cli(workspace) == 0

    entries = {
        entry["slug"]: entry for entry in snapshot_of(workspace, "2026-08-17")["repositories"]
    }
    assert entries["owner/one"]["status"] == "ok"
    assert entries["owner/one"]["releases_error"] == "rate_limit"
    assert entries["owner/two"] == {
        "slug": "owner/two",
        "status": "error",
        "error": "rate_limit",
    }
    assert snapshot_of(workspace, "2026-08-17")["status"] == "partial"

    report = (workspace / "reports/2026/08/17.md").read_text(encoding="utf-8")
    assert "Collection status: PARTIAL" in report
    assert "`owner/two` — rate_limit" in report


def test_a_malformed_payload_fails_one_repository_not_the_run(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    two_repositories(workspace)
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count="lots")),
        make_response(200, []),
        make_response(200, repository_payload("owner/two")),
        make_response(200, []),
    )

    assert run_cli(workspace) == 0

    entries = {
        entry["slug"]: entry for entry in snapshot_of(workspace, "2026-08-17")["repositories"]
    }
    assert entries["owner/one"] == {
        "slug": "owner/one",
        "status": "error",
        "error": "invalid_response",
    }
    assert entries["owner/two"]["stars"] == 112340


def test_an_html_error_page_is_not_mistaken_for_data(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub_api(monkeypatch, make_response(200, raw_body="<html>502 Bad Gateway</html>"))

    assert run_cli(workspace) == 1
    assert not (workspace / "data/2026/08/17.json").exists()


def test_running_twice_in_a_day_changes_nothing(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17")
    before = files_under(workspace)

    stub_api(monkeypatch)
    assert run_cli(workspace, day="2026-08-17") == 0

    assert files_under(workspace) == before


def test_a_flat_day_still_records_an_observation(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17", stars=1000)
    collect_day(workspace, monkeypatch, "2026-08-18", stars=1000)

    assert snapshot_of(workspace, "2026-08-18")["repositories"][0]["stars"] == 1000
    report = (workspace / "reports/2026/08/18.md").read_text(encoding="utf-8")
    assert "No repository gained stars." in report
    assert "Compared with 2026-08-17." in report


def test_a_gap_in_collection_compares_against_the_last_good_day(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17", stars=1000)

    stub_api(monkeypatch, *[requests.Timeout("slow") for _ in range(3)])
    assert run_cli(workspace, day="2026-08-18") == 1

    collect_day(workspace, monkeypatch, "2026-08-19", stars=1500)

    report = (workspace / "reports/2026/08/19.md").read_text(encoding="utf-8")
    assert "Compared with 2026-08-17." in report
    assert "+500" in report


def test_an_unreadable_old_snapshot_does_not_cost_today_its_observation(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17")
    (workspace / "data/2026/08/17.json").write_text("{ truncated", encoding="utf-8")

    collect_day(workspace, monkeypatch, "2026-08-18", stars=2000)

    assert snapshot_of(workspace, "2026-08-18")["repositories"][0]["stars"] == 2000
    assert "invalid JSON" in capsys.readouterr().err
    report = (workspace / "reports/2026/08/18.md").read_text(encoding="utf-8")
    assert "First observation" in report


def test_a_renamed_repository_keeps_its_history(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17", stars=1000)

    stub_api(
        monkeypatch,
        make_response(
            200,
            repository_payload("owner/one", full_name="newowner/one", stargazers_count=1200),
        ),
        make_response(200, [release_payload("v1")]),
    )
    assert run_cli(workspace, day="2026-08-18") == 0

    entry = snapshot_of(workspace, "2026-08-18")["repositories"][0]
    assert entry["slug"] == "owner/one"
    assert entry["full_name"] == "newowner/one"

    report = (workspace / "reports/2026/08/18.md").read_text(encoding="utf-8")
    assert "Owner: owner → newowner" in report
    assert "+200" in report


def test_a_deleted_repository_leaves_its_past_intact(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    two_repositories(workspace)
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, []),
        make_response(200, repository_payload("owner/two")),
        make_response(200, []),
    )
    assert run_cli(workspace, day="2026-08-17") == 0
    yesterday = json.dumps(snapshot_of(workspace, "2026-08-17"), sort_keys=True)

    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, []),
        make_response(404, {"message": "Not Found"}),
    )
    assert run_cli(workspace, day="2026-08-18") == 0

    entries = {
        entry["slug"]: entry for entry in snapshot_of(workspace, "2026-08-18")["repositories"]
    }
    assert entries["owner/two"] == {
        "slug": "owner/two",
        "status": "error",
        "error": "not_found",
    }
    assert "stars" not in entries["owner/two"]
    assert json.dumps(snapshot_of(workspace, "2026-08-17"), sort_keys=True) == yesterday


def test_a_repository_added_to_the_config_does_not_backfill(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17")

    two_repositories(workspace)
    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one")),
        make_response(200, [release_payload("v1")]),
        make_response(200, repository_payload("owner/two")),
        make_response(200, [release_payload("a"), release_payload("b")]),
    )
    assert run_cli(workspace, day="2026-08-18") == 0

    report = (workspace / "reports/2026/08/18.md").read_text(encoding="utf-8")
    assert "## New releases\n\nNone." in report
    assert len(snapshot_of(workspace, "2026-08-17")["repositories"]) == 1


def test_history_is_never_rewritten_without_being_asked(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17", stars=1000)
    collect_day(workspace, monkeypatch, "2026-08-18", stars=2000)
    original = snapshot_of(workspace, "2026-08-17")

    stub_api(monkeypatch)
    assert run_cli(workspace, day="2026-08-17") == 0

    assert snapshot_of(workspace, "2026-08-17") == original


def test_a_rerun_never_reports_growth_against_itself(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collect_day(workspace, monkeypatch, "2026-08-17", stars=1000)

    stub_api(
        monkeypatch,
        make_response(200, repository_payload("owner/one", stargazers_count=1000)),
        make_response(200, [release_payload("v1")]),
    )
    assert run_cli(workspace, "--repair", day="2026-08-17") == 0

    report = (workspace / "reports/2026/08/17.md").read_text(encoding="utf-8")
    assert "First observation" in report
