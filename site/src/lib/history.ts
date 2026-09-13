import { getCollection, type CollectionEntry } from 'astro:content';

export type ReportEntry = CollectionEntry<'reports'>;
export type SnapshotEntry = CollectionEntry<'snapshots'>;

/** Collection ids from the glob loader are the file path minus extension, e.g. "2026/09/13". */
function idToDate(id: string): string {
  return id.replace(/\//g, '-');
}

export async function getReports(): Promise<{ date: string; entry: ReportEntry }[]> {
  const entries = await getCollection('reports');
  return entries
    .map((entry) => ({ date: idToDate(entry.id), entry }))
    .sort((a, b) => (a.date < b.date ? 1 : -1));
}

export interface MonthGroup {
  key: string; // "2026-09"
  label: string; // "September 2026"
  reports: { date: string; entry: ReportEntry }[];
  netStars: number;
}

export async function getReportsByMonth(): Promise<MonthGroup[]> {
  const reports = await getReports();
  const activity = await getDailyActivity();
  const byMonth = new Map<string, MonthGroup>();

  for (const report of reports) {
    const key = report.date.slice(0, 7);
    let group = byMonth.get(key);
    if (!group) {
      const [year, month] = key.split('-').map(Number);
      const label = new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-US', {
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC'
      });
      group = { key, label, reports: [], netStars: 0 };
      byMonth.set(key, group);
    }
    group.reports.push(report);
    group.netStars += activity.get(report.date)?.netStars ?? 0;
  }

  return [...byMonth.values()].sort((a, b) => (a.key < b.key ? 1 : -1));
}

export interface TopMover {
  slug: string;
  delta: number;
}

export interface DayActivity {
  date: string;
  status: 'complete' | 'partial' | 'failed';
  /** Sum of positive and negative star changes vs. the previous snapshot, for repos present in both. */
  netStars: number;
  /** Sum of absolute star movement, used to size the heatmap bucket. */
  totalMovement: number;
  growingCount: number;
  newReleaseCount: number;
  topMover: TopMover | null;
}

export async function getDailyActivity(): Promise<Map<string, DayActivity>> {
  const snapshots = await getCollection('snapshots');
  const sorted = [...snapshots].sort((a, b) => (a.data.date < b.data.date ? -1 : 1));

  const activity = new Map<string, DayActivity>();
  let previous: SnapshotEntry | undefined;

  for (const snapshot of sorted) {
    let netStars = 0;
    let totalMovement = 0;
    let growingCount = 0;
    let newReleaseCount = 0;
    let topMover: TopMover | null = null;

    if (previous) {
      const previousStars = new Map<string, number>();
      const previousTags = new Map<string, Set<string>>();
      for (const repo of previous.data.repositories) {
        if (repo.status === 'ok' && typeof repo.stars === 'number') {
          previousStars.set(repo.slug, repo.stars);
        }
        if (repo.releases) {
          previousTags.set(repo.slug, new Set(repo.releases.map((r) => r.tag_name)));
        }
      }
      for (const repo of snapshot.data.repositories) {
        if (repo.status === 'ok' && typeof repo.stars === 'number') {
          const before = previousStars.get(repo.slug);
          if (before !== undefined) {
            const delta = repo.stars - before;
            netStars += delta;
            totalMovement += Math.abs(delta);
            if (delta > 0) growingCount++;
            if (!topMover || delta > topMover.delta) {
              topMover = { slug: repo.slug, delta };
            }
          }
        }
        if (repo.releases) {
          const before = previousTags.get(repo.slug);
          for (const release of repo.releases) {
            if (!before || !before.has(release.tag_name)) newReleaseCount++;
          }
        }
      }
    }

    activity.set(snapshot.data.date, {
      date: snapshot.data.date,
      status: snapshot.data.status,
      netStars,
      totalMovement,
      growingCount,
      newReleaseCount,
      topMover
    });

    previous = snapshot;
  }

  return activity;
}
