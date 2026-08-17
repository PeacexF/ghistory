# GitHub Daily

A small automated archive of the GitHub ecosystem.

Every day, GitHub Daily collects publicly available GitHub data, records it as a snapshot, and commits it to this repository.

The goal is simple: **build a historical record of how GitHub changes over time.**

## How it works

```text
Daily schedule
      ↓
Collect GitHub data
      ↓
Create snapshot
      ↓
Analyze changes
      ↓
Generate report
      ↓
Commit to Git
```

The repository itself acts as the database.

## Planned data

The initial version will track things such as:

* Repository stars and forks
* Repository activity
* Programming languages
* Releases
* Daily growth
* Interesting repository changes
* Newly discovered projects

The exact dataset may evolve as the project develops.

## Why?

GitHub is constantly changing.

Projects appear, grow, get abandoned, change direction, and disappear. A daily snapshot makes it possible to look back at those changes instead of only seeing the current state.

The project is intentionally small. No database, frontend, or complex infrastructure is planned.

Just:

```text
Python + Bash + Git + GitHub Actions
```

## Status

**Not built yet.**

## License

[MIT](LICENSE)
