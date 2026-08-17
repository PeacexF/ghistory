from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SLUG = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def tracked_slugs() -> list[str]:
    lines = (CONFIG_DIR / "repositories.txt").read_text(encoding="utf-8").splitlines()
    return [
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def test_every_line_is_an_owner_name_slug() -> None:
    bad = [slug for slug in tracked_slugs() if not SLUG.match(slug)]
    assert bad == []


def test_no_duplicate_repositories() -> None:
    slugs = tracked_slugs()
    duplicates = {slug for slug in slugs if slugs.count(slug) > 1}
    assert duplicates == set()


def test_slugs_are_case_insensitively_unique() -> None:
    lowered = [slug.lower() for slug in tracked_slugs()]
    duplicates = {slug for slug in lowered if lowered.count(slug) > 1}
    assert duplicates == set()


def test_repository_list_is_not_empty() -> None:
    assert len(tracked_slugs()) > 0


def test_settings_json_is_valid_and_complete() -> None:
    settings = json.loads((CONFIG_DIR / "settings.json").read_text(encoding="utf-8"))
    assert settings["max_releases_per_repository"] > 0
    assert settings["top_growth_limit"] > 0
    assert settings["request_timeout_seconds"] > 0
    assert settings["max_attempts"] >= 1
    assert isinstance(settings["discovery_enabled"], bool)
