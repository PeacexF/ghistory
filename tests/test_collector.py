from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ghistory.collector import (
    BOOL_SETTINGS,
    FLOAT_SETTINGS,
    INT_SETTINGS,
    ConfigError,
    Settings,
    collect,
    load_repositories,
    load_settings,
    normalize_repository,
    render_snapshot,
    snapshot_path,
    write_snapshot,
)
from support import build_client, make_response, release_payload, repository_payload

DATE = date(2026, 8, 17)
FIXED_NOW = datetime(2026, 8, 17, 0, 4, 21, 987654, tzinfo=UTC)


def settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


def collect_from(outcomes: list[Any], slugs: list[str], **kwargs: Any) -> dict[str, Any]:
    client, _adapter, _slept = build_client(outcomes)
    return collect(
        client,
        slugs,
        settings(**kwargs),
        observation_date=DATE,
        now=lambda: FIXED_NOW,
    )


def test_repository_list_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "repositories.txt"
    path.write_text("# a comment\n\nowner/one\n  owner/two  \n\n# another\n", encoding="utf-8")

    assert load_repositories(path) == ["owner/one", "owner/two"]


def test_repository_list_drops_case_insensitive_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "repositories.txt"
    path.write_text("owner/one\nOwner/One\nowner/two\n", encoding="utf-8")

    assert load_repositories(path) == ["owner/one", "owner/two"]


def test_repository_list_rejects_a_malformed_line(tmp_path: Path) -> None:
    path = tmp_path / "repositories.txt"
    path.write_text("owner/one\nnot-a-slug\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"repositories\.txt:2"):
        load_repositories(path)


def test_repository_list_rejects_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "repositories.txt"
    path.write_text("# only comments\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="no repositories"):
        load_repositories(path)


def test_repository_list_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no such file"):
        load_repositories(tmp_path / "missing.txt")


def test_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")

    assert load_settings(path) == Settings()


def test_settings_are_read(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"max_releases_per_repository": 3, "request_timeout_seconds": 5}),
        encoding="utf-8",
    )

    loaded = load_settings(path)
    assert loaded.max_releases_per_repository == 3
    assert loaded.request_timeout_seconds == 5.0


def test_settings_reject_an_unknown_key(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"max_release_per_repository": 3}), encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown setting"):
        load_settings(path)


@pytest.mark.parametrize(
    "raw",
    [
        {"max_releases_per_repository": 0},
        {"max_releases_per_repository": "ten"},
        {"max_releases_per_repository": True},
        {"discovery_enabled": "yes"},
        {"request_timeout_seconds": -1},
    ],
)
def test_settings_reject_bad_values(tmp_path: Path, raw: dict[str, Any]) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_settings(path)


def test_settings_reject_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid JSON"):
        load_settings(path)


def test_every_settings_field_is_validated() -> None:
    declared = {field.name for field in fields(Settings)}
    assert declared == BOOL_SETTINGS | INT_SETTINGS | FLOAT_SETTINGS


def test_normalized_entry_has_the_documented_shape() -> None:
    entry = normalize_repository(
        "rust-lang/rust",
        repository_payload("rust-lang/rust"),
        [release_payload("1.92.0")],
    )

    assert entry == {
        "slug": "rust-lang/rust",
        "status": "ok",
        "full_name": "rust-lang/rust",
        "description": "rust description",
        "language": "Rust",
        "license": "MIT",
        "default_branch": "main",
        "topics": ["compiler", "rust"],
        "stars": 112340,
        "forks": 14782,
        "open_issues": 1251,
        "subscribers": 4812,
        "size": 1234567,
        "archived": False,
        "disabled": False,
        "created_at": "2010-06-16T20:39:03Z",
        "updated_at": "2026-08-16T23:51:00Z",
        "pushed_at": "2026-08-16T23:48:00Z",
        "releases": [
            {
                "tag_name": "1.92.0",
                "name": "Release 1.92.0",
                "published_at": "2026-08-16T12:00:00Z",
                "created_at": "2026-08-16T11:00:00Z",
                "prerelease": False,
                "draft": False,
                "html_url": "https://github.com/owner/name/releases/tag/1.92.0",
            }
        ],
    }


def test_watchers_are_not_stored_because_the_api_reports_stars() -> None:
    entry = normalize_repository("owner/name", repository_payload("owner/name"), [])

    assert "watchers" not in entry
    assert entry["subscribers"] == 4812


def test_a_redirect_keeps_the_requested_slug_as_the_join_key() -> None:
    entry = normalize_repository(
        "facebook/react",
        repository_payload("react/react"),
        [],
    )

    assert entry["slug"] == "facebook/react"
    assert entry["full_name"] == "react/react"


def test_missing_licence_and_topics_are_represented_honestly() -> None:
    entry = normalize_repository(
        "owner/name",
        repository_payload("owner/name", license=None, topics=[], language=None),
        [],
    )

    assert entry["license"] is None
    assert entry["topics"] == []
    assert entry["language"] is None


def test_topics_are_sorted_so_reordering_does_not_churn_the_diff() -> None:
    entry = normalize_repository(
        "owner/name",
        repository_payload("owner/name", topics=["zeta", "alpha", "mid"]),
        [],
    )

    assert entry["topics"] == ["alpha", "mid", "zeta"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"stargazers_count": None},
        {"stargazers_count": "many"},
        {"archived": "false"},
        {"license": "MIT"},
        {"topics": [1, 2]},
        {"description": 42},
    ],
)
def test_malformed_fields_fail_loudly(overrides: dict[str, Any]) -> None:
    payload = repository_payload("owner/name", **overrides)

    with pytest.raises(Exception, match="owner/name"):
        normalize_repository("owner/name", payload, [])


def test_collection_of_healthy_repositories_is_complete() -> None:
    snapshot = collect_from(
        [
            make_response(200, repository_payload("owner/one")),
            make_response(200, [release_payload("v1")]),
            make_response(200, repository_payload("owner/two")),
            make_response(200, []),
        ],
        ["owner/one", "owner/two"],
    )

    assert snapshot["status"] == "complete"
    assert snapshot["counts"] == {"requested": 2, "ok": 2, "failed": 0}
    assert snapshot["date"] == "2026-08-17"
    assert snapshot["generated_at"] == "2026-08-17T00:04:21Z"
    assert snapshot["schema_version"] == 1


def test_a_failed_repository_carries_no_metrics() -> None:
    snapshot = collect_from(
        [
            make_response(404, {"message": "Not Found"}),
            make_response(200, repository_payload("owner/two")),
            make_response(200, []),
        ],
        ["owner/gone", "owner/two"],
    )

    failed = next(e for e in snapshot["repositories"] if e["slug"] == "owner/gone")
    assert failed == {"slug": "owner/gone", "status": "error", "error": "not_found"}
    assert "stars" not in failed
    assert snapshot["status"] == "partial"
    assert snapshot["counts"] == {"requested": 2, "ok": 1, "failed": 1}


def test_an_unreadable_release_list_is_not_an_empty_one() -> None:
    snapshot = collect_from(
        [
            make_response(200, repository_payload("owner/one")),
            make_response(500, {"message": "boom"}),
            make_response(500, {"message": "boom"}),
            make_response(500, {"message": "boom"}),
        ],
        ["owner/one"],
    )

    entry = snapshot["repositories"][0]
    assert entry["status"] == "ok"
    assert entry["stars"] == 112340
    assert entry["releases_error"] == "server_error"
    assert "releases" not in entry


def test_an_exhausted_quota_marks_the_remaining_repositories() -> None:
    quota_headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"}
    snapshot = collect_from(
        [
            make_response(200, repository_payload("owner/one"), {"x-ratelimit-remaining": "1"}),
            make_response(403, {"message": "rate limit"}, quota_headers),
        ],
        ["owner/one", "owner/two", "owner/three"],
    )

    by_slug = {entry["slug"]: entry for entry in snapshot["repositories"]}
    assert by_slug["owner/one"]["status"] == "ok"
    assert by_slug["owner/one"]["releases_error"] == "rate_limit"
    assert by_slug["owner/two"]["error"] == "rate_limit"
    assert by_slug["owner/three"]["error"] == "rate_limit"
    assert snapshot["status"] == "partial"


def test_a_collection_where_nothing_succeeded_is_not_called_partial() -> None:
    snapshot = collect_from(
        [make_response(404, {"message": "Not Found"})],
        ["owner/gone"],
    )

    assert snapshot["status"] == "failed"
    assert snapshot["counts"] == {"requested": 1, "ok": 0, "failed": 1}


def test_release_count_is_limited_by_settings() -> None:
    snapshot = collect_from(
        [
            make_response(200, repository_payload("owner/one")),
            make_response(200, [release_payload(f"v{i}") for i in range(10)]),
        ],
        ["owner/one"],
        max_releases_per_repository=2,
    )

    assert len(snapshot["repositories"][0]["releases"]) == 2


def test_entries_are_sorted_by_slug_regardless_of_input_order() -> None:
    snapshot = collect_from(
        [
            make_response(200, repository_payload("owner/zeta")),
            make_response(200, []),
            make_response(200, repository_payload("owner/alpha")),
            make_response(200, []),
        ],
        ["owner/zeta", "owner/alpha"],
    )

    assert [entry["slug"] for entry in snapshot["repositories"]] == ["owner/alpha", "owner/zeta"]


def test_rendering_is_byte_identical_for_equal_snapshots() -> None:
    outcomes = [
        make_response(200, repository_payload("owner/one")),
        make_response(200, [release_payload("v1")]),
    ]
    first = collect_from(list(outcomes), ["owner/one"])
    second = collect_from(
        [
            make_response(200, repository_payload("owner/one")),
            make_response(200, [release_payload("v1")]),
        ],
        ["owner/one"],
    )

    assert render_snapshot(first) == render_snapshot(second)


def test_rendered_snapshot_is_sorted_json_with_a_trailing_newline() -> None:
    rendered = render_snapshot({"b": 1, "a": {"d": 2, "c": 3}})

    assert rendered == '{\n  "a": {\n    "c": 3,\n    "d": 2\n  },\n  "b": 1\n}\n'


def test_snapshot_path_is_year_month_day() -> None:
    assert snapshot_path(Path("data"), DATE) == Path("data/2026/08/17.json")


def test_writing_creates_directories_and_leaves_no_temporary_files(tmp_path: Path) -> None:
    destination = snapshot_path(tmp_path, DATE)
    write_snapshot({"date": "2026-08-17"}, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == {"date": "2026-08-17"}
    assert list(destination.parent.iterdir()) == [destination]


def test_a_written_snapshot_is_world_readable(tmp_path: Path) -> None:
    destination = snapshot_path(tmp_path, DATE)
    write_snapshot({"date": "2026-08-17"}, destination)

    assert destination.stat().st_mode & 0o777 == 0o644


def test_a_failed_write_leaves_the_previous_snapshot_intact(tmp_path: Path) -> None:
    destination = snapshot_path(tmp_path, DATE)
    write_snapshot({"date": "2026-08-17", "status": "complete"}, destination)
    original = destination.read_text(encoding="utf-8")

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        write_snapshot({"broken": Unserializable()}, destination)

    assert destination.read_text(encoding="utf-8") == original
    assert list(destination.parent.iterdir()) == [destination]
