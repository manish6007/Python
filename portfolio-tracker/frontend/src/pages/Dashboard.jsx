import { api, BUCKET_LABELS, inr } from '../api'
import { AllocationChart, DonutByClass, OwnerBar, TrendChart } from '../components/Charts'

export default function Dashboard({ summary, meta, reload }) {
  const s = summary
  const takeSnapshot = async () => { await api.post('/api/snapshots'); reload() }
  const empty = !s.holdings.length

  return (
    <div className="grid">
      {empty && (
        <div className="notice">
          No holdings yet — add them in <b>Portfolio</b>, or load sample data
          from <b>Settings → Demo data</b> to explore the app.
        </div>
      )}
      <div className="grid cols-4">
        <div className="card stat">
          <div className="label">Total assets</div>
          <div className="value">{inr(s.total_assets)}</div>
        </div>
        <div className="card stat">
          <div className="label">Liabilities</div>
          <div className="value">{inr(s.total_liabilities)}</div>
        </div>
        <div className="card stat">
          <div className="label">Net worth</div>
          <div className={'value ' + (s.net_worth >= 0 ? 'pos' : 'neg')}>{inr(s.net_worth)}</div>
        </div>
        <div className="card stat">
          <div className="label">Investible surplus / month</div>
          <div className={'value ' + (s.cashflow.surplus_m >= 0 ? '' : 'neg')}>
            {inr(s.cashflow.surplus_m)}
          </div>
          <div className="sub">savings rate {s.cashflow.savings_rate_pct.toFixed(0)}%</div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>By asset class</h2>
          <DonutByClass byClass={s.by_class} labels={meta.asset_class_labels} />
        </div>
        <div className="card">
          <h2>By owner</h2>
          <OwnerBar byOwner={s.by_owner} />
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Allocation vs target</h2>
          <AllocationChart drift={s.drift} bucketLabels={BUCKET_LABELS} />
        </div>
        <div className="card">
          <h2>Suggestions</h2>
          {s.suggestions.map((g, i) => (
            <div className="sugg" key={i}>
              <span className={'dot p' + g.priority} />
              <div><b>{g.title}</b><span>{g.detail}</span></div>
            </div>
          ))}
          <p className="small muted">Educational nudges only — not investment advice.</p>
        </div>
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between' }}>
          <h2>Net worth trend</h2>
          <button className="btn secondary" onClick={takeSnapshot}>
            📸 Take snapshot (monthly)
          </button>
        </div>
        <TrendChart snapshots={s.snapshots} />
      </div>
    </div>
  )
}
