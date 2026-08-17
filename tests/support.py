from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import requests
from requests.adapters import BaseAdapter
from requests.models import PreparedRequest, Response

from ghistory.github import GitHubClient

TOKEN = "ghp_notarealtoken"


def make_response(
    status: int,
    body: Any = None,
    headers: Mapping[str, str] | None = None,
    *,
    raw_body: str | None = None,
) -> Response:
    response = Response()
    response.status_code = status
    response.headers.update(headers or {})
    text = raw_body if raw_body is not None else json.dumps(body)
    response._content = text.encode()
    return response


class StubAdapter(BaseAdapter):
    def __init__(self, outcomes: Sequence[Response | Exception]) -> None:
        super().__init__()
        self.outcomes = list(outcomes)
        self.requests: list[PreparedRequest] = []
        self.timeouts: list[Any] = []

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: Any = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.outcomes:
            raise AssertionError("unexpected extra request")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        outcome.request = request
        outcome.url = request.url or ""
        return outcome

    def close(self) -> None:
        return None


def build_client(
    outcomes: Sequence[Response | Exception],
    **kwargs: Any,
) -> tuple[GitHubClient, StubAdapter, list[float]]:
    adapter = StubAdapter(outcomes)
    session = requests.Session()
    session.mount("https://", adapter)
    slept: list[float] = []
    client = GitHubClient(TOKEN, session=session, sleep=slept.append, **kwargs)
    return client, adapter, slept


def repository_payload(slug: str, **overrides: Any) -> dict[str, Any]:
    owner, name = slug.split("/")
    payload: dict[str, Any] = {
        "full_name": slug,
        "name": name,
        "owner": {"login": owner},
        "description": f"{name} description",
        "html_url": f"https://github.com/{slug}",
        "created_at": "2010-06-16T20:39:03Z",
        "updated_at": "2026-08-16T23:51:00Z",
        "pushed_at": "2026-08-16T23:48:00Z",
        "default_branch": "main",
        "language": "Rust",
        "license": {"key": "mit", "spdx_id": "MIT"},
        "topics": ["compiler", "rust"],
        "stargazers_count": 112340,
        "watchers_count": 112340,
        "forks_count": 14782,
        "open_issues_count": 1251,
        "subscribers_count": 4812,
        "size": 1234567,
        "archived": False,
        "disabled": False,
    }
    payload.update(overrides)
    return payload


def release_payload(tag: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tag_name": tag,
        "name": f"Release {tag}",
        "published_at": "2026-08-16T12:00:00Z",
        "created_at": "2026-08-16T11:00:00Z",
        "prerelease": False,
        "draft": False,
        "html_url": f"https://github.com/owner/name/releases/tag/{tag}",
        "body": "release notes we do not keep",
        "assets": [{"name": "binary.tar.gz"}],
    }
    payload.update(overrides)
    return payload
