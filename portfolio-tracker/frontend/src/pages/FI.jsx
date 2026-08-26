import { useCallback, useEffect, useState } from 'react'
import { api, inr, inrShort } from '../api'
import { FiChart } from '../components/Charts'

const pct = (n) => (n == null ? '—' : `${n}%`)

export default function FI({ summary }) {
  const [data, setData] = useState(null)
  const [real, setReal] = useState(true)
  const [horizon, setHorizon] = useState(null)
  const [err, setErr] = useState('')
  const [a, setA] = useState({ inflation_pct: '', step_up_pct: '', swr_multiple: '' })

  const load = useCallback(async () => {
    const q = Object.entries(a)
      .filter(([, v]) => v !== '')
      .map(([k, v]) => `${k}=${v}`).join('&')
    try {
      setData(await api.get('/api/fi' + (q ? '?' + q : '')))
      setErr('')
    } catch (e) { setErr(e.message) }
  }, [a])

  useEffect(() => { load() }, [load])

  if (err) return <div className="notice">Could not build the projection: {err}</div>
  if (!data) return <p className="muted">Projecting…</p>

  const as = data.assumptions
  const base = data.scenarios.find((s) => s.equity_return_pct === 12)
    || data.scenarios[1] || data.scenarios[0]
  const lo = data.scenarios[0]
  const hi = data.scenarios[data.scenarios.length - 1]
  const ck = real ? 'corpus_real' : 'corpus'
  const tk = real ? 'fi_target_real' : 'fi_target'

  // Plot a window around the answer. Charting 40 years when FI lands in 5
  // squashes every year that matters into a flat line at the bottom.
  const suggested = base.years_to_fi != null
    ? Math.min(as.years, Math.max(base.years_to_fi + 5, 10))
    : as.years
  const shown = horizon ?? suggested
  const rows = base.rows.slice(0, shown + 1).map((r, i) => ({
    year: r.year,
    corpus: r[ck],
    target: r[tk],
    band: [lo.rows[i][ck], hi.rows[i][ck]],
  }))

  const age = summary && +(summary.age || 0)
  const progress = data.fi_number_today > 0
    ? Math.min(100, (data.corpus_today / data.fi_number_today) * 100) : 0
  const noExpenses = as.annual_expense <= 0

  return (
    <div className="grid">
      {noExpenses && (
        <div className="notice">
          No expenses are logged, so your FI target is ₹0 and everything below
          is meaningless. Log a month of spending on <b>Cashflow</b> first —
          FI is defined by what you spend, not what you earn.
        </div>
      )}

      {/* Hero */}
      <div className="card" style={{ display: 'flex', gap: 32, flexWrap: 'wrap',
        alignItems: 'flex-end' }}>
        <div>
          <div className="label" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            Your FI number, in today&apos;s money
          </div>
          <div style={{ fontSize: 44, fontWeight: 650, lineHeight: 1.1 }}>
            {inr(data.fi_number_today)}
          </div>
          <div className="small muted">
            {inr(as.annual_expense)}/year of spending × {as.swr_multiple}
          </div>
        </div>
        <div>
          <div className="label" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            On a 12% equity assumption
          </div>
          <div style={{ fontSize: 44, fontWeight: 650, lineHeight: 1.1 }}>
            {base.years_to_fi == null ? 'not within ' + as.years + 'y'
              : base.years_to_fi === 0 ? 'already there'
                : `${base.years_to_fi} years`}
          </div>
          <div className="small muted">
            {base.years_to_fi != null && age > 0
              ? `at about age ${age + base.years_to_fi}`
              : 'set your age in Settings to see the age you reach it'}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div className="small muted" style={{ marginBottom: 4 }}>
            {progress.toFixed(0)}% of the way there ({inr(data.corpus_today)})
          </div>
          <div style={{ height: 10, background: 'var(--grid)', borderRadius: 5,
            overflow: 'hidden' }}>
            <div style={{ width: `${progress}%`, height: '100%',
              background: 'var(--series-1)', borderRadius: 5 }} />
          </div>
        </div>
      </div>

      {/* Scenarios */}
      <div className="grid cols-4">
        {data.scenarios.map((s) => (
          <div className="card stat" key={s.equity_return_pct}
            style={s === base ? { borderColor: 'var(--accent)' } : {}}>
            <div className="label">
              Equity at {s.equity_return_pct}%{s === base ? ' · base case' : ''}
            </div>
            <div className="value">
              {s.years_to_fi == null ? '—' : `${s.years_to_fi}y`}
            </div>
            <div className="sub">
              {s.corpus_at_fi_real
                ? `${inrShort(s.corpus_at_fi_real)} in today's money`
                : `not reached within ${as.years} years`}
            </div>
          </div>
        ))}
        <div className="card stat">
          <div className="label">Coast FI</div>
          <div className="value">
            {data.coast.years_to_fi == null ? '—' : `${data.coast.years_to_fi}y`}
          </div>
          <div className="sub">if you never invest another rupee</div>
        </div>
      </div>

      {/* Projection */}
      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between',
          alignItems: 'center' }}>
          <h2>Corpus vs FI target</h2>
          <div className="row" style={{ alignItems: 'center', gap: 14 }}>
            <label className="row small" style={{ alignItems: 'center', gap: 6 }}>
              Show
              <select value={shown} style={{ padding: '4px 8px' }}
                onChange={(e) => setHorizon(+e.target.value)}>
                {[...new Set([suggested, 10, 20, 30, as.years])]
                  .filter((n) => n <= as.years).sort((x, y) => x - y)
                  .map((n) => (
                    <option key={n} value={n}>
                      {n} years{n === suggested ? ' (fits the answer)' : ''}
                    </option>
                  ))}
              </select>
            </label>
            <label className="row small" style={{ alignItems: 'center', gap: 6 }}>
              <input type="checkbox" checked={real}
                onChange={(e) => setReal(e.target.checked)} />
              Show in today&apos;s money
            </label>
          </div>
        </div>
        <FiChart rows={rows} crossover={base.years_to_fi} real={real} />
        <p className="small muted">
          The target line rises because your expenses inflate — FI is a moving
          number, not a fixed one. The band is the 9%–15% equity range; the
          gap between its edges is the honest width of this forecast, and a
          real market path will wander inside and outside it.
          {!real && ' Nominal figures flatter the plan: switch to today’s money to see what it buys.'}
        </p>
      </div>

      {/* Assumptions */}
      <div className="card">
        <h2>Assumptions</h2>
        <div className="row">
          <label className="field">Inflation % p.a.
            <input type="number" step="any" style={{ width: 110 }}
              placeholder={String(as.inflation_pct)} value={a.inflation_pct}
              onChange={(e) => setA({ ...a, inflation_pct: e.target.value })} />
          </label>
          <label className="field">SIP step-up % p.a.
            <input type="number" step="any" style={{ width: 130 }}
              placeholder={String(as.step_up_pct)} value={a.step_up_pct}
              onChange={(e) => setA({ ...a, step_up_pct: e.target.value })} />
          </label>
          <label className="field">Expenses multiple
            <select value={a.swr_multiple}
              onChange={(e) => setA({ ...a, swr_multiple: e.target.value })}>
              <option value="">{as.swr_multiple}× (current)</option>
              <option value="25">25× — 4% withdrawal (US-derived)</option>
              <option value="30">30× — 3.3% withdrawal</option>
              <option value="33">33× — 3% withdrawal (cautious)</option>
            </select>
          </label>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <table className="data" style={{ maxWidth: 640 }}>
            <thead><tr>
              <th>Input</th><th className="num">Value</th><th>Where it comes from</th>
            </tr></thead>
            <tbody>
              <tr><td>Annual spending</td><td className="num">{inr(as.annual_expense)}</td>
                <td className="small muted">Cashflow — already excludes EMI, which is
                  what post-FI spending looks like</td></tr>
              <tr><td>Invested per year</td><td className="num">{inr(as.annual_investment)}</td>
                <td className="small muted">SIPs + payroll, growing {pct(as.step_up_pct)}/yr</td></tr>
              <tr><td>Corpus today</td><td className="num">{inr(data.corpus_today)}</td>
                <td className="small muted">All holdings, each bucket compounding at its own rate</td></tr>
              <tr><td>New money allocated</td><td className="num">
                {Object.entries(as.new_money_allocation_pct || {})
                  .filter(([, v]) => v > 0)
                  .map(([k, v]) => `${k} ${v}%`).join(' · ')}</td>
                <td className="small muted">Your target allocation from Settings</td></tr>
              <tr><td>Loan closes</td><td className="num">
                {as.loan_payoff_year == null ? '—' : `${as.loan_payoff_year}y`}</td>
                <td className="small muted">
                  {as.freed_emi_annual > 0
                    ? `then ${inr(as.freed_emi_annual)}/yr of freed EMI is invested`
                    : 'no loan recorded'}</td></tr>
              <tr><td>Expected returns</td><td className="num small">
                {Object.entries(as.returns_pct).filter(([k]) => k !== 'other')
                  .map(([k, v]) => `${k} ${v}%`).join(' · ')}</td>
                <td className="small muted">Per bucket; only equity moves across scenarios</td></tr>
            </tbody>
          </table>
        </div>
        {data.notes.map((n, i) => (
          <p className="small muted" key={i}>• {n}</p>
        ))}
        <p className="small muted">
          A projection is not a prediction. It assumes steady returns in a
          straight line; real markets deliver the same average through crashes
          and booms, and retiring into a bad decade is the risk this chart
          cannot show. Treat the range as a direction of travel, revisit it
          yearly, and change the assumptions rather than trusting these.
        </p>
      </div>
    </div>
  )
}
