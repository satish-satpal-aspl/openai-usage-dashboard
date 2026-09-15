import type { AccountRow, Dashboard, UsageReport } from '../lib/api'
import { int, pct, usd } from '../lib/format'

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

const day = (iso: string) => {
  const d = new Date(iso + 'T00:00:00Z')
  return d.toLocaleDateString('en-GB', {
    day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC',
  })
}

/** Marks a client whose cost was split proportionally rather than measured. */
function Approx({ on }: { on: boolean }) {
  if (!on) return null
  return (
    <span className="muted" title="Apportioned across API keys by token spend — the Costs API cannot group by key">
      {' '}*
    </span>
  )
}

export function ReportTab({ data }: { data: Dashboard }) {
  const r: UsageReport | undefined = data.report
  if (!r) return <div className="state">No report available.</div>
  const periods = r.periods
  const docs = r.documents

  return (
    <>
      <div className="tiles">
        <Tile label="Topped up" value={usd(r.top_ups_total, 2)}
              sub={`${r.top_ups.length} top-up${r.top_ups.length === 1 ? '' : 's'} in range`} />
        <Tile label="Usage (billable)" value={usd(r.usage_total, 2)}
              sub={`${r.usage_by_client.length} client${r.usage_by_client.length === 1 ? '' : 's'}`} />
        <Tile label="Balance available" value={usd(r.balance.available, 2)}
              sub={r.balance.covers_period ? 'top-ups less usage' : 'top-ups incomplete'} />
        <Tile label="Excluded / disputed" value={usd(r.excluded_total, 2)}
              sub={r.excluded.length ? 'held out of client usage' : 'none'} />
      </div>

      {!r.balance.covers_period && r.balance.warning && (
        <div className="banner warn">
          <span className="dot" />
          <div><strong>Balance is partial — </strong>{r.balance.warning}</div>
        </div>
      )}

      <Panel title="1. Top-ups" caption="Recorded by hand in report_config.json — OpenAI does not expose credits to API keys.">
        <table>
          <thead>
            <tr><th>Date</th><th>Description</th><th>Account</th><th className="num">Amount</th></tr>
          </thead>
          <tbody>
            {r.top_ups.map((t, i) => (
              <tr key={`${t.date}-${i}`}>
                <td>{day(t.date)}</td>
                <td>{t.description}</td>
                <td className="muted">{t.account_label}</td>
                <td className="num">{usd(t.amount, 2)}</td>
              </tr>
            ))}
            {!r.top_ups.length && (
              <tr><td colSpan={4} className="muted">No top-ups recorded in this range.</td></tr>
            )}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={3}>Total topped up</th>
              <th className="num">{usd(r.top_ups_total, 2)}</th>
            </tr>
          </tfoot>
        </table>
      </Panel>

      <Panel title="2. Usage by period and client"
             caption="Periods split at each recorded top-up date. Billed amounts from the OpenAI Costs API.">
        <table>
          <thead>
            <tr>
              <th>Period</th><th>Client</th>
              <th className="num">Client total</th><th className="num">Period total</th>
            </tr>
          </thead>
          <tbody>
            {r.usage_by_period.map((p) =>
              p.lines.length
                ? p.lines.map((l, i) => (
                    <tr key={`${p.key}-${l.client}`}>
                      <td>{i === 0 ? p.label : ''}</td>
                      <td>{l.client}<Approx on={l.apportioned} /></td>
                      <td className="num">{usd(l.amount, 2)}</td>
                      <td className="num">{i === p.lines.length - 1 ? usd(p.total, 2) : ''}</td>
                    </tr>
                  ))
                : (
                  <tr key={p.key}>
                    <td>{p.label}</td><td className="muted">No usage</td>
                    <td className="num">—</td><td className="num">{usd(0, 2)}</td>
                  </tr>
                ),
            )}
          </tbody>
          <tfoot>
            <tr>
              <th colSpan={2}>Total usage</th>
              <th className="num">{usd(r.usage_total, 2)}</th>
              <th className="num">{usd(r.usage_total, 2)}</th>
            </tr>
          </tfoot>
        </table>
      </Panel>

      <Panel title="3. Usage by client" caption="Across every period in the selected range.">
        <table>
          <thead>
            <tr>
              <th>Client</th>
              {periods.map((p) => <th key={p.key} className="num">{p.short_label}</th>)}
              <th className="num">Total</th><th className="num">Share</th>
            </tr>
          </thead>
          <tbody>
            {r.usage_by_client.map((c) => (
              <tr key={c.client}>
                <td>{c.client}<Approx on={c.apportioned} /></td>
                {periods.map((p) => (
                  <td key={p.key} className="num">{usd(c.periods[p.key] ?? 0, 2)}</td>
                ))}
                <td className="num">{usd(c.total, 2)}</td>
                <td className="num">{pct(c.share)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th>Total</th>
              {periods.map((p) => (
                <th key={p.key} className="num">
                  {usd(r.usage_by_period.find((x) => x.key === p.key)?.total ?? 0, 2)}
                </th>
              ))}
              <th className="num">{usd(r.usage_total, 2)}</th>
              <th className="num">{pct(1)}</th>
            </tr>
          </tfoot>
        </table>
      </Panel>

      <Panel title="4. Balance">
        <table>
          <tbody>
            <tr><td>Total topped up</td><td className="num">{usd(r.balance.topped_up, 2)}</td></tr>
            <tr><td>Less: total usage</td><td className="num">−{usd(r.balance.usage, 2)}</td></tr>
          </tbody>
          <tfoot>
            <tr><th>Balance available</th><th className="num">{usd(r.balance.available, 2)}</th></tr>
          </tfoot>
        </table>
      </Panel>

      {r.excluded.length > 0 && (
        <Panel title="5. Excluded from client usage — disputed charges"
               caption="Held out of the client tables above so they reflect genuine consumption. Still billed by OpenAI until credited.">
          <table>
            <thead>
              <tr>
                <th>Date</th><th>Item</th><th className="num">Gross</th>
                <th className="num">Retained as normal</th><th className="num">Excluded</th>
              </tr>
            </thead>
            <tbody>
              {r.excluded.map((e) => (
                <tr key={e.id}>
                  <td>{day(e.date)}</td>
                  <td>{e.label}{e.note && <div className="muted">{e.note}</div>}</td>
                  <td className="num">{usd(e.gross, 2)}</td>
                  <td className="num">{usd(e.retained_as_normal, 2)}</td>
                  <td className="num">{usd(e.amount, 2)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th colSpan={4}>Total excluded</th>
                <th className="num">{usd(r.excluded_total, 2)}</th>
              </tr>
              <tr>
                <th colSpan={4}>Org billed total (usage + excluded)</th>
                <th className="num">{usd(r.billed_total_including_excluded, 2)}</th>
              </tr>
            </tfoot>
          </table>
        </Panel>
      )}

      {docs.environments.length > 0 && (
        <Panel title={`${r.excluded.length ? 6 : 5}. ${docs.client || 'Client'} — documents processed`}
               caption={`Source: ${docs.source}. Whole months overlapping the range (${
                 docs.months_in_period.join(', ') || '—'}) — a partial month counts in full. Pending database access.`}>
          <table>
            <thead>
              <tr>
                <th>Month</th>
                {docs.environments.map((e) => <th key={e} className="num">{e}</th>)}
                <th className="num">Total</th>
              </tr>
            </thead>
            <tbody>
              {docs.monthly.map((row) => (
                <tr key={String(row.month)}>
                  <td>{String(row.month)}</td>
                  {docs.environments.map((e) => (
                    <td key={e} className="num">{int(Number(row[e] ?? 0))}</td>
                  ))}
                  <td className="num">{int(Number(row.total ?? 0))}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th>All time</th>
                {docs.environments.map((e) => (
                  <th key={e} className="num">{int(docs.all_time_totals[e] ?? 0)}</th>
                ))}
                <th className="num">{int(docs.all_time_total)}</th>
              </tr>
              <tr>
                <th>In this period</th>
                {docs.environments.map((e) => (
                  <th key={e} className="num">{int(docs.period_totals[e] ?? 0)}</th>
                ))}
                <th className="num">{int(docs.period_total)}</th>
              </tr>
            </tfoot>
          </table>
        </Panel>
      )}

      {(r.notes.length > 0 || r.has_apportioned) && (
        <div className="panel">
          <h2>Notes</h2>
          <ul className="caption" style={{ paddingLeft: 18, margin: 0 }}>
            {r.notes.map((n) => <li key={n}>{n}</li>)}
            {r.has_apportioned && (
              <li>
                * Cost apportioned across API keys by token spend. That organization keeps every
                client in one project and the Costs API cannot group by API key, so per-client
                figures there are proportional rather than exact.
              </li>
            )}
          </ul>
        </div>
      )}
    </>
  )
}

export function AccountTable({ rows }: { rows: AccountRow[] }) {
  return (
    <Panel title="Accounts"
           caption="Every configured OpenAI organization. Usage is estimated from tokens; billed is what OpenAI charged.">
      <table>
        <thead>
          <tr>
            <th>Account</th><th className="num">Calls</th><th className="num">Input</th>
            <th className="num">Output</th><th className="num">Est. cost</th>
            <th className="num">Billed cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.account_id}>
              <td>{r.name}</td>
              <td className="num">{int(r.requests)}</td>
              <td className="num">{int(r.input_tokens)}</td>
              <td className="num">{int(r.output_tokens)}</td>
              <td className="num">{usd(r.est_cost)}</td>
              <td className="num">{usd(r.billed_cost, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
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
