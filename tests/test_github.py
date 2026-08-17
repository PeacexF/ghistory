from __future__ import annotations

import pytest
import requests

from ghistory.github import GitHubClient, GitHubError, RateLimitError
from support import TOKEN, build_client, make_response


def test_get_repository_returns_payload() -> None:
    client, adapter, _ = build_client([make_response(200, {"full_name": "rust-lang/rust"})])

    assert client.get_repository("rust-lang/rust")["full_name"] == "rust-lang/rust"
    assert adapter.requests[0].url == "https://api.github.com/repos/rust-lang/rust"


def test_request_carries_auth_and_version_headers() -> None:
    client, adapter, _ = build_client([make_response(200, {})])
    client.get_repository("owner/name")

    headers = adapter.requests[0].headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["User-Agent"].startswith("ghistory/")


def test_timeout_is_passed_to_every_request() -> None:
    client, adapter, _ = build_client([make_response(200, {})], timeout=7.5)
    client.get_repository("owner/name")

    assert adapter.timeouts == [7.5]


def test_get_releases_requests_page_size_and_truncates() -> None:
    releases = [{"tag_name": f"v{i}"} for i in range(5)]
    client, adapter, _ = build_client([make_response(200, releases)])

    assert len(client.get_releases("owner/name", limit=3)) == 3
    assert adapter.requests[0].url == "https://api.github.com/repos/owner/name/releases?per_page=3"


def test_get_releases_clamps_page_size_to_the_api_maximum() -> None:
    client, adapter, _ = build_client([make_response(200, [])])
    client.get_releases("owner/name", limit=500)

    assert adapter.requests[0].url is not None
    assert "per_page=100" in adapter.requests[0].url


def test_not_found_is_not_retried() -> None:
    client, adapter, slept = build_client([make_response(404, {"message": "Not Found"})])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/gone")

    assert excinfo.value.kind == "not_found"
    assert len(adapter.requests) == 1
    assert slept == []


def test_unauthorized_is_not_retried() -> None:
    client, adapter, _ = build_client([make_response(401, {"message": "Bad credentials"})])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "unauthorized"
    assert len(adapter.requests) == 1


def test_dmca_blocked_repository_is_reported_as_unavailable() -> None:
    client, _, _ = build_client([make_response(451, {"message": "Repository access blocked"})])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/blocked")

    assert excinfo.value.kind == "unavailable"


def test_server_errors_are_retried_then_succeed() -> None:
    client, adapter, slept = build_client(
        [
            make_response(500, {"message": "boom"}),
            make_response(502, {"message": "boom"}),
            make_response(200, {"full_name": "owner/name"}),
        ]
    )

    assert client.get_repository("owner/name")["full_name"] == "owner/name"
    assert len(adapter.requests) == 3
    assert slept == [1.0, 2.0]


def test_server_errors_give_up_after_max_attempts() -> None:
    client, adapter, _ = build_client(
        [make_response(503, {"message": "boom"}) for _ in range(3)],
    )

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "server_error"
    assert len(adapter.requests) == 3


def test_network_failures_are_retried_then_reported() -> None:
    client, adapter, slept = build_client(
        [
            requests.ConnectionError("no route"),
            requests.Timeout("too slow"),
            requests.ConnectionError("no route"),
        ]
    )

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "network"
    assert len(adapter.requests) == 3
    assert slept == [1.0, 2.0]


def test_max_attempts_of_one_disables_retrying() -> None:
    client, adapter, slept = build_client([make_response(500, {})], max_attempts=1)

    with pytest.raises(GitHubError):
        client.get_repository("owner/name")

    assert len(adapter.requests) == 1
    assert slept == []


def test_exhausted_quota_is_reported_as_rate_limit() -> None:
    client, adapter, _ = build_client(
        [
            make_response(
                403,
                {"message": "API rate limit exceeded"},
                {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4000"},
            )
        ]
    )

    with pytest.raises(RateLimitError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "rate_limit"
    assert excinfo.value.reset_at == 4000
    assert len(adapter.requests) == 1


def test_forbidden_without_quota_headers_is_not_a_rate_limit() -> None:
    client, _, _ = build_client([make_response(403, {"message": "Forbidden"})])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "unauthorized"


def test_further_requests_stop_before_hitting_a_known_exhausted_quota() -> None:
    client, adapter, _ = build_client(
        [
            make_response(
                403,
                {"message": "API rate limit exceeded"},
                {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4000"},
            )
        ],
        now=lambda: 1000.0,
    )

    with pytest.raises(RateLimitError):
        client.get_repository("owner/first")
    with pytest.raises(RateLimitError):
        client.get_repository("owner/second")

    assert len(adapter.requests) == 1


def test_requests_resume_once_the_reset_time_has_passed() -> None:
    client, _adapter, _ = build_client(
        [
            make_response(
                403,
                {"message": "API rate limit exceeded"},
                {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "4000"},
            ),
            make_response(200, {"full_name": "owner/second"}, {"x-ratelimit-remaining": "60"}),
        ],
        now=lambda: 5000.0,
    )

    with pytest.raises(RateLimitError):
        client.get_repository("owner/first")

    assert client.get_repository("owner/second")["full_name"] == "owner/second"


def test_secondary_rate_limit_waits_for_retry_after_then_retries() -> None:
    client, adapter, slept = build_client(
        [
            make_response(429, {"message": "slow down"}, {"retry-after": "5"}),
            make_response(200, {"full_name": "owner/name"}, {"x-ratelimit-remaining": "10"}),
        ]
    )

    assert client.get_repository("owner/name")["full_name"] == "owner/name"
    assert slept == [5.0]
    assert len(adapter.requests) == 2


def test_a_long_retry_after_is_not_waited_out() -> None:
    client, adapter, slept = build_client(
        [make_response(429, {"message": "slow down"}, {"retry-after": "3600"})]
    )

    with pytest.raises(RateLimitError):
        client.get_repository("owner/name")

    assert slept == []
    assert len(adapter.requests) == 1


def test_rate_limit_headers_are_tracked() -> None:
    client, _, _ = build_client(
        [make_response(200, {}, {"x-ratelimit-remaining": "4321", "x-ratelimit-reset": "9999"})]
    )
    client.get_repository("owner/name")

    assert client.rate_limit_remaining == 4321
    assert client.rate_limit_reset == 9999


def test_garbage_rate_limit_headers_are_ignored() -> None:
    client, _, _ = build_client([make_response(200, {}, {"x-ratelimit-remaining": "soon"})])
    client.get_repository("owner/name")

    assert client.rate_limit_remaining is None


def test_non_json_body_is_reported_as_invalid() -> None:
    client, _, _ = build_client([make_response(200, raw_body="<html>502 Bad Gateway</html>")])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "invalid_response"


def test_unexpected_shape_is_reported_as_invalid() -> None:
    client, _, _ = build_client([make_response(200, ["not", "an", "object"])])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert excinfo.value.kind == "invalid_response"


def test_releases_reject_malformed_entries() -> None:
    client, _, _ = build_client([make_response(200, [{"tag_name": "v1"}, "nope"])])

    with pytest.raises(GitHubError) as excinfo:
        client.get_releases("owner/name")

    assert excinfo.value.kind == "invalid_response"


def test_empty_token_is_refused() -> None:
    with pytest.raises(GitHubError) as excinfo:
        GitHubClient("")

    assert excinfo.value.kind == "unauthorized"


def test_from_env_requires_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with pytest.raises(GitHubError) as excinfo:
        GitHubClient.from_env()

    assert excinfo.value.kind == "unauthorized"


def test_from_env_reads_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)

    with GitHubClient.from_env() as client:
        assert repr(client) == "<GitHubClient remaining=None>"


def test_token_never_appears_in_errors_or_repr() -> None:
    client, _, _ = build_client([make_response(404, {"message": "Not Found"})])

    with pytest.raises(GitHubError) as excinfo:
        client.get_repository("owner/name")

    assert TOKEN not in str(excinfo.value)
    assert TOKEN not in repr(client)
