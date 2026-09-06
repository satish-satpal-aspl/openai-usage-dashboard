import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'

import { CostTrend, ModelSplit, RequestTrend, TokenVolume } from './components/Charts'
import { BillingTab } from './components/Billing'
import { ICONS, Sidebar, useHashTab, type TabDef } from './components/Sidebar'
import {
  ApiKeyTable, BilledTrendTable, LineItemTable, ModelTable, ProjectTable, RateCard,
} from './components/Tables'
import { exportUrl, fetchDashboard, type Dashboard, type Filters } from './lib/api'
import { ago, compact, int, isoDaysAgo, monthStart, pct, today, usd } from './lib/format'
import { useThemeMode } from './lib/useTheme'

const PRESETS = [
  { label: '7D', start: () => isoDaysAgo(6), end: today },
  { label: '30D', start: () => isoDaysAgo(29), end: today },
  { label: '90D', start: () => isoDaysAgo(89), end: today },
  { label: 'MTD', start: monthStart, end: today },
]

const TAB_IDS = ['overview', 'models', 'projects', 'keys', 'costs', 'billing', 'rates'] as const

/* Usage data lands with some lag upstream, so sub-minute polling just burns rate
   limit. 60s is the default; the server also caches for CACHE_TTL_SECONDS. */
const INTERVALS = [
  { label: '30s', ms: 30_000 },
  { label: '1m', ms: 60_000 },
  { label: '5m', ms: 300_000 },
  { label: '15m', ms: 900_000 },
  { label: 'Off', ms: 0 },
]

/** Re-render on a timer so the "updated Xs ago" label actually ticks. */
function useTicker(active: boolean, everyMs = 1000) {
  const [, force] = useState(0)
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => force((n) => n + 1), everyMs)
    return () => clearInterval(id)
  }, [active, everyMs])
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  )
}

export default function App() {
  const [filters, setFilters] = useState<Filters>({
    start: isoDaysAgo(29), end: today(), bucket: '1d', projectIds: [],
  })
  const [mode, setMode] = useThemeMode()
  const [tab, setTab] = useHashTab([...TAB_IDS], 'overview')
  const [intervalMs, setIntervalMs] = useState(() => {
    // NB: an absent key must fall through to the default. Number(null) is 0, and
    // 0 is a legal interval here ("Off"), so test for the key before coercing.
    let raw: string | null = null
    try { raw = localStorage.getItem('refreshMs') } catch { /* private mode */ }
    if (raw === null || raw === '') return 60_000
    const saved = Number(raw)
    return INTERVALS.some((i) => i.ms === saved) ? saved : 60_000
  })

  useEffect(() => {
    try { localStorage.setItem('refreshMs', String(intervalMs)) } catch { /* private mode */ }
  }, [intervalMs])

  const { data, isLoading, isFetching, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['dashboard', filters],
    queryFn: () => fetchDashboard(filters),
    staleTime: 15_000,
    refetchInterval: intervalMs || false,
    refetchIntervalInBackground: false,   // pause polling on a hidden tab
    refetchOnWindowFocus: true,           // catch up the moment you come back
    placeholderData: (prev) => prev,      // keep charts on screen while refetching
  })

  useTicker(true)

  const activePreset = useMemo(
    () => PRESETS.find((p) => p.start() === filters.start && p.end() === filters.end)?.label,
    [filters.start, filters.end],
  )
  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch }))

  const t = data?.summary.total
  const days = data
    ? Math.max(1, Math.round(
        (Date.parse(data.meta.end_date) - Date.parse(data.meta.start_date)) / 86_400_000) + 1)
    : 1

  const tabs: TabDef[] = [
    { id: 'overview', label: 'Overview', icon: ICONS.overview,
      hint: t ? `${compact(t.requests)} calls` : undefined },
    { id: 'models', label: 'Models', icon: ICONS.models,
      hint: data ? `${data.by_model.length} in use` : undefined },
    { id: 'projects', label: 'Projects', icon: ICONS.projects,
      hint: data ? `${data.by_project.length} active` : undefined },
    { id: 'keys', label: 'API keys', icon: ICONS.keys,
      hint: data ? `${data.by_api_key.length} keys` : undefined },
    { id: 'costs', label: 'Costs', icon: ICONS.costs,
      hint: data ? usd(data.billed_cost, 2) : undefined },
    { id: 'billing', label: 'Billing', icon: ICONS.billing,
      hint: 'history & balance' },
    { id: 'rates', label: 'Rate card', icon: ICONS.rates,
      hint: data ? `${data.rate_card.length} models` : undefined },
  ]

  const activeTab = tabs.find((x) => x.id === tab)

  return (
    <div className="layout">
      <Sidebar
        tabs={tabs}
        active={tab}
        onSelect={setTab}
        footer={
          <>
            {data?.meta.live
              ? <span className={'live-pill' + (isFetching ? ' syncing' : '')}>
                  <i />{isFetching ? 'Syncing…' : 'Live organization data'}
                </span>
              : <span className="live-pill demo"><i />Demo data</span>}
            <p className="foot-note">
              Updated {ago(dataUpdatedAt)}
              {intervalMs
                ? ` · auto every ${INTERVALS.find((i) => i.ms === intervalMs)?.label}`
                : ' · auto-refresh off'}
            </p>
            <div className="field" style={{ marginTop: 10 }}>
              <label htmlFor="theme">Theme</label>
              <select id="theme" value={mode} onChange={(e) => setMode(e.target.value as any)}>
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </div>
            {data && (
              <p className="foot-note">
                Rates: {data.meta.pricing_source}
              </p>
            )}
          </>
        }
      />

      <main className="main">
        <header className="page-head">
          <div>
            <h1>{activeTab?.label ?? 'Overview'}</h1>
            <p>
              {data ? `${data.meta.start_date} → ${data.meta.end_date}` : 'Loading…'}
              {data && <span className="muted"> · updated {ago(dataUpdatedAt)}</span>}
            </p>
          </div>
        </header>

      {data && !data.meta.live && (
        <div className="banner warn">
          <span className="dot" />
          <div>
            <strong>Demo data — not your organization</strong>
            {data.meta.key_status.message} Set <code>OPENAI_ADMIN_KEY</code> in{' '}
            <code>usage_dashboard/backend/.env</code> to an Admin key (<code>sk-admin-…</code>)
            and restart the backend.
          </div>
        </div>
      )}

      {/* Filters are global: they apply to every tab, so they stay above the split. */}
      <div className="toolbar">
        <div className="presets" role="group" aria-label="Date range presets">
          {PRESETS.map((p) => (
            <button key={p.label} aria-pressed={activePreset === p.label}
                    onClick={() => set({ start: p.start(), end: p.end() })}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="field">
          <label htmlFor="start">From</label>
          <input id="start" type="date" value={filters.start} max={filters.end}
                 onChange={(e) => set({ start: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="end">To</label>
          <input id="end" type="date" value={filters.end} min={filters.start} max={today()}
                 onChange={(e) => set({ end: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="bucket">Granularity</label>
          <select id="bucket" value={filters.bucket}
                  onChange={(e) => set({ bucket: e.target.value as Filters['bucket'] })}>
            <option value="1d">Daily</option>
            <option value="1h">Hourly</option>
            <option value="1m">Per minute</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="project">Project</label>
          <select id="project" value={filters.projectIds[0] ?? ''}
                  onChange={(e) => set({ projectIds: e.target.value ? [e.target.value] : [] })}>
            <option value="">All projects</option>
            {data?.projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </div>
        <div className="spacer" />
        <div className="field">
          <label htmlFor="auto">Auto-refresh</label>
          <select id="auto" value={intervalMs}
                  onChange={(e) => setIntervalMs(Number(e.target.value))}>
            {INTERVALS.map((i) => (
              <option key={i.label} value={i.ms}>
                {i.ms ? `Every ${i.label}` : 'Off'}
              </option>
            ))}
          </select>
        </div>
        <button onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
        <a href={exportUrl(filters)} download>
          <button className="btn-primary">Download Excel</button>
        </a>
      </div>

        <div className="content">
          {isLoading && <div className="state">Loading usage…</div>}
          {error && (
            <div className="state error">
              {(error as Error).message}
              <div style={{ marginTop: 12 }}><button onClick={() => refetch()}>Retry</button></div>
            </div>
          )}

          {data && t && (
            <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} tabIndex={-1}>
              {tab === 'overview' && <OverviewTab data={data} days={days} />}
              {tab === 'models' && <ModelsTab data={data} />}
              {tab === 'projects' && <ProjectsTab data={data} />}
              {tab === 'keys' && <ApiKeyTable rows={data.by_api_key} />}
              {tab === 'costs' && <CostsTab data={data} days={days} />}
              {tab === 'billing' && <BillingTab refreshMs={intervalMs} />}
              {tab === 'rates' && <RateCard data={data} />}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

/* ── tab bodies ─────────────────────────────────────────────────────────── */

function OverviewTab({ data, days }: { data: Dashboard; days: number }) {
  const t = data.summary.total
  const cacheRate = t.input_tokens ? t.cached_tokens / t.input_tokens : 0
  return (
    <>
      <div className="tiles">
        <Tile label="API calls" value={compact(t.requests)}
              sub={`${int(Math.round(t.requests / days))} / day avg`} />
        <Tile label="Total tokens" value={compact(t.input_tokens + t.output_tokens)}
              sub={`${compact(t.input_tokens)} in · ${compact(t.output_tokens)} out`} />
        <Tile label="Input tokens" value={compact(t.input_tokens)}
              sub={`${compact(t.cached_tokens)} cached (${pct(cacheRate, 0)})`} />
        <Tile label="Output tokens" value={compact(t.output_tokens)}
              sub={t.requests ? `${int(Math.round(t.output_tokens / t.requests))} / call` : undefined} />
        <Tile label="Billed cost" value={usd(data.billed_cost, 2)}
              sub={`${usd(data.billed_cost / days, 2)} / day`} />
        <Tile label="Estimated cost" value={usd(t.est_cost, 2)}
              sub={`${usd(Math.abs(data.billed_cost - t.est_cost), 2)} from billed`} />
      </div>
      <CostTrend data={data} />
      <div className="grid-2">
        <TokenVolume rows={data.timeseries} />
        <RequestTrend rows={data.timeseries} />
      </div>
    </>
  )
}

function ModelsTab({ data }: { data: Dashboard }) {
  const top = data.by_model[0]
  const t = data.summary.total
  return (
    <>
      <div className="tiles">
        <Tile label="Models in use" value={String(data.by_model.length)} />
        <Tile label="Top model by spend" value={top ? top.model.replace(/-\d{4}-\d{2}-\d{2}$/, '') : '—'}
              sub={top ? `${usd(top.est_cost, 2)} · ${compact(top.requests)} calls` : undefined} />
        <Tile label="Priciest per call"
              value={usd(Math.max(0, ...data.by_model.map((m) => m.avg_cost_per_request)), 4)}
              sub={
                data.by_model.length
                  ? [...data.by_model].sort((a, b) => b.avg_cost_per_request - a.avg_cost_per_request)[0]
                      .model.replace(/-\d{4}-\d{2}-\d{2}$/, '')
                  : undefined
              } />
        <Tile label="Cache hit rate"
              value={pct(t.input_tokens ? t.cached_tokens / t.input_tokens : 0, 1)}
              sub={`${compact(t.cached_tokens)} cached tokens`} />
      </div>
      <ModelSplit rows={data.by_model} />
      <ModelTable rows={data.by_model} />
    </>
  )
}

function ProjectsTab({ data }: { data: Dashboard }) {
  const top = data.by_project[0]
  return (
    <>
      <div className="tiles">
        <Tile label="Active projects" value={String(data.by_project.length)}
              sub={`${data.projects.length} total in org`} />
        <Tile label="Top project" value={top ? top.name : '—'}
              sub={top ? `${usd(top.billed_cost, 2)} billed` : undefined} />
        <Tile label="Billed total" value={usd(data.billed_cost, 2)} />
      </div>
      <ProjectTable rows={data.by_project} />
    </>
  )
}

function CostsTab({ data, days }: { data: Dashboard; days: number }) {
  const t = data.summary.total
  const drift = data.billed_cost - t.est_cost
  return (
    <>
      <div className="tiles">
        <Tile label="Billed cost" value={usd(data.billed_cost, 2)}
              sub={`${usd(data.billed_cost / days, 2)} / day`} />
        <Tile label="Estimated cost" value={usd(t.est_cost, 2)} sub="tokens × live rates" />
        <Tile label="Reconciliation gap" value={usd(Math.abs(drift), 2)}
              sub={data.billed_cost ? `${pct(Math.abs(drift) / data.billed_cost, 2)} of billed` : undefined} />
        <Tile label="Line items" value={String(data.cost_by_line_item.length)} />
      </div>
      <CostTrend data={data} />
      <LineItemTable data={data} />
      <BilledTrendTable data={data} />
    </>
  )
}
