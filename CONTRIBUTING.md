# Contributing

> Thanks for your interest in contributing to **ghistory**.

Bug fixes, tests, documentation, analysis tooling, and suggestions for the tracked
repository list are all welcome.

Before anything else, one rule specific to this project:

> [!IMPORTANT]
> **Never hand-edit anything in `data/` or `reports/`.**
>
> `data/` is an append-only archive of what the collector observed on a given day.
> A snapshot is not corrected when GitHub later reports something different — it
> records an observation, and rewriting it destroys the only thing this project
> produces. `reports/` is generated from those snapshots; edit the generator, not
> the output.
>
> Both directories are written by the daily workflow. A pull request should not
> touch them.

If a snapshot really is wrong because collection itself failed, that is what
`./run.sh --repair --date YYYY-MM-DD` is for. See
[docs/operations.md](docs/operations.md#repair-a-bad-day).

## Getting started

```bash
git clone https://github.com/PeacexF/ghistory
cd ghistory
make sync                                 # locked environment via uv
echo "GITHUB_TOKEN=your_token" > .env     # no scopes needed; public data only
make ci                                   # lint, format, types, tests
```

`make` on its own lists every target. [docs/configuration.md](docs/configuration.md)
covers the token and settings; [docs/architecture.md](docs/architecture.md) explains
how a run fits together.

Work against the API without writing anything:

```bash
make dry-run
```

## Before opening a pull request

1. `make ci` passes — it runs exactly what CI runs.
2. New behaviour has tests. `tests/test_reliability.py` is the place for anything
   about how the collector behaves when things go wrong.
3. The change keeps the data guarantees intact: missing values stay missing rather
   than becoming zero, failures stay visible, and snapshots stay immutable.

## Style

- Formatting and linting are settled by `ruff`; types by `mypy` in strict mode.
  Don't argue with them by hand, run `make format`.
- Prose explanation belongs in `docs/`, not in the source.

## Especially useful

- **The tracked list.** [`config/repositories.txt`](config/repositories.txt) is a
  judgement call. Suggestions for long-lived, high-signal projects — particularly in
  ecosystems currently underrepresented — are welcome. Adding a repository starts its
  history from the next run; nothing is backfilled.
- **Analysis tooling.** The dataset is plain JSON and nobody has built much on top of
  it yet. Scripts that read `data/` and answer a question are the most valuable thing
  that can be added without touching the collector.
- **Documentation** that corrects something inaccurate about the data.

## Out of scope

The project is deliberately small: a scheduled collector and a dataset. Web
dashboards, databases, long-running services, and new runtime dependencies are not
planned, and neither is expanding the tracked set to thousands of repositories. If
you have an idea in that direction, open an issue first — the answer may well be
interesting, but it likely belongs somewhere else.

For larger changes generally, an issue before implementation saves everyone effort.

Thanks for helping improve the project.
