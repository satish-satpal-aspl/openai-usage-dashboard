export const SERIES = [
  'var(--series-1)',
  'var(--series-2)',
  'var(--series-3)',
  'var(--series-4)',
  'var(--series-5)',
  'var(--series-6)',
] as const

/** Categorical colour is assigned by fixed slot order and never cycled.
 *  Anything past slot 6 is folded into "Other" by the callers. */
export const seriesColor = (i: number) => SERIES[Math.min(i, SERIES.length - 1)]

const nf = new Intl.NumberFormat('en-US')

export const int = (n: number) => nf.format(Math.round(n ?? 0))

export function compact(n: number): string {
  const v = n ?? 0
  const a = Math.abs(v)
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1) + 'B'
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M'
  if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'K'
  return nf.format(Math.round(v))
}

export function usd(n: number, dp?: number): string {
  let v = n ?? 0
  // collapse -0 and float dust so a zero gap never renders as "$-0.0000"
  if (Math.abs(v) < 5e-7) v = 0
  const digits = dp ?? (Math.abs(v) >= 100 ? 0 : Math.abs(v) >= 1 ? 2 : 4)
  return '$' + v.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export const pct = (n: number, dp = 1) => ((n ?? 0) * 100).toFixed(dp) + '%'

export function isoDaysAgo(days: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

export const today = () => new Date().toISOString().slice(0, 10)

export function monthStart(): string {
  const d = new Date()
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)).toISOString().slice(0, 10)
}

/** Short axis label: "2026-08-24" -> "Aug 24". Hourly buckets keep the time. */
export function axisDate(bucket: string): string {
  if (bucket.includes(' ')) return bucket.split(' ')[1]
  const [y, m, d] = bucket.split('-').map(Number)
  if (!y || !m || !d) return bucket
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${months[m - 1]} ${d}`
}

/** Keep the top N by `value`, fold the rest into a single "Other" row. */
export function topNWithOther<T extends Record<string, any>>(
  rows: T[], n: number, key: keyof T, value: (r: T) => number,
): T[] {
  if (rows.length <= n) return rows
  const sorted = [...rows].sort((a, b) => value(b) - value(a))
  const head = sorted.slice(0, n)
  const tail = sorted.slice(n)
  if (!tail.length) return head
  const merged: any = { [key]: 'Other', __folded: tail.length }
  for (const k of Object.keys(tail[0])) {
    if (typeof (tail[0] as any)[k] === 'number') {
      merged[k] = tail.reduce((s, r) => s + ((r as any)[k] ?? 0), 0)
    }
  }
  return [...head, merged as T]
}

/** "just now" / "12s ago" / "3m ago" - for the auto-refresh freshness label. */
export function ago(ms: number): string {
  if (!ms) return 'never'
  const secs = Math.max(0, Math.round((Date.now() - ms) / 1000))
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  return `${Math.round(mins / 60)}h ago`
}
