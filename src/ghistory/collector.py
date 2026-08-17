from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ghistory import SCHEMA_VERSION, __version__
from ghistory.github import GitHubClient, GitHubError

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
RELEASE_FIELDS = (
    "tag_name",
    "name",
    "published_at",
    "created_at",
    "prerelease",
    "draft",
    "html_url",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    max_releases_per_repository: int = 10
    top_growth_limit: int = 10
    discovery_enabled: bool = False
    request_timeout_seconds: float = 20.0
    max_attempts: int = 3


BOOL_SETTINGS = frozenset({"discovery_enabled"})
INT_SETTINGS = frozenset({"max_releases_per_repository", "top_growth_limit", "max_attempts"})
FLOAT_SETTINGS = frozenset({"request_timeout_seconds"})


def load_settings(path: Path) -> Settings:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path}: no such file") from None
    except ValueError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from None

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a JSON object")

    unknown = sorted(set(raw) - BOOL_SETTINGS - INT_SETTINGS - FLOAT_SETTINGS)
    if unknown:
        raise ConfigError(f"{path}: unknown setting(s): {', '.join(unknown)}")

    values: dict[str, Any] = {}
    for name, value in raw.items():
        if name in BOOL_SETTINGS:
            if not isinstance(value, bool):
                raise ConfigError(f"{path}: {name} must be true or false")
            values[name] = value
        elif name in INT_SETTINGS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ConfigError(f"{path}: {name} must be a positive integer")
            values[name] = value
        else:
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise ConfigError(f"{path}: {name} must be a positive number")
            values[name] = float(value)

    return Settings(**values)


def load_repositories(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"{path}: no such file") from None

    slugs: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        slug = line.strip()
        if not slug or slug.startswith("#"):
            continue
        if not SLUG_PATTERN.match(slug):
            raise ConfigError(f"{path}:{number}: {slug!r} is not owner/name")
        # GitHub is case-insensitive here, so two casings are one repository.
        if slug.lower() in seen:
            continue
        seen.add(slug.lower())
        slugs.append(slug)

    if not slugs:
        raise ConfigError(f"{path}: no repositories listed")
    return slugs


def normalize_release(payload: dict[str, Any]) -> dict[str, Any]:
    return {field: payload.get(field) for field in RELEASE_FIELDS}


def normalize_repository(
    slug: str,
    payload: dict[str, Any],
    releases: list[dict[str, Any]] | None,
    releases_error: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "slug": slug,
        "status": "ok",
        "full_name": _text(payload, "full_name", slug) or slug,
        "description": _text(payload, "description", slug),
        "language": _text(payload, "language", slug),
        "license": _license(payload, slug),
        "default_branch": _text(payload, "default_branch", slug),
        "topics": _topics(payload, slug),
        "stars": _count(payload, "stargazers_count", slug),
        "forks": _count(payload, "forks_count", slug),
        "open_issues": _count(payload, "open_issues_count", slug),
        "subscribers": _count(payload, "subscribers_count", slug),
        "size": _count(payload, "size", slug),
        "archived": _flag(payload, "archived", slug),
        "disabled": _flag(payload, "disabled", slug),
        "created_at": _text(payload, "created_at", slug),
        "updated_at": _text(payload, "updated_at", slug),
        "pushed_at": _text(payload, "pushed_at", slug),
    }

    # An unreadable release list is not an empty one, so the key stays absent.
    if releases_error is not None:
        entry["releases_error"] = releases_error
    else:
        entry["releases"] = [normalize_release(release) for release in releases or []]
    return entry


def collect(
    client: GitHubClient,
    slugs: Iterable[str],
    settings: Settings,
    *,
    observation_date: date,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    entries = [collect_repository(client, slug, settings) for slug in slugs]
    entries.sort(key=lambda entry: str(entry["slug"]).lower())

    ok = sum(1 for entry in entries if entry["status"] == "ok")
    failed = len(entries) - ok

    if failed == 0:
        status = "complete"
    elif ok == 0:
        status = "failed"
    else:
        status = "partial"

    return {
        "schema_version": SCHEMA_VERSION,
        "collector_version": __version__,
        "date": observation_date.isoformat(),
        "generated_at": _iso_utc(now()),
        "status": status,
        "counts": {"requested": len(entries), "ok": ok, "failed": failed},
        "repositories": entries,
    }


def collect_repository(client: GitHubClient, slug: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = client.get_repository(slug)
    except GitHubError as exc:
        return {"slug": slug, "status": "error", "error": exc.kind}

    releases: list[dict[str, Any]] | None = None
    releases_error: str | None = None
    try:
        releases = client.get_releases(slug, settings.max_releases_per_repository)
    except GitHubError as exc:
        releases_error = exc.kind

    try:
        return normalize_repository(slug, payload, releases, releases_error)
    except GitHubError as exc:
        return {"slug": slug, "status": "error", "error": exc.kind}


def snapshot_path(data_dir: Path, observation_date: date) -> Path:
    year, month, day = f"{observation_date:%Y}", f"{observation_date:%m}", f"{observation_date:%d}"
    return data_dir / year / month / f"{day}.json"


def render_snapshot(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_snapshot(snapshot: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(render_snapshot(snapshot))
        # mkstemp creates at 0600, which os.replace would carry over.
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(payload: dict[str, Any], key: str, slug: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise GitHubError("invalid_response", f"{slug}: {key} is not a string")


def _count(payload: dict[str, Any], key: str, slug: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise GitHubError("invalid_response", f"{slug}: {key} is not a number")
    return value


def _flag(payload: dict[str, Any], key: str, slug: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise GitHubError("invalid_response", f"{slug}: {key} is not a boolean")
    return value


def _license(payload: dict[str, Any], slug: str) -> str | None:
    value = payload.get("license")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise GitHubError("invalid_response", f"{slug}: license is not an object")
    spdx = value.get("spdx_id")
    if spdx is None or isinstance(spdx, str):
        return spdx
    raise GitHubError("invalid_response", f"{slug}: license.spdx_id is not a string")


def _topics(payload: dict[str, Any], slug: str) -> list[str]:
    value = payload.get("topics")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(topic, str) for topic in value):
        raise GitHubError("invalid_response", f"{slug}: topics is not a list of strings")
    return sorted(value)
