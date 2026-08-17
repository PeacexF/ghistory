from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ghistory.analyzer import analyze
from ghistory.report import render_report, report_path, write_report
from support import error_entry, ok_entry, snapshot

FIXTURES = Path(__file__).parent / "fixtures"


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


def full_analysis() -> Any:
    today = [
        ok_entry(
            "owner/fast", stars=12000, language="Rust", releases=[release("v2"), release("v1")]
        ),
        ok_entry("owner/steady", stars=5000, language="Go", releases=[release("v9")]),
        ok_entry("owner/slow", stars=300, language="Go", archived=True, license="GPL-3.0"),
        ok_entry("owner/still", stars=42, language=None),
        error_entry("owner/missing", "rate_limit"),
    ]
    yesterday = [
        ok_entry("owner/fast", stars=10000, language="Rust", releases=[release("v1")]),
        ok_entry("owner/steady", stars=4900, language="Go", releases=[release("v9")]),
        ok_entry("owner/slow", stars=300, language="Go", archived=False, license="MIT"),
        ok_entry("owner/still", stars=42, language=None),
        ok_entry("owner/missing", stars=7),
    ]
    return analyze(snapshot(today), snapshot(yesterday, day="2026-08-17"), top_growth_limit=10)


def test_report_matches_the_golden_file() -> None:
    expected = (FIXTURES / "report_full.md").read_text(encoding="utf-8")

    assert render_report(full_analysis()) == expected


def test_rendering_the_same_analysis_twice_is_byte_identical() -> None:
    assert render_report(full_analysis()) == render_report(full_analysis())


def test_a_report_ends_with_exactly_one_newline() -> None:
    rendered = render_report(full_analysis())

    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n")


def test_the_first_report_says_there_is_nothing_to_compare() -> None:
    rendered = render_report(analyze(snapshot([ok_entry("owner/one")]), None))

    assert "First observation" in rendered
    assert "no growth can be measured yet" in rendered
    assert "Compared with" not in rendered


def test_a_complete_report_has_no_failure_section() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one")]),
            snapshot([ok_entry("owner/one")], day="2026-08-17"),
        )
    )

    assert "Incomplete collection" not in rendered
    assert "Collection status: COMPLETE" in rendered


def test_a_partial_report_names_every_failure() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one"), error_entry("owner/gone", "not_found")]),
            snapshot([ok_entry("owner/one")], day="2026-08-17"),
        )
    )

    assert "## Incomplete collection" in rendered
    assert "`owner/gone` — not_found" in rendered
    assert "Collection status: PARTIAL" in rendered


def test_flat_days_say_so_rather_than_showing_an_empty_table() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", stars=100)]),
            snapshot([ok_entry("owner/one", stars=100)], day="2026-08-17"),
        )
    )

    assert "No repository gained stars." in rendered
    assert "| # | Repository |" not in rendered


def test_a_prerelease_is_marked() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", releases=[release("v2", prerelease=True)])]),
            snapshot([ok_entry("owner/one", releases=[])], day="2026-08-17"),
        )
    )

    assert "*(prerelease)*" in rendered


def test_a_release_without_a_url_is_still_listed() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", releases=[release("v2", html_url=None)])]),
            snapshot([ok_entry("owner/one", releases=[])], day="2026-08-17"),
        )
    )

    assert "`v2`" in rendered


def test_booleans_read_as_words() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", archived=True)]),
            snapshot([ok_entry("owner/one", archived=False)], day="2026-08-17"),
        )
    )

    assert "Archived: no → yes" in rendered


def test_a_removed_licence_is_not_rendered_as_the_word_none() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", license=None)]),
            snapshot([ok_entry("owner/one", license="MIT")], day="2026-08-17"),
        )
    )

    assert "License: MIT → *none*" in rendered


def test_a_long_description_is_truncated() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", description="x" * 200)]),
            snapshot([ok_entry("owner/one", description="short")], day="2026-08-17"),
        )
    )

    assert "…" in rendered
    assert "x" * 200 not in rendered


def test_a_rename_is_described_in_words() -> None:
    rendered = render_report(
        analyze(
            snapshot([ok_entry("owner/one", full_name="newowner/one")]),
            snapshot([ok_entry("owner/one", full_name="owner/one")], day="2026-08-17"),
        )
    )

    assert "Owner: owner → newowner" in rendered


def test_report_path_is_year_month_day() -> None:
    assert report_path(Path("reports"), date(2026, 8, 17)) == Path("reports/2026/08/17.md")


def test_writing_a_report_creates_directories(tmp_path: Path) -> None:
    destination = report_path(tmp_path, date(2026, 8, 18))
    write_report(full_analysis(), destination)

    assert destination.read_text(encoding="utf-8").startswith("# ghistory — 2026-08-18")
    assert destination.stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize(
    "heading",
    [
        "## Summary",
        "## Fastest growing",
        "## New releases",
        "## Significant changes",
        "## Languages",
    ],
)
def test_every_section_is_always_present(heading: str) -> None:
    assert heading in render_report(analyze(snapshot([ok_entry("owner/one")]), None))
