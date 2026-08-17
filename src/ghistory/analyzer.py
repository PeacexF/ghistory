from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ghistory import SCHEMA_VERSION

METRICS = ("stars", "forks", "open_issues", "subscribers")
WATCHED_FIELDS = ("license", "default_branch", "description", "archived", "disabled")
UNKNOWN_LANGUAGE = "Unknown"
SNAPSHOT_GLOB = "[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9].json"


class AnalysisError(Exception):
    pass


@dataclass(frozen=True)
class MetricChange:
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before


@dataclass(frozen=True)
class RepositoryDelta:
    slug: str
    full_name: str
    metrics: dict[str, MetricChange]

    def change(self, metric: str) -> MetricChange | None:
        return self.metrics.get(metric)

    @property
    def star_delta(self) -> int | None:
        change = self.metrics.get("stars")
        return None if change is None else change.delta


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass(frozen=True)
class SignificantChange:
    slug: str
    full_name: str
    changes: list[FieldChange]


@dataclass(frozen=True)
class NewRelease:
    slug: str
    full_name: str
    tag_name: str
    name: str | None
    html_url: str | None
    published_at: str | None
    prerelease: bool


@dataclass(frozen=True)
class Failure:
    slug: str
    error: str


@dataclass(frozen=True)
class Analysis:
    date: str
    previous_date: str | None
    status: str
    counts: dict[str, int]
    deltas: list[RepositoryDelta]
    top_growth: list[RepositoryDelta]
    languages: list[tuple[str, int]]
    new_releases: list[NewRelease]
    significant_changes: list[SignificantChange]
    failures: list[Failure]


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AnalysisError(f"{path}: no such file") from None
    except ValueError as exc:
        raise AnalysisError(f"{path}: invalid JSON ({exc})") from None

    if not isinstance(raw, dict) or not isinstance(raw.get("repositories"), list):
        raise AnalysisError(f"{path}: not a snapshot")

    version = raw.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise AnalysisError(f"{path}: unsupported schema_version {version!r}")

    return raw


def snapshot_dates(data_dir: Path) -> list[date]:
    dates: list[date] = []
    for path in data_dir.glob(SNAPSHOT_GLOB):
        try:
            dates.append(date(int(path.parts[-3]), int(path.parts[-2]), int(path.stem)))
        except ValueError:
            continue
    return sorted(dates)


def find_previous_snapshot(data_dir: Path, observation_date: date) -> Path | None:
    earlier = [day for day in snapshot_dates(data_dir) if day < observation_date]
    if not earlier:
        return None
    previous = earlier[-1]
    return data_dir / f"{previous:%Y}" / f"{previous:%m}" / f"{previous:%d}.json"


def analyze(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    top_growth_limit: int = 10,
) -> Analysis:
    entries = _by_slug(current)
    earlier = _by_slug(previous) if previous is not None else {}

    deltas = _deltas(entries, earlier)
    growing = [delta for delta in deltas if (delta.star_delta or 0) > 0]
    growing.sort(key=lambda delta: (-(delta.star_delta or 0), delta.slug.lower()))

    return Analysis(
        date=str(current.get("date", "")),
        previous_date=None if previous is None else str(previous.get("date", "")),
        status=str(current.get("status", "")),
        counts=dict(current.get("counts", {})),
        deltas=deltas,
        top_growth=growing[:top_growth_limit],
        languages=_languages(entries),
        new_releases=_new_releases(entries, earlier),
        significant_changes=_significant_changes(entries, earlier),
        failures=_failures(entries),
    )


def _by_slug(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["slug"]): entry for entry in snapshot["repositories"]}


def _ok(entry: dict[str, Any]) -> bool:
    return entry.get("status") == "ok"


def _full_name(entry: dict[str, Any]) -> str:
    return str(entry.get("full_name") or entry["slug"])


def _deltas(
    entries: dict[str, dict[str, Any]],
    earlier: dict[str, dict[str, Any]],
) -> list[RepositoryDelta]:
    deltas: list[RepositoryDelta] = []
    for slug in sorted(entries, key=str.lower):
        entry = entries[slug]
        if not _ok(entry):
            continue

        before = earlier.get(slug)
        metrics: dict[str, MetricChange] = {}
        if before is not None and _ok(before):
            for metric in METRICS:
                # A metric missing on either day has no delta; it is not zero.
                if isinstance(entry.get(metric), int) and isinstance(before.get(metric), int):
                    metrics[metric] = MetricChange(before[metric], entry[metric])

        deltas.append(RepositoryDelta(slug, _full_name(entry), metrics))
    return deltas


def _languages(entries: dict[str, dict[str, Any]]) -> list[tuple[str, int]]:
    counter = Counter(
        str(entry.get("language") or UNKNOWN_LANGUAGE) for entry in entries.values() if _ok(entry)
    )
    return sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))


def _new_releases(
    entries: dict[str, dict[str, Any]],
    earlier: dict[str, dict[str, Any]],
) -> list[NewRelease]:
    releases: list[NewRelease] = []
    for slug in sorted(entries, key=str.lower):
        entry = entries[slug]
        before = earlier.get(slug)
        # Without a readable baseline every tag looks new
        if not _ok(entry) or before is None or not _ok(before):
            continue
        if "releases" not in entry or "releases" not in before:
            continue

        known = {release.get("tag_name") for release in before["releases"]}
        for release in entry["releases"]:
            tag = release.get("tag_name")
            if tag is None or tag in known:
                continue
            releases.append(
                NewRelease(
                    slug=slug,
                    full_name=_full_name(entry),
                    tag_name=str(tag),
                    name=release.get("name"),
                    html_url=release.get("html_url"),
                    published_at=release.get("published_at"),
                    prerelease=bool(release.get("prerelease")),
                )
            )
    return releases


def _significant_changes(
    entries: dict[str, dict[str, Any]],
    earlier: dict[str, dict[str, Any]],
) -> list[SignificantChange]:
    significant: list[SignificantChange] = []
    for slug in sorted(entries, key=str.lower):
        entry = entries[slug]
        before = earlier.get(slug)
        if not _ok(entry) or before is None or not _ok(before):
            continue

        changes = [
            FieldChange(field, before.get(field), entry.get(field))
            for field in WATCHED_FIELDS
            if before.get(field) != entry.get(field)
        ]
        changes.extend(_identity_changes(before, entry))

        if changes:
            significant.append(SignificantChange(slug, _full_name(entry), changes))
    return significant


def _identity_changes(before: dict[str, Any], entry: dict[str, Any]) -> list[FieldChange]:
    previous_name = _full_name(before)
    current_name = _full_name(entry)
    if previous_name == current_name:
        return []

    previous_owner, _, previous_repo = previous_name.partition("/")
    current_owner, _, current_repo = current_name.partition("/")

    changes = []
    if previous_owner != current_owner:
        changes.append(FieldChange("owner", previous_owner, current_owner))
    if previous_repo != current_repo:
        changes.append(FieldChange("name", previous_repo, current_repo))
    return changes


def _failures(entries: dict[str, dict[str, Any]]) -> list[Failure]:
    return [
        Failure(slug, str(entry.get("error", "unknown")))
        for slug, entry in sorted(entries.items(), key=lambda item: item[0].lower())
        if entry.get("status") == "error"
    ]
