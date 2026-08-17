from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, Literal

import requests

from ghistory import __version__

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"
USER_AGENT = f"ghistory/{__version__}"

# Stored verbatim in snapshots, so these strings are part of the data format.
ErrorKind = Literal[
    "not_found",
    "unauthorized",
    "rate_limit",
    "unavailable",
    "server_error",
    "network",
    "invalid_response",
    "http_error",
]

RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
MAX_PER_PAGE = 100

MAX_RETRY_AFTER_SECONDS = 60.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0


class GitHubError(Exception):
    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind


class RateLimitError(GitHubError):
    def __init__(self, message: str, reset_at: int | None = None) -> None:
        super().__init__("rate_limit", message)
        self.reset_at = reset_at


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        timeout: float = 20.0,
        max_attempts: int = 3,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        if not token:
            raise GitHubError("unauthorized", "a GitHub token is required")

        self.rate_limit_remaining: int | None = None
        self.rate_limit_reset: int | None = None

        self._timeout = timeout
        self._max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._now = now
        self._session = session if session is not None else requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": USER_AGENT,
            }
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> GitHubClient:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise GitHubError("unauthorized", "GITHUB_TOKEN is not set")
        return cls(token, **kwargs)

    # Keep the token out of tracebacks and logs.
    def __repr__(self) -> str:
        return f"<GitHubClient remaining={self.rate_limit_remaining}>"

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def get_repository(self, slug: str) -> dict[str, Any]:
        payload = self._get(f"/repos/{slug}")
        if not isinstance(payload, dict):
            raise GitHubError("invalid_response", f"{slug}: expected an object")
        return payload

    def get_releases(self, slug: str, limit: int = 10) -> list[dict[str, Any]]:
        per_page = min(max(limit, 1), MAX_PER_PAGE)
        payload = self._get(f"/repos/{slug}/releases", {"per_page": per_page})
        if not isinstance(payload, list):
            raise GitHubError("invalid_response", f"{slug}: expected a list of releases")
        releases = [item for item in payload if isinstance(item, dict)]
        if len(releases) != len(payload):
            raise GitHubError("invalid_response", f"{slug}: malformed release entry")
        return releases[:limit]

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self._guard_rate_limit(path)

        url = f"{API_ROOT}{path}"
        last_error: GitHubError | None = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                last_error = GitHubError("network", f"{path}: {type(exc).__name__}")
            else:
                self._record_rate_limit(response)

                if response.status_code == 200:
                    return self._decode(response, path)

                error = self._classify(response, path)
                retry_after = self._retry_after(response)
                if (
                    error.kind == "rate_limit"
                    and retry_after is not None
                    and retry_after <= MAX_RETRY_AFTER_SECONDS
                    and attempt < self._max_attempts
                ):
                    self._sleep(retry_after)
                    continue

                if response.status_code not in RETRYABLE_STATUS:
                    raise error

                last_error = error

            if attempt < self._max_attempts:
                self._sleep(self._backoff(attempt))

        assert last_error is not None
        raise last_error

    def _guard_rate_limit(self, path: str) -> None:
        if self.rate_limit_remaining is None or self.rate_limit_remaining > 0:
            return
        reset = self.rate_limit_reset
        if reset is not None and reset <= self._now():
            return
        raise RateLimitError(f"{path}: rate limit exhausted", reset)

    def _record_rate_limit(self, response: requests.Response) -> None:
        self.rate_limit_remaining = _header_int(response, "x-ratelimit-remaining")
        self.rate_limit_reset = _header_int(response, "x-ratelimit-reset")

    def _classify(self, response: requests.Response, path: str) -> GitHubError:
        status = response.status_code
        detail = f"{path}: HTTP {status}"

        if status in (403, 429):
            # 403 covers both "out of quota" and plain forbidden; only the headers tell them apart.
            if self.rate_limit_remaining == 0 or self._retry_after(response) is not None:
                return RateLimitError(detail, self.rate_limit_reset)
            return GitHubError("unauthorized", detail)
        if status == 401:
            return GitHubError("unauthorized", detail)
        if status == 404:
            return GitHubError("not_found", detail)
        if status == 451:
            return GitHubError("unavailable", detail)
        if status >= 500:
            return GitHubError("server_error", detail)
        return GitHubError("http_error", detail)

    def _decode(self, response: requests.Response, path: str) -> Any:
        try:
            return response.json()
        except ValueError:
            raise GitHubError("invalid_response", f"{path}: response was not JSON") from None

    def _retry_after(self, response: requests.Response) -> float | None:
        raw = response.headers.get("retry-after")
        if raw is None:
            return None
        try:
            return max(float(raw), 0.0)
        except ValueError:
            return None

    def _backoff(self, attempt: int) -> float:
        return min(BACKOFF_BASE_SECONDS * (1 << (attempt - 1)), BACKOFF_CAP_SECONDS)


def _header_int(response: requests.Response, name: str) -> int | None:
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
