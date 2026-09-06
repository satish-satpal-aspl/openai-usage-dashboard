import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

import { pct, today, usd } from '../lib/format'
import { useTokens } from '../lib/useTheme'

export interface BalanceStatus {
  amount: number
  as_of: string
  note: string
  updated_at: string
  spent_since: number
  remaining: number
  used_pct: number | null
  days_elapsed: number
  burn_per_day: number
  burn_recent_per_day: number
  burn_recent_days: number
  burn_basis: 'recent' | 'average'
  runway_days: number | null
  depleted_on: string | null
  covers_full_period: boolean
}

export interface BillingData {
  live: boolean
  months_requested: number
  history: {
    month: string; cost: number; days: number; avg_per_day: number
    prev_cost: number | null; change_pct: number | null
    first_day: string; last_day: string
  }[]
  by_project: Record<string, any>[]
  project_months: string[]
  balance: BalanceStatus | null
  balance_supported_by_api: boolean
  balance_note: string
}

async function getBilling(months: number): Promise<BillingData> {
  const r = await fetch(`/api/billing?months=${months}`)
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `Failed (${r.status})`)
  return r.json()
}

function monthLabel(m: string) {
  const [y, mo] = m.split('-').map(Number)
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[mo - 1]} ${String(y).slice(2)}`
}

/* ── balance editor ─────────────────────────────────────────────────────── */
function BalanceForm({ current, onDone }:
  { current: BalanceStatus | null; onDone: () => void }) {
  const [amount, setAmount] = useState(current ? String(current.amount) : '')
  const [asOf, setAsOf] = useState(current?.as_of ?? today())
  const [note, setNote] = useState(current?.note ?? '')
  const qc = useQueryClient()

  const save = useMutation({
    mutationFn: async () => {
      const r = await fetch('/api/billing/balance', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: Number(amount), as_of: asOf, note }),
      })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? 'Save failed')
      return r.json()
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['billing'] }); onDone() },
  })

  const clear = useMutation({
    mutationFn: async () => { await fetch('/api/billing/balance', { method: 'DELETE' }) },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['billing'] }); onDone() },
  })

  return (
    <div className="panel">
      <h2>{current ? 'Update recorded balance' : 'Record your balance'}</h2>
      <p className="caption">
        Enter the credit balance shown on your OpenAI billing page and the date you
        read it. Billed spend since that date is subtracted automatically.
      </p>
      <div className="toolbar" style={{ marginBottom: 0, boxShadow: 'none' }}>
        <div className="field">
          <label htmlFor="bal-amt">Balance (USD)</label>
          <input id="bal-amt" type="number" min="0" step="0.01" value={amount}
                 placeholder="250.00" onChange={(e) => setAmount(e.target.value)}
                 style={{ width: 140 }} />
        </div>
        <div className="field">
          <label htmlFor="bal-date">As of</label>
          <input id="bal-date" type="date" value={asOf} max={today()}
                 onChange={(e) => setAsOf(e.target.value)} />
        </div>
        <div className="field" style={{ flex: '1 1 220px' }}>
          <label htmlFor="bal-note">Note (optional)</label>
          <input id="bal-note" type="text" value={note} placeholder="e.g. $500 credit top-up"
                 onChange={(e) => setNote(e.target.value)} style={{ width: '100%' }} />
        </div>
        <div className="spacer" />
        <button className="btn-primary"
                disabled={!amount || save.isPending}
                onClick={() => save.mutate()}>
          {save.isPending ? 'Saving…' : 'Save'}
        </button>
        {current && (
          <button onClick={() => clear.mutate()} disabled={clear.isPending}>Clear</button>
        )}
      </div>
      {save.isError && (
        <p className="caption" style={{ color: 'var(--critical)', marginTop: 10 }}>
          {(save.error as Error).message}
        </p>
      )}
    </div>
  )
}

/* ── main tab ───────────────────────────────────────────────────────────── */
export function BillingTab({ refreshMs }: { refreshMs: number }) {
  const [months, setMonths] = useState(12)
  const [editing, setEditing] = useState(false)
  const t = useTokens()

  const { data, isLoading, error } = useQuery({
    queryKey: ['billing', months],
    queryFn: () => getBilling(months),
    refetchInterval: refreshMs || false,
    refetchIntervalInBackground: false,
    placeholderData: (prev) => prev,
  })

  useEffect(() => { if (data && !data.balance) setEditing(true) }, [data])

  if (isLoading) return <div className="state">Loading billing…</div>
  if (error) return <div className="state error">{(error as Error).message}</div>
  if (!data) return null

  const b = data.balance
  const chart = [...data.history].reverse()
    .map((r) => ({ label: monthLabel(r.month), cost: r.cost, month: r.month }))

  // Runway severity drives an icon+label, never colour alone.
  const runway = b?.runway_days ?? null
  const sev = runway === null ? null : runway < 14 ? 'critical' : runway < 45 ? 'warning' : 'good'
  const sevText = sev === 'critical' ? 'Low' : sev === 'warning' ? 'Watch' : 'Healthy'

  return (
    <>
      {/* balance */}
      {b ? (
        <>
          <div className="tiles">
            <div className="tile">
              <div className="label">Remaining balance</div>
              <div className="value" style={{ color: sev === 'critical' ? 'var(--critical)' : undefined }}>
                {usd(b.remaining, 2)}
              </div>
              <div className="sub">
                of {usd(b.amount, 2)} recorded {b.as_of}
              </div>
            </div>
            <div className="tile">
              <div className="label">Spent since</div>
              <div className="value">{usd(b.spent_since, 2)}</div>
              <div className="sub">
                {b.used_pct !== null ? `${pct(b.used_pct, 1)} used` : ''} · {b.days_elapsed} days
              </div>
            </div>
            <div className="tile">
              <div className="label">Burn rate</div>
              <div className="value">{usd(b.burn_recent_per_day, 2)}<span style={{ fontSize: 14, fontWeight: 500 }}> /day</span></div>
              <div className="sub">
                last {b.burn_recent_days}d · {usd(b.burn_per_day, 2)}/day lifetime
              </div>
            </div>
            <div className="tile">
              <div className="label">Runway</div>
              <div className="value">
                {runway === null ? '—' : `${Math.floor(runway)}d`}
              </div>
              <div className="sub">
                {b.depleted_on ? `empty ~${b.depleted_on}` : 'no spend recorded'}
                {sev && <> · <strong>{sevText}</strong></>}
              </div>
            </div>
          </div>

          <div className={'banner ' + (sev === 'critical' ? 'warn' : 'live')}>
            <span className="dot" style={{
              background: sev === 'critical' ? 'var(--critical)'
                : sev === 'warning' ? 'var(--warning)' : 'var(--good)',
            }} />
            <div>
              <strong>
                {sev === 'critical' ? 'Balance running low'
                  : sev === 'warning' ? 'Balance worth watching'
                  : 'Balance healthy'}
              </strong>
              Runway is computed from the <strong>{b.burn_basis}</strong> burn rate
              ({usd(b.burn_basis === 'recent' ? b.burn_recent_per_day : b.burn_per_day, 2)}/day),
              whichever is higher — spend that is accelerating would otherwise flatter
              the estimate.
              {!b.covers_full_period && (
                <> <strong>Note:</strong> history does not reach back to {b.as_of},
                so spend since then may be understated — widen the range below.</>
              )}
              {b.note && <> · {b.note}</>}
              <button className="toggle" style={{ marginLeft: 10 }}
                      onClick={() => setEditing((v) => !v)}>
                {editing ? 'Close' : 'Update'}
              </button>
            </div>
          </div>
        </>
      ) : (
        <div className="banner warn">
          <span className="dot" />
          <div>
            <strong>No balance recorded</strong>
            {data.balance_note}
          </div>
        </div>
      )}

      {editing && <BalanceForm current={b} onDone={() => setEditing(false)} />}

      {/* history */}
      <div className="panel">
        <div className="panel-head">
          <h2>Billing history</h2>
          <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            {[3, 6, 12, 24].map((m) => <option key={m} value={m}>Last {m} months</option>)}
          </select>
        </div>
        <p className="caption">
          Billed spend per calendar month, from the Costs API — the same figures OpenAI
          charges. Invoices themselves are not exposed to API keys.
        </p>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={chart} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}
                    barCategoryGap="28%">
            <CartesianGrid stroke={t.grid} vertical={false} />
            <XAxis dataKey="label" stroke={t.axis} tickLine={false}
                   tick={{ fill: t['text-muted'], fontSize: 11 }} />
            <YAxis stroke={t.axis} tickLine={false} width={62}
                   tick={{ fill: t['text-muted'], fontSize: 11 }}
                   tickFormatter={(v) => usd(v, 0)} />
            <Tooltip
              cursor={{ fill: t['surface-2'], opacity: 0.55 }}
              content={({ active, payload, label }: any) =>
                active && payload?.length ? (
                  <div className="tip">
                    <div className="tip-title">{label}</div>
                    <div className="row">
                      <span className="k">Billed</span>
                      <span className="v">{usd(payload[0].value, 2)}</span>
                    </div>
                  </div>
                ) : null}
            />
            <Bar dataKey="cost" name="Billed" fill={t['series-1']} radius={[4, 4, 0, 0]}
                 label={{ position: 'top', formatter: (v: number) => usd(v, 0),
                          fill: t['text-secondary'], fontSize: 11 }} />
          </BarChart>
        </ResponsiveContainer>

        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table>
            <thead>
              <tr>
                <th>Month</th>
                <th className="num">Billed</th>
                <th className="num">Active days</th>
                <th className="num">Avg / day</th>
                <th className="num">vs prev month</th>
              </tr>
            </thead>
            <tbody>
              {data.history.map((r) => (
                <tr key={r.month}>
                  <td>{monthLabel(r.month)}<span className="muted"> · {r.month}</span></td>
                  <td className="num">{usd(r.cost, 2)}</td>
                  <td className="num">{r.days}</td>
                  <td className="num">{usd(r.avg_per_day, 2)}</td>
                  <td className="num">
                    {r.change_pct === null ? '—' : (
                      <span style={{ color: r.change_pct > 0 ? 'var(--critical)' : 'var(--success-text)' }}>
                        {r.change_pct > 0 ? '▲' : '▼'} {pct(Math.abs(r.change_pct), 0)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* per-project across months */}
      <div className="panel">
        <h2>Monthly spend by project</h2>
        <p className="caption">Where the bill came from, month by month.</p>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Project</th>
                {data.project_months.filter((m) =>
                  data.by_project.some((r) => (r[`m_${m}`] ?? 0) > 0)).map((m) => (
                  <th key={m} className="num">{monthLabel(m)}</th>
                ))}
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.by_project.map((r) => (
                <tr key={r.project_id}>
                  <td>{r.name}</td>
                  {data.project_months.filter((m) =>
                    data.by_project.some((x) => (x[`m_${m}`] ?? 0) > 0)).map((m) => (
                    <td key={m} className="num">
                      {(r[`m_${m}`] ?? 0) > 0 ? usd(r[`m_${m}`], 2) : <span className="muted">—</span>}
                    </td>
                  ))}
                  <td className="num"><strong>{usd(r.total, 2)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
