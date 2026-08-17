# Configuration

Three things configure a run: the repository list, the settings file, and a token.

```text
config/
├── repositories.txt    what to observe
└── settings.json       how to observe it
.env                    GITHUB_TOKEN (git-ignored)
```

---

## `config/repositories.txt`

One `owner/name` per line. Blank lines and `#` comments are ignored.

```text
# --- Rust ---
rust-lang/rust
tokio-rs/tokio
BurntSushi/ripgrep
```

Rules enforced at load time:

- Every non-comment line must match `owner/name`. A malformed line aborts the run
  **with its line number**, before any request is made.
- Duplicates are dropped case-insensitively, since GitHub treats `Owner/Repo` and
  `owner/repo` as the same repository.
- An empty list is an error.

### Adding and removing

**Adding** a repository starts its history from the next run. Nothing is backfilled,
and its existing releases are not reported as new — a repository with no previous
observation is deliberately skipped by release detection.

**Removing** one stops collection but leaves every past snapshot untouched. The
history remains queryable; it simply stops growing.

**Do not edit a line to follow a rename.** GitHub redirects renamed repositories
indefinitely, so the original slug keeps working and keeps the history joined. The
new name is recorded in `full_name`, and the rename appears in that day's report.
Editing the line instead starts a fresh, disconnected history. See
[Data format](data-format.md#slug-vs-full_name).

---

## `config/settings.json`

```json
{
  "max_releases_per_repository": 10,
  "top_growth_limit": 10,
  "discovery_enabled": false,
  "request_timeout_seconds": 20,
  "max_attempts": 3
}
```

| Key | Type | Default | Effect |
| --- | --- | --- | --- |
| `max_releases_per_repository` | int ≥ 1 | 10 | Releases stored per repository per day. Dominates snapshot size. |
| `top_growth_limit` | int ≥ 1 | 10 | Rows in the report's growth table. |
| `discovery_enabled` | bool | `false` | **Reserved.** Accepted and validated, but nothing reads it yet — repository discovery is a 0.2 feature. |
| `request_timeout_seconds` | number > 0 | 20 | Per-request timeout. |
| `max_attempts` | int ≥ 1 | 3 | Total attempts per request, not retries after the first. `3` means try three times. |

Every key is optional; omitted keys take the default. An empty `{}` is valid.

**Unknown keys are an error, not a warning.** A typo such as
`max_release_per_repository` would otherwise be silently ignored, leaving you with a
setting you believe is applied and data collected under the default. The run stops
and names the offending key.

### Snapshot size

`max_releases_per_repository` is the main lever. At 10 releases across 54
repositories a snapshot is roughly 195 KB, of which release objects are about 85%.
Compressed in git that is around 23 KB per day — under 10 MB a year before git's
delta compression across near-identical consecutive days. Halving the release count
roughly halves the file.

---

## Token

ghistory reads only public data. The token exists purely to raise the rate limit
from 60 requests/hour to 5,000.

**It needs no scopes and no repository access.**

- **Fine-grained PAT** — resource owner: your account; repository access: *Public
  repositories (read-only)*; add no permissions.
- **Classic PAT** — every scope box left unchecked.

Never grant `repo`, `workflow`, or `delete_repo`. A leaked token with `repo` could
write to your repositories; this tool only ever reads.

### Supplying it

```bash
# a .env file at the repository root, loaded by run.sh
echo "GITHUB_TOKEN=your_token" > .env

# or the environment directly
export GITHUB_TOKEN=your_token
```

`.env` is git-ignored, and CI runs a secret scan over the full history on every push.

In GitHub Actions no token is configured at all: the workflow uses the built-in
`secrets.GITHUB_TOKEN`, which allows 1,000 requests/hour per repository against the
~108 a daily run needs.

---

## Command line

```bash
./run.sh [options]          # validates the environment, then runs the collector
```

| Option | Effect |
| --- | --- |
| `--date YYYY-MM-DD` | Observation date. Defaults to today in UTC. |
| `--dry-run` | Collect and print a summary; write nothing. |
| `--repair` | Overwrite an existing snapshot for that date. |
| `--report-only` | Rebuild the report from stored snapshots. Makes no API calls. |
| `--config-dir PATH` | Default `config`. |
| `--data-dir PATH` | Default `data`. |
| `--reports-dir PATH` | Default `reports`. |
| `--version` | Print the collector version. |

`--dry-run`, `--repair`, and `--report-only` are mutually exclusive in the
combinations that would contradict each other; the parser rejects those with exit 2.

Without any flags the run is idempotent: if today's snapshot exists, it reports that
and stops without touching the API.

---

## Workflow inputs

`.github/workflows/daily.yml` runs on cron and accepts two inputs when dispatched
manually from the Actions tab:

| Input | Default | Effect |
| --- | --- | --- |
| `date` | today, UTC | Passed through as `--date`. |
| `repair` | `false` | Adds `--repair`. |

Both are read through the environment rather than interpolated into the shell.

---

## Development

```bash
make sync      # install the locked environment
make ci        # lint, format check, types, tests — exactly what CI runs
make dry-run   # collect against the live API, write nothing
```

`make` on its own lists every target.

See also: [Operations](operations.md) · [Architecture](architecture.md)
