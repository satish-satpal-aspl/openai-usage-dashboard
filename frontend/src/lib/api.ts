export interface Totals {
  requests: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  audio_input_tokens: number
  audio_output_tokens: number
  est_cost: number
  total_tokens?: number
}

export interface TimePoint {
  bucket: string
  start_time: number
  requests: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  est_cost: number
}

export interface ModelRow extends Totals {
  model: string
  total_tokens: number
  price_in_per_1m: number
  price_out_per_1m: number
  price_cached_per_1m: number
  priced: boolean
  avg_cost_per_request: number
  cache_hit_rate: number
}

export interface ProjectRow extends Totals {
  project_id: string
  name: string
  billed_cost: number
  account_id: string
  account_label: string
}

export interface AccountRow extends Totals {
  account_id: string
  name: string
  billed_cost: number
}

export interface AccountInfo {
  id: string
  label: string
  org_id: string | null
  owner_email: string | null
  attribute_by: string
  key_env: string
  kind: string
  usable: boolean
  message: string
}

export interface ReportPeriod {
  key: string
  label: string
  short_label: string
  start: string
  end: string
}

export interface ClientRow {
  client: string
  apportioned: boolean
  periods: Record<string, number>
  total: number
  share: number
}

export interface UsageReport {
  title: string
  period: { start: string; end: string; label: string }
  currency: string
  accounts: { id: string; label: string; attribute_by: string; usage: number }[]
  top_ups: {
    date: string
    description: string
    account_id: string
    account_label: string
    amount: number
  }[]
  top_ups_total: number
  periods: ReportPeriod[]
  usage_by_period: (ReportPeriod & {
    lines: { client: string; amount: number; apportioned: boolean }[]
    total: number
  })[]
  usage_by_client: ClientRow[]
  usage_total: number
  balance: {
    topped_up: number
    usage: number
    available: number
    covers_period: boolean
    warning: string
  }
  excluded: {
    id: string
    label: string
    date: string
    gross: number
    retained_as_normal: number
    amount: number
    note: string
  }[]
  excluded_total: number
  billed_total_including_excluded: number
  documents: {
    client: string
    source: string
    environments: string[]
    monthly: Record<string, number | string>[]
    months_in_period: string[]
    period_totals: Record<string, number>
    period_total: number
    all_time_totals: Record<string, number>
    all_time_total: number
  }
  notes: string[]
  has_apportioned: boolean
}

export interface ApiKeyRow extends Totals {
  api_key_id: string
  name: string
  project_name: string
}

export interface Dashboard {
  meta: {
    start_date: string
    end_date: string
    bucket_width: string
    live: boolean
    pricing_source: string
    pricing_fetched: string
    generated_at?: string
    cache_age_seconds?: number
    key_status: {
      configured: boolean
      kind: string | null
      message: string
      accounts: AccountInfo[]
      usable_count: number
      total_count: number
    }
    accounts: AccountInfo[]
    selected_accounts: string[]
  }
  summary: { total: Totals; by_endpoint: Record<string, Totals> }
  timeseries: TimePoint[]
  cost_timeseries: { bucket: string; start_time: number; cost: number }[]
  billed_cost: number
  by_model: ModelRow[]
  by_account: AccountRow[]
  by_project: ProjectRow[]
  by_api_key: ApiKeyRow[]
  cost_by_line_item: { line_item: string; cost: number }[]
  projects: {
    id: string
    name: string
    status: string | null
    account_id: string
    account_label: string
  }[]
  rate_card: {
    model: string
    price_in_per_1m: number
    price_out_per_1m: number
    price_cached_per_1m: number
  }[]
  report: UsageReport
}

export interface Filters {
  start: string
  end: string
  bucket: '1d' | '1h' | '1m'
  projectIds: string[]
  accountIds: string[]
}

export function queryString(f: Filters): string {
  const p = new URLSearchParams()
  p.set('start', f.start)
  p.set('end', f.end)
  p.set('bucket_width', f.bucket)
  f.projectIds.forEach((id) => p.append('project_ids', id))
  f.accountIds.forEach((id) => p.append('account_ids', id))
  return p.toString()
}

export async function fetchDashboard(f: Filters, refresh = false): Promise<Dashboard> {
  const qs = queryString(f) + (refresh ? '&refresh=true' : '')
  const r = await fetch(`/api/dashboard?${qs}`)
  if (!r.ok) {
    let detail = `Request failed (${r.status})`
    try {
      detail = (await r.json()).detail ?? detail
    } catch {
      /* keep the status-code message */
    }
    throw new Error(detail)
  }
  return r.json()
}

export function exportUrl(f: Filters): string {
  return `/api/export.xlsx?${queryString(f)}`
}
