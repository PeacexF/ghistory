import type { DayActivity } from './history';

export interface CalendarDay {
  date: string;
  day: number;
  activity: DayActivity | null;
  /** 0 = no data, 1-4 = increasing movement, matching a GitHub-style contribution scale. */
  level: 0 | 1 | 2 | 3 | 4;
}

export interface CalendarMonth {
  year: number;
  month: number; // 1-12
  label: string;
  /** Leading nulls pad the first week to start on Monday. */
  weeks: (CalendarDay | null)[][];
}

function level(movement: number, max: number): CalendarDay['level'] {
  if (movement <= 0 || max <= 0) return 0;
  const ratio = movement / max;
  if (ratio > 0.75) return 4;
  if (ratio > 0.5) return 3;
  if (ratio > 0.25) return 2;
  return 1;
}

/** Groups every observed day into month grids, most recent month first. */
export function buildCalendar(activity: Map<string, DayActivity>): CalendarMonth[] {
  const maxMovement = Math.max(0, ...[...activity.values()].map((a) => a.totalMovement));
  const byMonth = new Map<string, CalendarDay[]>();

  for (const [date, dayActivity] of activity) {
    const [year, month] = date.split('-').map(Number);
    const key = `${year}-${String(month).padStart(2, '0')}`;
    const day = Number(date.split('-')[2]);
    const list = byMonth.get(key) ?? [];
    list.push({
      date,
      day,
      activity: dayActivity,
      level: dayActivity.status === 'failed' ? 0 : level(dayActivity.totalMovement, maxMovement)
    });
    byMonth.set(key, list);
  }

  const months: CalendarMonth[] = [];
  for (const [key, days] of byMonth) {
    const [year, month] = key.split('-').map(Number);
    days.sort((a, b) => a.day - b.day);

    const firstWeekday = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7; // Monday = 0
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const cells: (CalendarDay | null)[] = Array(firstWeekday).fill(null);
    const byDay = new Map(days.map((d) => [d.day, d]));
    for (let d = 1; d <= daysInMonth; d++) {
      cells.push(byDay.get(d) ?? null);
    }

    const weeks: (CalendarDay | null)[][] = [];
    for (let i = 0; i < cells.length; i += 7) {
      weeks.push(cells.slice(i, i + 7));
    }

    months.push({
      year,
      month,
      label: new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString('en-US', {
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC'
      }),
      weeks
    });
  }

  return months.sort((a, b) => (a.year === b.year ? b.month - a.month : b.year - a.year));
}
