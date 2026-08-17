# Data format

Everything ghistory produces lives in two directories. `data/` holds observations
and is machine-readable; `reports/` holds the human-readable rendering of the
difference between two observations.

```text
data/2026/08/17.json      one immutable observation
reports/2026/08/17.md     derived from that day and the one before it
```

Paths are always `YYYY/MM/DD`, zero-padded, in UTC.

---

## Snapshot

```json
{
  "schema_version": 1,
  "collector_version": "0.1.0",
  "date": "2026-08-17",
  "generated_at": "2026-08-17T03:04:21Z",
  "status": "complete",
  "counts": { "requested": 54, "ok": 54, "failed": 0 },
  "repositories": [ ... ]
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Format of this file. Bumped only when a change would make older files ambiguous. |
| `collector_version` | string | Version of the collector that produced it. |
| `date` | string | Observation date, `YYYY-MM-DD`, UTC. Matches the file path. |
| `generated_at` | string | When the run finished, RFC 3339 UTC, second precision. |
| `status` | string | `complete`, `partial`, or `failed`. See below. |
| `counts` | object | `requested`, `ok`, `failed`. |
| `repositories` | array | One entry per configured repository, sorted by `slug`. |

### `status`

| Value | Meaning | Written to disk? |
| --- | --- | --- |
| `complete` | Every repository was observed. | yes |
| `partial` | Some succeeded, some failed. | yes |
| `failed` | Nothing succeeded. | **no** — the run exits non-zero instead |

`failed` exists in the schema but you will not find it in `data/`: a run that
collected nothing writes no file at all, so a failure can never be mistaken for a
day on which every repository lost all its stars.

---

## Repository entry — observed

```json
{
  "slug": "rust-lang/rust",
  "status": "ok",
  "full_name": "rust-lang/rust",
  "description": "Empowering everyone to build reliable and efficient software.",
  "language": "Rust",
  "license": "Apache-2.0",
  "default_branch": "main",
  "topics": ["compiler", "language", "rust"],
  "stars": 115528,
  "forks": 15423,
  "open_issues": 12722,
  "subscribers": 1550,
  "size": 970749,
  "archived": false,
  "disabled": false,
  "created_at": "2010-06-16T20:39:03Z",
  "updated_at": "2026-08-17T01:49:27Z",
  "pushed_at": "2026-08-16T22:37:24Z",
  "releases": [ ... ]
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `slug` | string | The line from `config/repositories.txt`. **The join key across days.** |
| `status` | string | `ok` here; `error` in the failed form below. |
| `full_name` | string | What GitHub actually returned. Differs from `slug` after a rename or transfer. |
| `description` | string \| null | |
| `language` | string \| null | GitHub's primary-language guess. `null` when it has none. |
| `license` | string \| null | SPDX id. `NOASSERTION` when a licence file exists but is unrecognised. |
| `default_branch` | string \| null | |
| `topics` | string[] | Sorted alphabetically, so upstream reordering does not churn the diff. |
| `stars` | int | |
| `forks` | int | |
| `open_issues` | int | **Includes pull requests** — see caveats. |
| `subscribers` | int | Real watcher count — see caveats. |
| `size` | int | Repository size in KB, as GitHub reports it. |
| `archived` | bool | |
| `disabled` | bool | |
| `created_at` | string \| null | RFC 3339 UTC, verbatim from the API. |
| `updated_at` | string \| null | Metadata change. |
| `pushed_at` | string \| null | Last push to any branch. |
| `releases` | array | Up to `max_releases_per_repository`, newest first. |

### `slug` vs `full_name`

`slug` is what you asked for; `full_name` is what GitHub gave back. GitHub follows
renames with redirects indefinitely, so a repository that moves keeps arriving under
its original slug and its history stays joined:

```json
{ "slug": "facebook/react", "full_name": "react/react" }
```

The consequence: **editing an existing line in `config/repositories.txt` starts a new
history for that repository.** Leave renamed entries alone; the redirect does the work.

---

## Repository entry — failed

```json
{ "slug": "owner/name", "status": "error", "error": "not_found" }
```

A failed entry carries **no metric fields at all**. Not `stars: 0`, not
`stars: null` — the keys are absent, because the collector has nothing to say about
them that day.

| `error` | Cause |
| --- | --- |
| `not_found` | 404. Deleted, made private, or a typo in the config. |
| `unauthorized` | 401, or a 403 that is not a quota problem. |
| `rate_limit` | Quota exhausted. Usually affects every repository after a point in the run. |
| `unavailable` | 451. Access blocked, typically a DMCA takedown. |
| `server_error` | 5xx after all retries. |
| `network` | Connection failure or timeout after all retries. |
| `invalid_response` | A 200 whose body was not JSON, or whose fields had the wrong types. |
| `http_error` | Any other unexpected status. |

These strings are part of the data format, not log text. They are safe to match on.

### Partially observed

Metrics and releases are fetched separately, so one can succeed while the other
fails. When that happens the entry keeps its metrics and records why the releases
are missing:

```json
{
  "slug": "owner/name",
  "status": "ok",
  "stars": 1234,
  "releases_error": "rate_limit"
}
```

`releases` is **absent**, not `[]`. An unreadable release list is not an empty one —
the same rule that keeps missing stars from becoming zero.

---

## Release

```json
{
  "tag_name": "1.97.1",
  "name": "Rust 1.97.1",
  "published_at": "2026-07-16T12:29:15Z",
  "created_at": "2026-07-16T12:29:08Z",
  "prerelease": false,
  "draft": false,
  "html_url": "https://github.com/rust-lang/rust/releases/tag/1.97.1"
}
```

Each snapshot carries the newest N releases as they stood that day, so every file is
self-contained. Release notes and assets are deliberately dropped: they are large,
they change after publication, and they are one click away via `html_url`.

A release is reported as *new* when its tag is present today and absent yesterday.

---

## GitHub API caveats

Two fields in GitHub's response mean something other than what they appear to.

**`watchers_count` is a copy of the star count.** It is not stored. The number of
accounts actually watching a repository is `subscribers_count`, stored here as
`subscribers`. For `rust-lang/rust` on 2026-08-17 that was 115,528 stars against
1,550 real watchers.

**`open_issues_count` counts pull requests too.** GitHub models PRs as issues, so
`open_issues` is open issues *plus* open PRs. Treat it as "open items", and expect it
to jump on repositories with busy PR queues.

---

## Rules the data keeps

1. **Snapshots are immutable.** A file is written once. It is not corrected later
   because GitHub now says something different — it records what was observed that
   day. `--repair` exists for genuine collection faults and overwrites deliberately.
2. **Missing is never zero.** Absent keys, never invented values.
3. **Failures are visible.** In `status`, in `counts`, in the entry, and in the report.
4. **Reports are derived.** Every report can be rebuilt from stored snapshots with
   `--report-only`. Delete `reports/` entirely and nothing is lost.
5. **Byte-stable output.** Keys sorted, entries sorted by slug, two-space indent,
   trailing newline. Two runs over identical data produce identical bytes, so a diff
   only ever shows real change.

---

## Versioning

`schema_version` is `1`. It increases only when a change would make an older file
ambiguous to read — renaming a field, changing a unit, altering what a value means.
Adding a new optional field does not require a bump.

The collector refuses to read a snapshot whose `schema_version` is newer than it
understands, rather than guessing at its meaning.
