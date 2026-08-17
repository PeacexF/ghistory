from __future__ import annotations

from pathlib import Path

import pytest

from support import TOKEN


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    (config / "repositories.txt").write_text("owner/one\n", encoding="utf-8")
    (config / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    return tmp_path
