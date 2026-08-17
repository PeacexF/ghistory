from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ghistory.analyzer import Analysis, FieldChange, RepositoryDelta
from ghistory.storage import write_atomic

FIELD_LABELS = {
    "license": "License",
    "default_branch": "Default branch",
    "description": "Description",
    "archived": "Archived",
    "disabled": "Disabled",
    "owner": "Owner",
    "name": "Name",
}
DESCRIPTION_LIMIT = 80


def report_path(reports_dir: Path, observation_date: date) -> Path:
    year, month, day = f"{observation_date:%Y}", f"{observation_date:%m}", f"{observation_date:%d}"
    return reports_dir / year / month / f"{day}.md"


def write_report(analysis: Analysis, path: Path) -> None:
    write_atomic(path, render_report(analysis))


def render_report(analysis: Analysis) -> str:
    sections = [
        _heading(analysis),
        _summary(analysis),
        _failures(analysis),
        _growth(analysis),
        _releases(analysis),
        _significant_changes(analysis),
        _languages(analysis),
        _footer(),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def _heading(analysis: Analysis) -> str:
    if analysis.previous_date is None:
        return f"# ghistory — {analysis.date}\n\nFirst observation; nothing to compare against yet."
    return f"# ghistory — {analysis.date}\n\nCompared with {analysis.previous_date}."


def _summary(analysis: Analysis) -> str:
    growing = sum(1 for delta in analysis.deltas if (delta.star_delta or 0) > 0)
    lines = [
        "## Summary",
        "",
        f"- Tracked repositories: {analysis.counts.get('requested', 0):,}",
        f"- Collected: {analysis.counts.get('ok', 0):,}",
    ]
    if analysis.counts.get("failed", 0):
        lines.append(f"- Failed: {analysis.counts['failed']:,}")
    lines += [
        f"- Repositories growing: {growing:,}",
        f"- New releases: {len(analysis.new_releases):,}",
        f"- Significant changes: {len(analysis.significant_changes):,}",
        f"- Collection status: {analysis.status.upper()}",
    ]
    return "\n".join(lines)


def _failures(analysis: Analysis) -> str:
    if not analysis.failures:
        return ""
    lines = [
        "## Incomplete collection",
        "",
        "These repositories were not observed on this date:",
        "",
    ]
    lines += [f"- `{failure.slug}` — {failure.error}" for failure in analysis.failures]
    return "\n".join(lines)


def _growth(analysis: Analysis) -> str:
    lines = ["## Fastest growing", ""]
    if analysis.previous_date is None:
        return "\n".join([*lines, "No previous snapshot, so no growth can be measured yet."])
    if not analysis.top_growth:
        return "\n".join([*lines, "No repository gained stars."])

    lines += ["| # | Repository | Stars | Change |", "| --: | --- | --: | --: |"]
    for rank, delta in enumerate(analysis.top_growth, start=1):
        change = delta.change("stars")
        if change is None:
            continue
        lines.append(f"| {rank} | {_link(delta)} | {change.after:,} | +{change.delta:,} |")
    return "\n".join(lines)


def _releases(analysis: Analysis) -> str:
    lines = ["## New releases", ""]
    if not analysis.new_releases:
        return "\n".join([*lines, "None."])

    for release in analysis.new_releases:
        label = f"`{release.tag_name}`"
        if release.html_url:
            label = f"[{release.tag_name}]({release.html_url})"
        suffix = " *(prerelease)*" if release.prerelease else ""
        lines.append(f"- **{release.full_name}** — {label}{suffix}")
    return "\n".join(lines)


def _significant_changes(analysis: Analysis) -> str:
    lines = ["## Significant changes", ""]
    if not analysis.significant_changes:
        return "\n".join([*lines, "None."])

    for entry in analysis.significant_changes:
        lines.append(f"### {entry.full_name}")
        lines.append("")
        lines += [f"- {_describe(change)}" for change in entry.changes]
        lines.append("")
    return "\n".join(lines).rstrip()


def _languages(analysis: Analysis) -> str:
    lines = ["## Languages", ""]
    if not analysis.languages:
        return "\n".join([*lines, "Nothing observed."])

    lines += ["| Language | Repositories |", "| --- | --: |"]
    lines += [f"| {language} | {count:,} |" for language, count in analysis.languages]
    lines.append("")
    lines.append("Counted across the tracked set only, by primary language.")
    return "\n".join(lines)


def _footer() -> str:
    return (
        "---\n\n"
        "Values are point-in-time observations from a single daily collection run, "
        "not a complete record of everything that happened that day."
    )


def _link(delta: RepositoryDelta) -> str:
    return f"[{delta.full_name}](https://github.com/{delta.full_name})"


def _describe(change: FieldChange) -> str:
    label = FIELD_LABELS.get(change.field, change.field)
    return f"{label}: {_value(change.before)} → {_value(change.after)}"


def _value(value: Any) -> str:
    if value is None:
        return "*none*"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    if len(text) > DESCRIPTION_LIMIT:
        text = text[: DESCRIPTION_LIMIT - 1].rstrip() + "…"
    return text
