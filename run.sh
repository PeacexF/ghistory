#!/usr/bin/env bash
#
# ghistory entrypoint.
#
#   ./run.sh                    collect, analyze, report
#   ./run.sh --dry-run          contact the API, write nothing
#   ./run.sh --repair           overwrite an existing snapshot
#   ./run.sh --report-only      rebuild the report from stored snapshots, no API calls
#   ./run.sh --date 2026-08-17  use a specific UTC date
#
# Full reference: docs/configuration.md

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is not installed (https://docs.astral.sh/uv/)" >&2
    exit 1
fi

if [ -f .env ]; then
    set -a
    # shellcheck source=/dev/null
    . ./.env
    set +a
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
    echo "error: GITHUB_TOKEN is not set" >&2
    echo "       export GITHUB_TOKEN=... (a token with public read access is enough)" >&2
    exit 1
fi

exec uv run --frozen ghistory "$@"
