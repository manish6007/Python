import { useState } from 'react'
import { api, inr } from '../api'

export default function Loans({ summary, owners, reload }) {
  const [f, setF] = useState({ name: '', kind: 'home', principal_outstanding: '',
    annual_rate: '', emi: '', tenure_months_remaining: '', owner_id: '' })
  const [calc, setCalc] = useState({ loan_id: '', lumpsum: '', invest_return_pct: '12' })
  const [result, setResult] = useState(null)
  const [msg, setMsg] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const loans = summary.loans

  const submit = async (e) => {
    e.preventDefault()
    try {
      await api.post('/api/loans', {
        ...f, owner_id: f.owner_id ? +f.owner_id : undefined,
        principal_outstanding: +f.principal_outstanding,
        annual_rate: +f.annual_rate, emi: +f.emi || 0,
        tenure_months_remaining: +f.tenure_months_remaining || 0,
      })
      setF({ ...f, name: '', principal_outstanding: '', annual_rate: '', emi: '', tenure_months_remaining: '' })
      reload()
    } catch (err) { setMsg('Error: ' + err.message) }
  }

  const runCalc = async (e) => {
    e.preventDefault()
    const loan = loans.find((l) => l.id === +calc.loan_id) || loans[0]
    if (!loan) return
    try {
      setResult({
        loan,
        ...(await api.post('/api/loans/prepay-vs-invest', {
          principal: loan.principal_outstanding, annual_rate: loan.annual_rate,
          emi: loan.emi, lumpsum: +calc.lumpsum,
          invest_return_pct: +calc.invest_return_pct,
        })),
      })
      setMsg('')
    } catch (err) { setMsg('Error: ' + err.message) }
  }

  return (
    <div className="grid">
      {msg && <div className="notice">{msg}</div>}
      <div className="card">
        <h2>Add a loan</h2>
        <form className="row" onSubmit={submit}>
          <label className="field">Name
            <input required value={f.name} onChange={set('name')} placeholder="HDFC home loan" /></label>
          <label className="field">Kind
            <select value={f.kind} onChange={set('kind')}>
              {['home', 'car', 'personal', 'credit_card', 'other'].map((k) => <option key={k}>{k}</option>)}
            </select></label>
          <label className="field">Owner
            <select value={f.owner_id} onChange={set('owner_id')}>
              <option value="">{owners[0]?.name || 'Me'}</option>
              {owners.slice(1).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select></label>
          <label className="field">Outstanding principal
            <input type="number" step="any" required value={f.principal_outstanding} onChange={set('principal_outstanding')} /></label>
          <label className="field">Rate % p.a.
            <input type="number" step="any" required value={f.annual_rate} onChange={set('annual_rate')} /></label>
          <label className="field">EMI
            <input type="number" step="any" value={f.emi} onChange={set('emi')} /></label>
          <label className="field">Months left
            <input type="number" value={f.tenure_months_remaining} onChange={set('tenure_months_remaining')} /></label>
          <button className="btn" type="submit">Add loan</button>
        </form>
      </div>

      <div className="card">
        <h2>Loans</h2>
        {!loans.length ? <p className="muted">No loans recorded. Lucky you.</p> : (
          <table className="data">
            <thead><tr>
              <th>Name</th><th>Kind</th><th className="num">Outstanding</th>
              <th className="num">Rate %</th><th className="num">EMI</th>
              <th className="num">Months left</th><th></th>
            </tr></thead>
            <tbody>{loans.map((l) => (
              <tr key={l.id}>
                <td>{l.name}</td><td>{l.kind}</td>
                <td className="num">{inr(l.principal_outstanding)}</td>
                <td className="num">{l.annual_rate}</td>
                <td className="num">{inr(l.emi)}</td>
                <td className="num">{l.tenure_months_remaining || '—'}</td>
                <td><button className="icon" onClick={async () => {
                  if (window.confirm('Delete ' + l.name + '?')) {
                    await api.del('/api/loans/' + l.id); reload()
                  }
                }}>🗑</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>

      {loans.length > 0 && (
        <div className="card">
          <h2>Prepay vs invest</h2>
          <form className="row" onSubmit={runCalc}>
            <label className="field">Loan
              <select value={calc.loan_id} onChange={(e) => setCalc({ ...calc, loan_id: e.target.value })}>
                {loans.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select></label>
            <label className="field">Lumpsum available
              <input type="number" step="any" required value={calc.lumpsum}
                onChange={(e) => setCalc({ ...calc, lumpsum: e.target.value })} /></label>
            <label className="field">Expected investment return % p.a.
              <input type="number" step="any" value={calc.invest_return_pct}
                onChange={(e) => setCalc({ ...calc, invest_return_pct: e.target.value })} /></label>
            <button className="btn" type="submit">Compare</button>
          </form>
          {result && (
            <div className="grid cols-2" style={{ marginTop: 14 }}>
              <div className="card stat">
                <div className="label">Prepay {result.loan.name}</div>
                <div className="value">{inr(result.interest_saved)}</div>
                <div className="sub">interest saved · closes {result.months_saved} months earlier</div>
              </div>
              <div className="card stat">
                <div className="label">Invest instead (over {Math.round(result.horizon_months / 12)} yrs)</div>
                <div className="value">{inr(result.invest_gain)}</div>
                <div className="sub">expected gain (future value {inr(result.invest_future_value)})</div>
              </div>
              <p className="small muted" style={{ gridColumn: '1 / -1' }}>
                {result.interest_saved > result.invest_gain
                  ? 'Prepaying wins at these rates — and it is risk-free.'
                  : 'Investing wins on expected value, but prepaying is guaranteed; the investment return is not.'}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
