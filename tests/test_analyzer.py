from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ghistory.analyzer import (
    AnalysisError,
    analyze,
    find_previous_snapshot,
    load_snapshot,
    snapshot_dates,
)
from support import error_entry, ok_entry, snapshot

TODAY = date(2026, 8, 18)


def release(tag: str, **overrides: Any) -> dict[str, Any]:
    entry = {
        "tag_name": tag,
        "name": f"Release {tag}",
        "published_at": "2026-08-18T12:00:00Z",
        "created_at": "2026-08-18T11:00:00Z",
        "prerelease": False,
        "draft": False,
        "html_url": f"https://github.com/owner/name/releases/tag/{tag}",
    }
    entry.update(overrides)
    return entry


def write(data_dir: Path, day: str, payload: dict[str, Any] | None = None) -> Path:
    year, month, dom = day.split("-")
    path = data_dir / year / month / f"{dom}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or snapshot([ok_entry("owner/one")], day=day)))
    return path


def test_no_previous_snapshot_on_the_first_day(tmp_path: Path) -> None:
    assert find_previous_snapshot(tmp_path, TODAY) is None


def test_previous_snapshot_skips_gaps(tmp_path: Path) -> None:
    write(tmp_path, "2026-08-11")
    write(tmp_path, "2026-08-15")

    assert find_previous_snapshot(tmp_path, TODAY) == tmp_path / "2026/08/15.json"


def test_previous_snapshot_crosses_month_and_year_boundaries(tmp_path: Path) -> None:
    write(tmp_path, "2025-12-31")

    assert find_previous_snapshot(tmp_path, date(2026, 1, 1)) == tmp_path / "2025/12/31.json"


def test_todays_own_snapshot_is_never_the_previous_one(tmp_path: Path) -> None:
    write(tmp_path, "2026-08-18")
    write(tmp_path, "2026-08-19")

    assert find_previous_snapshot(tmp_path, TODAY) is None


def test_unrelated_files_are_ignored(tmp_path: Path) -> None:
    (tmp_path / "2026" / "08").mkdir(parents=True)
    (tmp_path / "2026" / "08" / "notes.json").write_text("{}")
    (tmp_path / "README.md").write_text("hello")
    write(tmp_path, "2026-08-15")

    assert snapshot_dates(tmp_path) == [date(2026, 8, 15)]


def test_loading_rejects_a_future_schema(tmp_path: Path) -> None:
    payload = snapshot([ok_entry("owner/one")])
    payload["schema_version"] = 99
    path = write(tmp_path, "2026-08-17", payload)

    with pytest.raises(AnalysisError, match="schema_version"):
        load_snapshot(path)


def test_loading_rejects_a_file_that_is_not_a_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "thing.json"
    path.write_text('{"hello": "world"}')

    with pytest.raises(AnalysisError, match="not a snapshot"):
        load_snapshot(path)


def test_loading_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "thing.json"
    path.write_text("{oops")

    with pytest.raises(AnalysisError, match="invalid JSON"):
        load_snapshot(path)


def test_loading_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(AnalysisError, match="no such file"):
        load_snapshot(tmp_path / "missing.json")


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [(100, 150, 50), (150, 100, -50), (100, 100, 0)],
)
def test_deltas_are_plain_subtraction(before: int, after: int, expected: int) -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", stars=after)]),
        snapshot([ok_entry("owner/one", stars=before)], day="2026-08-17"),
    )

    change = analysis.deltas[0].change("stars")
    assert change is not None
    assert (change.before, change.after, change.delta) == (before, after, expected)


def test_every_metric_is_tracked() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", stars=10, forks=20, open_issues=30, subscribers=40)]),
        snapshot(
            [ok_entry("owner/one", stars=1, forks=2, open_issues=3, subscribers=4)],
            day="2026-08-17",
        ),
    )

    metrics = analysis.deltas[0].metrics
    assert {name: change.delta for name, change in metrics.items()} == {
        "stars": 9,
        "forks": 18,
        "open_issues": 27,
        "subscribers": 36,
    }


def test_a_repository_added_today_has_no_deltas() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one"), ok_entry("owner/new")]),
        snapshot([ok_entry("owner/one")], day="2026-08-17"),
    )

    new = next(delta for delta in analysis.deltas if delta.slug == "owner/new")
    assert new.metrics == {}
    assert new.star_delta is None


def test_a_repository_that_failed_yesterday_has_no_deltas() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", stars=200)]),
        snapshot([error_entry("owner/one", "rate_limit")], day="2026-08-17"),
    )

    assert analysis.deltas[0].metrics == {}


def test_a_repository_that_failed_today_is_not_a_delta_at_all() -> None:
    analysis = analyze(
        snapshot([error_entry("owner/one"), ok_entry("owner/two")]),
        snapshot([ok_entry("owner/one"), ok_entry("owner/two")], day="2026-08-17"),
    )

    assert [delta.slug for delta in analysis.deltas] == ["owner/two"]
    assert analysis.failures[0].slug == "owner/one"
    assert analysis.failures[0].error == "not_found"


def test_a_metric_missing_from_one_day_yields_no_delta() -> None:
    today = ok_entry("owner/one")
    yesterday = ok_entry("owner/one")
    del yesterday["subscribers"]

    analysis = analyze(snapshot([today]), snapshot([yesterday], day="2026-08-17"))

    assert "subscribers" not in analysis.deltas[0].metrics
    assert "stars" in analysis.deltas[0].metrics


def test_the_first_day_produces_deltas_for_nobody() -> None:
    analysis = analyze(snapshot([ok_entry("owner/one")]), None)

    assert analysis.previous_date is None
    assert analysis.deltas[0].metrics == {}
    assert analysis.top_growth == []


def test_growth_ranking_is_ordered_and_limited() -> None:
    today = [ok_entry(f"owner/{n}", stars=1000 + n) for n in range(1, 6)]
    yesterday = [ok_entry(f"owner/{n}", stars=1000) for n in range(1, 6)]

    analysis = analyze(
        snapshot(today),
        snapshot(yesterday, day="2026-08-17"),
        top_growth_limit=3,
    )

    assert [delta.slug for delta in analysis.top_growth] == ["owner/5", "owner/4", "owner/3"]


def test_growth_ranking_excludes_flat_and_shrinking_repositories() -> None:
    analysis = analyze(
        snapshot(
            [
                ok_entry("owner/up", stars=1100),
                ok_entry("owner/flat", stars=1000),
                ok_entry("owner/down", stars=900),
            ]
        ),
        snapshot(
            [
                ok_entry("owner/up", stars=1000),
                ok_entry("owner/flat", stars=1000),
                ok_entry("owner/down", stars=1000),
            ],
            day="2026-08-17",
        ),
    )

    assert [delta.slug for delta in analysis.top_growth] == ["owner/up"]


def test_equal_growth_is_broken_by_slug_so_the_ranking_is_stable() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/zeta", stars=1100), ok_entry("owner/alpha", stars=1100)]),
        snapshot(
            [ok_entry("owner/zeta", stars=1000), ok_entry("owner/alpha", stars=1000)],
            day="2026-08-17",
        ),
    )

    assert [delta.slug for delta in analysis.top_growth] == ["owner/alpha", "owner/zeta"]


def test_languages_are_counted_from_successful_entries_only() -> None:
    analysis = analyze(
        snapshot(
            [
                ok_entry("owner/a", language="Go"),
                ok_entry("owner/b", language="Go"),
                ok_entry("owner/c", language="Rust"),
                ok_entry("owner/d", language=None),
                error_entry("owner/e"),
            ]
        ),
        None,
    )

    assert analysis.languages == [("Go", 2), ("Rust", 1), ("Unknown", 1)]


def test_languages_with_equal_counts_are_ordered_by_name() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/a", language="Zig"), ok_entry("owner/b", language="Ada")]),
        None,
    )

    assert analysis.languages == [("Ada", 1), ("Zig", 1)]


def test_a_new_tag_is_reported_as_a_release() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", releases=[release("v2"), release("v1")])]),
        snapshot([ok_entry("owner/one", releases=[release("v1")])], day="2026-08-17"),
    )

    assert [new.tag_name for new in analysis.new_releases] == ["v2"]
    assert analysis.new_releases[0].full_name == "owner/one"
    assert analysis.new_releases[0].prerelease is False


def test_a_prerelease_is_flagged() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", releases=[release("v2", prerelease=True)])]),
        snapshot([ok_entry("owner/one", releases=[])], day="2026-08-17"),
    )

    assert analysis.new_releases[0].prerelease is True


def test_the_first_day_reports_no_releases_at_all() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", releases=[release("v1"), release("v2")])]),
        None,
    )

    assert analysis.new_releases == []


def test_a_newly_tracked_repository_does_not_dump_its_release_history() -> None:
    analysis = analyze(
        snapshot(
            [
                ok_entry("owner/one", releases=[release("v1")]),
                ok_entry("owner/new", releases=[release("a"), release("b"), release("c")]),
            ]
        ),
        snapshot([ok_entry("owner/one", releases=[release("v1")])], day="2026-08-17"),
    )

    assert analysis.new_releases == []


def test_an_unreadable_release_list_yields_no_releases() -> None:
    today = ok_entry("owner/one")
    del today["releases"]
    today["releases_error"] = "rate_limit"

    analysis = analyze(
        snapshot([today]),
        snapshot([ok_entry("owner/one", releases=[release("v1")])], day="2026-08-17"),
    )

    assert analysis.new_releases == []


def test_yesterdays_unreadable_release_list_does_not_invent_releases() -> None:
    yesterday = ok_entry("owner/one")
    del yesterday["releases"]
    yesterday["releases_error"] = "server_error"

    analysis = analyze(
        snapshot([ok_entry("owner/one", releases=[release("v1"), release("v2")])]),
        snapshot([yesterday], day="2026-08-17"),
    )

    assert analysis.new_releases == []


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        ("license", "MIT", "GPL-3.0"),
        ("archived", False, True),
        ("disabled", False, True),
        ("default_branch", "main", "trunk"),
        ("description", "a description", "something else"),
    ],
)
def test_watched_fields_are_reported_as_significant(field: str, before: Any, after: Any) -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", **{field: after})]),
        snapshot([ok_entry("owner/one", **{field: before})], day="2026-08-17"),
    )

    change = analysis.significant_changes[0].changes[0]
    assert (change.field, change.before, change.after) == (field, before, after)


def test_a_rename_is_detected_from_the_observed_name() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", full_name="owner/renamed")]),
        snapshot([ok_entry("owner/one", full_name="owner/one")], day="2026-08-17"),
    )

    changes = {
        change.field: (change.before, change.after)
        for change in analysis.significant_changes[0].changes
    }
    assert changes == {"name": ("one", "renamed")}


def test_a_transfer_is_reported_as_an_owner_change() -> None:
    analysis = analyze(
        snapshot([ok_entry("facebook/react", full_name="react/react")]),
        snapshot([ok_entry("facebook/react", full_name="facebook/react")], day="2026-08-17"),
    )

    changes = {
        change.field: (change.before, change.after)
        for change in analysis.significant_changes[0].changes
    }
    assert changes == {"owner": ("facebook", "react")}


def test_a_transfer_that_also_renames_reports_both() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", full_name="newowner/newname")]),
        snapshot([ok_entry("owner/one", full_name="owner/one")], day="2026-08-17"),
    )

    changes = {change.field for change in analysis.significant_changes[0].changes}
    assert changes == {"owner", "name"}


def test_an_unchanged_repository_is_not_significant() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", stars=2000)]),
        snapshot([ok_entry("owner/one", stars=1000)], day="2026-08-17"),
    )

    assert analysis.significant_changes == []


def test_a_failure_on_either_day_produces_no_phantom_changes() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one", license="GPL-3.0")]),
        snapshot([error_entry("owner/one")], day="2026-08-17"),
    )

    assert analysis.significant_changes == []


def test_analysis_carries_the_snapshot_summary() -> None:
    analysis = analyze(
        snapshot([ok_entry("owner/one"), error_entry("owner/two")]),
        snapshot([ok_entry("owner/one")], day="2026-08-17"),
    )

    assert analysis.date == "2026-08-18"
    assert analysis.previous_date == "2026-08-17"
    assert analysis.status == "partial"
    assert analysis.counts == {"requested": 2, "ok": 1, "failed": 1}
