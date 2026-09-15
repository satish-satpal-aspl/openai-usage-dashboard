import { useMemo, useState } from 'react'

import type { ApiKeyRow, Dashboard, ModelRow, ProjectRow } from '../lib/api'
import { int, pct, usd } from '../lib/format'
import { useTokens } from '../lib/useTheme'

function Panel({ title, caption, children }:
  { title: string; caption?: string; children: React.ReactNode }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      {caption && <p className="caption">{caption}</p>}
      <div className="table-wrap">{children}</div>
    </div>
  )
}

export function ModelTable({ rows }: { rows: ModelRow[] }) {
  const t = useTokens()
  const palette = [t['series-1'], t['series-2'], t['series-3'],
                   t['series-4'], t['series-5'], t['series-6']]
  return (
    <Panel
      title="Models"
      caption="Live rates joined to observed usage — this is the per-model unit economics view."
    >
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th className="num">Calls</th>
            <th className="num">Input</th>
            <th className="num">Cached</th>
            <th className="num">Output</th>
            <th className="num">Cache hit</th>
            <th className="num">$/1M in</th>
            <th className="num">$/1M out</th>
            <th className="num">Avg $/call</th>
            <th className="num">Est. cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.model}>
              <td>
                <i className="swatch" style={{ background: palette[Math.min(i, 5)] }} />
                {r.model}
                {!r.priced && <span className="muted"> · unpriced</span>}
              </td>
              <td className="num">{int(r.requests)}</td>
              <td className="num">{int(r.input_tokens)}</td>
              <td className="num">{int(r.cached_tokens)}</td>
              <td className="num">{int(r.output_tokens)}</td>
              <td className="num">{pct(r.cache_hit_rate)}</td>
              <td className="num">{r.priced ? usd(r.price_in_per_1m, 2) : '—'}</td>
              <td className="num">{r.priced ? usd(r.price_out_per_1m, 2) : '—'}</td>
              <td className="num">{usd(r.avg_cost_per_request, 5)}</td>
              <td className="num">{usd(r.est_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function ProjectTable({ rows }: { rows: ProjectRow[] }) {
  // Two orgs can each hold a project called "Default project" - show the owner
  // column only when there is actually more than one org in play.
  const multi = new Set(rows.map((r) => r.account_id).filter(Boolean)).size > 1
  return (
    <Panel
      title="Projects"
      caption="Billed cost comes from the Costs API; estimated cost is priced from the token mix."
    >
      <table>
        <thead>
          <tr>
            {multi && <th>Account</th>}
            <th>Project</th>
            <th className="num">Calls</th>
            <th className="num">Input</th>
            <th className="num">Cached</th>
            <th className="num">Output</th>
            <th className="num">Est. cost</th>
            <th className="num">Billed</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.project_id}>
              {multi && <td className="muted">{r.account_label}</td>}
              <td>{r.name}<div className="muted" style={{ fontSize: 11 }}>{r.project_id}</div></td>
              <td className="num">{int(r.requests)}</td>
              <td className="num">{int(r.input_tokens)}</td>
              <td className="num">{int(r.cached_tokens)}</td>
              <td className="num">{int(r.output_tokens)}</td>
              <td className="num">{usd(r.est_cost)}</td>
              <td className="num">{usd(r.billed_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function ApiKeyTable({ rows }: { rows: ApiKeyRow[] }) {
  return (
    <Panel
      title="API keys"
      caption="Usage per key. The API returns key IDs and names only — secret values are never exposed."
    >
      <table>
        <thead>
          <tr>
            <th>Key</th>
            <th className="num">Calls</th>
            <th className="num">Input</th>
            <th className="num">Output</th>
            <th className="num">Est. cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.api_key_id}>
              <td>{r.name}<div className="muted" style={{ fontSize: 11 }}>{r.api_key_id}</div></td>
              <td className="num">{int(r.requests)}</td>
              <td className="num">{int(r.input_tokens)}</td>
              <td className="num">{int(r.output_tokens)}</td>
              <td className="num">{usd(r.est_cost)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function RateCard({ data }: { data: Dashboard }) {
  const [q, setQ] = useState('')
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const all = data.rate_card
    return (needle ? all.filter((r) => r.model.toLowerCase().includes(needle)) : all).slice(0, 300)
  }, [data.rate_card, q])

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Model rate card</h2>
        <input
          type="text" value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Filter models…"
          style={{
            fontFamily: 'var(--font)', fontSize: 13, padding: '6px 10px',
            borderRadius: 8, border: '1px solid var(--border-strong)',
            background: 'var(--surface-1)', color: 'var(--text-primary)', minWidth: 200,
          }}
        />
      </div>
      <p className="caption">
        Live from {data.meta.pricing_source} · fetched {data.meta.pricing_fetched}
        {' · '}showing {rows.length} of {data.rate_card.length} OpenAI models
      </p>
      <div className="table-wrap" style={{ maxHeight: 380, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th className="num">$/1M input</th>
              <th className="num">$/1M cached input</th>
              <th className="num">$/1M output</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.model}>
                <td>{r.model}</td>
                <td className="num">{usd(r.price_in_per_1m, 3)}</td>
                <td className="num">
                  {r.price_cached_per_1m ? usd(r.price_cached_per_1m, 3) : '—'}
                </td>
                <td className="num">{usd(r.price_out_per_1m, 3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export function LineItemTable({ data }: { data: Dashboard }) {
  return (
    <Panel title="Billed cost by line item"
           caption="Exactly how OpenAI itemises the bill for this range.">
      <table>
        <thead>
          <tr><th>Line item</th><th className="num">Billed</th><th className="num">Share</th></tr>
        </thead>
        <tbody>
          {data.cost_by_line_item.map((r) => (
            <tr key={r.line_item}>
              <td>{r.line_item}</td>
              <td className="num">{usd(r.cost)}</td>
              <td className="num">
                {data.billed_cost ? pct(r.cost / data.billed_cost) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function BilledTrendTable({ data }: { data: Dashboard }) {
  const est = new Map(data.timeseries.map((r) => [r.bucket, r.est_cost]))
  return (
    <Panel title="Daily billed cost"
           caption="Straight from the Costs API, with the token-priced estimate alongside.">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th className="num">Billed</th>
            <th className="num">Estimated</th>
            <th className="num">Gap</th>
          </tr>
        </thead>
        <tbody>
          {data.cost_timeseries.map((r) => {
            const e = est.get(r.bucket) ?? 0
            return (
              <tr key={r.bucket}>
                <td>{r.bucket}</td>
                <td className="num">{usd(r.cost)}</td>
                <td className="num">{usd(e)}</td>
                <td className="num">{usd(r.cost - e)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Panel>
  )
}
