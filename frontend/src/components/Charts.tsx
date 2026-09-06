import { useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import type { Dashboard, ModelRow, TimePoint } from '../lib/api'
import { axisDate, compact, int, pct, topNWithOther, usd } from '../lib/format'
import { useTokens } from '../lib/useTheme'

/* ── shared tooltip ─────────────────────────────────────────────────────── */
function Tip({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="tip">
      <div className="tip-title">{label}</div>
      {payload.map((p: any) => (
        <div className="row" key={p.dataKey}>
          <span className="k">
            <i className="swatch" style={{ background: p.color, margin: 0 }} />
            {p.name}
          </span>
          <span className="v">{fmt ? fmt(p.value, p.dataKey) : int(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

function Legend2({ items }: { items: { name: string; color: string }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.name}>
          <i style={{ background: i.color }} />
          {i.name}
        </span>
      ))}
    </div>
  )
}

/* Light mode WARNs on contrast for three series slots, so every chart here can
   fall back to a table view - that is the relief the palette check requires. */
function TableToggle({ on, set }: { on: boolean; set: (v: boolean) => void }) {
  return (
    <button className="toggle" onClick={() => set(!on)} aria-pressed={on}>
      {on ? 'Chart' : 'Table'}
    </button>
  )
}

const axisProps = (t: ReturnType<typeof useTokens>) => ({
  stroke: t.axis,
  tick: { fill: t['text-muted'], fontSize: 11 },
  tickLine: false,
})

/* ── 1. Cost over time ──────────────────────────────────────────────────── */
export function CostTrend({ data }: { data: Dashboard }) {
  const t = useTokens()
  const [asTable, setAsTable] = useState(false)

  const billed = new Map(data.cost_timeseries.map((r) => [r.bucket, r.cost]))
  const rows = data.timeseries.map((r) => ({
    bucket: r.bucket,
    label: axisDate(r.bucket),
    billed: billed.get(r.bucket) ?? 0,
    estimated: r.est_cost,
  }))

  const series = [
    { name: 'Billed (OpenAI)', color: t['series-1'], key: 'billed' },
    { name: 'Estimated (tokens × rates)', color: t['series-2'], key: 'estimated' },
  ]

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Spend over time</h2>
        <TableToggle on={asTable} set={setAsTable} />
      </div>
      <p className="caption">
        Billed dollars from the Costs API against what the observed token mix should
        cost at current rates. A persistent gap means untracked line items.
      </p>
      <Legend2 items={series} />

      {asTable ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Date</th><th className="num">Billed</th><th className="num">Estimated</th><th className="num">Δ</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.bucket}>
                  <td>{r.bucket}</td>
                  <td className="num">{usd(r.billed)}</td>
                  <td className="num">{usd(r.estimated)}</td>
                  <td className="num">{usd(r.billed - r.estimated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="gBilled" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={t['series-1']} stopOpacity={0.26} />
                <stop offset="100%" stopColor={t['series-1']} stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke={t.grid} strokeDasharray="0" vertical={false} />
            <XAxis dataKey="label" {...axisProps(t)} />
            <YAxis {...axisProps(t)} tickFormatter={(v) => usd(v, 0)} width={62} />
            <Tooltip
              content={<Tip fmt={(v: number) => usd(v)} />}
              cursor={{ stroke: t.axis, strokeWidth: 1 }}
            />
            <Area
              type="monotone" dataKey="billed" name="Billed (OpenAI)"
              stroke={t['series-1']} strokeWidth={2} fill="url(#gBilled)"
              dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: t['surface-1'] }}
            />
            <Area
              type="monotone" dataKey="estimated" name="Estimated (tokens × rates)"
              stroke={t['series-2']} strokeWidth={2} strokeDasharray="4 3" fill="none"
              dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: t['surface-1'] }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

/* ── 2. Token volume, stacked ───────────────────────────────────────────── */
export function TokenVolume({ rows }: { rows: TimePoint[] }) {
  const t = useTokens()
  const [asTable, setAsTable] = useState(false)

  const data = rows.map((r) => ({
    bucket: r.bucket,
    label: axisDate(r.bucket),
    cached: r.cached_tokens,
    billable: Math.max(0, r.input_tokens - r.cached_tokens),
    output: r.output_tokens,
    requests: r.requests,
  }))

  const series = [
    { name: 'Input (billable)', color: t['series-1'], key: 'billable' },
    { name: 'Input (cached)', color: t['series-3'], key: 'cached' },
    { name: 'Output', color: t['series-2'], key: 'output' },
  ]

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Token volume</h2>
        <TableToggle on={asTable} set={setAsTable} />
      </div>
      <p className="caption">
        Cached input is split out because it bills at a lower rate — the green band
        is the discount you are already earning.
      </p>
      <Legend2 items={series} />

      {asTable ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th><th className="num">Calls</th>
                <th className="num">Input (billable)</th><th className="num">Input (cached)</th>
                <th className="num">Output</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.bucket}>
                  <td>{r.bucket}</td>
                  <td className="num">{int(r.requests)}</td>
                  <td className="num">{int(r.billable)}</td>
                  <td className="num">{int(r.cached)}</td>
                  <td className="num">{int(r.output)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
            <CartesianGrid stroke={t.grid} vertical={false} />
            <XAxis dataKey="label" {...axisProps(t)} />
            <YAxis {...axisProps(t)} tickFormatter={compact} width={54} />
            <Tooltip
              content={<Tip fmt={(v: number) => int(v)} />}
              cursor={{ fill: t['surface-2'], opacity: 0.55 }}
            />
            {/* 1px surface stroke on each segment = the 2px gap between fills */}
            <Bar dataKey="billable" name="Input (billable)" stackId="s"
                 fill={t['series-1']} stroke={t['surface-1']} strokeWidth={1} />
            <Bar dataKey="cached" name="Input (cached)" stackId="s"
                 fill={t['series-3']} stroke={t['surface-1']} strokeWidth={1} />
            <Bar dataKey="output" name="Output" stackId="s"
                 fill={t['series-2']} stroke={t['surface-1']} strokeWidth={1}
                 radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

/* ── 3. Cost by model ───────────────────────────────────────────────────── */
export function ModelSplit({ rows }: { rows: ModelRow[] }) {
  const t = useTokens()
  // Models whose spend rounds to $0.0000 add rows of noise (and previously folded
  // into a meaningless "Other" bar). Drop them from the chart, but say so.
  const MIN = 5e-5
  const shown = rows.filter((r) => r.est_cost >= MIN)
  const hidden = rows.length - shown.length
  const folded = topNWithOther(shown, 6, 'model', (r) => r.est_cost)
  const data = folded
    .filter((r) => r.est_cost >= MIN)
    .map((r) => ({ model: r.model, cost: r.est_cost, requests: r.requests }))
    .sort((a, b) => b.cost - a.cost)
  const palette = [t['series-1'], t['series-2'], t['series-3'],
                   t['series-4'], t['series-5'], t['series-6']]

  return (
    <div className="panel">
      <h2>Estimated cost by model</h2>
      <p className="caption">
        Token mix priced at current rates. Values are labelled directly, so the
        bars never carry meaning by colour alone.
        {hidden > 0 && ` ${hidden} model${hidden > 1 ? 's' : ''} under $0.0001 not shown — see the table below.`}
      </p>
      <ResponsiveContainer width="100%" height={Math.max(150, data.length * 42 + 30)}>
        <BarChart data={data} layout="vertical"
                  margin={{ top: 2, right: 70, left: 8, bottom: 2 }}>
          <CartesianGrid stroke={t.grid} horizontal={false} />
          <XAxis type="number" {...axisProps(t)} tickFormatter={(v) => usd(v, 0)} />
          <YAxis type="category" dataKey="model" width={150} {...axisProps(t)} />
          <Tooltip
            content={<Tip fmt={(v: number) => usd(v)} />}
            cursor={{ fill: t['surface-2'], opacity: 0.55 }}
          />
          <Bar dataKey="cost" name="Estimated cost" radius={[0, 4, 4, 0]} barSize={20}
               label={{ position: 'right', formatter: (v: number) => usd(v),
                        fill: t['text-secondary'], fontSize: 11 }}>
            {data.map((_, i) => <Cell key={i} fill={palette[Math.min(i, palette.length - 1)]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── 4. Calls per day ───────────────────────────────────────────────────── */
export function RequestTrend({ rows }: { rows: TimePoint[] }) {
  const t = useTokens()
  const data = rows.map((r) => ({ label: axisDate(r.bucket), requests: r.requests }))
  return (
    <div className="panel">
      <h2>API calls</h2>
      <p className="caption">Model requests per bucket across every endpoint.</p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={t.grid} vertical={false} />
          <XAxis dataKey="label" {...axisProps(t)} />
          <YAxis {...axisProps(t)} tickFormatter={compact} width={54} />
          <Tooltip
            content={<Tip fmt={(v: number) => int(v)} />}
            cursor={{ stroke: t.axis, strokeWidth: 1 }}
          />
          <Line type="monotone" dataKey="requests" name="API calls"
                stroke={t['series-1']} strokeWidth={2} dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: t['surface-1'] }} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
