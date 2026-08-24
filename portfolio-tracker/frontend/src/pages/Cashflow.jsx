import { useEffect, useState } from 'react'
import { api, inr } from '../api'

const today = () => new Date().toISOString().slice(0, 10)

function EntryForm({ kind, owners, onDone }) {
  const isIncome = kind === 'income'
  const [f, setF] = useState({
    date: today(), category: isIncome ? 'Salary' : 'Household',
    amount: '', owner_id: '', fixed: !isIncome, notes: '',
  })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const cats = isIncome
    ? ['Salary', 'Bonus', 'Rent received', 'Dividend', 'Interest', 'Other']
    : ['Household', 'Rent paid', 'School fees', 'Transport', 'Utilities',
       'Insurance', 'Medical', 'Dining & fun', 'Travel', 'Shopping', 'Other']
  const submit = async (e) => {
    e.preventDefault()
    await api.post('/api/' + (isIncome ? 'income' : 'expenses'), {
      ...f, amount: +f.amount,
      owner_id: f.owner_id ? +f.owner_id : undefined,
      fixed: f.fixed === true || f.fixed === 'true',
    })
    setF({ ...f, amount: '', notes: '' })
    onDone()
  }
  return (
    <form className="row" onSubmit={submit}>
      <label className="field">Date
        <input type="date" value={f.date} onChange={set('date')} /></label>
      <label className="field">Owner
        <select value={f.owner_id} onChange={set('owner_id')}>
          <option value="">{owners[0]?.name || 'Me'}</option>
          {owners.slice(1).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select></label>
      <label className="field">Category
        <select value={f.category} onChange={set('category')}>
          {cats.map((c) => <option key={c}>{c}</option>)}
        </select></label>
      <label className="field">Amount
        <input type="number" step="any" required value={f.amount} onChange={set('amount')} /></label>
      {!isIncome && (
        <label className="field">Type
          <select value={String(f.fixed)} onChange={set('fixed')}>
            <option value="true">Fixed / committed</option>
            <option value="false">Discretionary</option>
          </select></label>
      )}
      <button className="btn" type="submit">Add</button>
    </form>
  )
}

function EntryTable({ rows, onDelete, showFixed }) {
  if (!rows.length) return <p className="muted">No entries yet.</p>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="data">
        <thead><tr>
          <th>Date</th><th>Owner</th><th>Category</th>
          {showFixed && <th>Type</th>}
          <th className="num">Amount</th><th></th>
        </tr></thead>
        <tbody>
          {rows.slice(0, 60).map((r) => (
            <tr key={r.id}>
              <td>{r.date}</td><td>{r.owner}</td><td>{r.category}</td>
              {showFixed && <td className="small muted">{r.fixed ? 'fixed' : 'discretionary'}</td>}
              <td className="num">{inr(r.amount)}</td>
              <td><button className="icon" onClick={() => onDelete(r.id)}>🗑</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Cashflow({ summary, owners, reload }) {
  const [income, setIncome] = useState([])
  const [expenses, setExpenses] = useState([])
  const [rec, setRec] = useState([])
  const [rf, setRf] = useState({ name: '', kind: 'sip', amount_monthly: '' })

  const loadLists = async () => {
    const [i, e, r] = await Promise.all([
      api.get('/api/income'), api.get('/api/expenses'), api.get('/api/recurring')])
    setIncome(i); setExpenses(e); setRec(r)
  }
  useEffect(() => { loadLists() }, [])

  const refresh = () => { loadLists(); reload() }
  const cf = summary.cashflow

  const addRec = async (e) => {
    e.preventDefault()
    await api.post('/api/recurring', {
      name: rf.name, kind: rf.kind, amount_monthly: +rf.amount_monthly,
      counts_as_investment: rf.kind === 'sip',
    })
    setRf({ name: '', kind: 'sip', amount_monthly: '' })
    refresh()
  }

  return (
    <div className="grid">
      <div className="grid cols-4">
        {[['Income / month (3-mo avg)', cf.income_m],
          ['Expenses / month', cf.expense_m],
          ['EMIs + committed', cf.emi_m + cf.other_committed_m + cf.committed_invest_m],
          ['Investible surplus', cf.surplus_m]].map(([l, v]) => (
            <div className="card stat" key={l}>
              <div className="label">{l}</div>
              <div className={'value ' + (l.includes('surplus') && v < 0 ? 'neg' : '')}>{inr(v)}</div>
            </div>
          ))}
      </div>

      <div className="card">
        <h2>Committed monthly outflows (EMIs, SIPs, premiums)</h2>
        <form className="row" onSubmit={addRec}>
          <label className="field">Name
            <input required value={rf.name} onChange={(e) => setRf({ ...rf, name: e.target.value })} /></label>
          <label className="field">Kind
            <select value={rf.kind} onChange={(e) => setRf({ ...rf, kind: e.target.value })}>
              <option value="sip">SIP (counts as investment)</option>
              <option value="emi">EMI</option>
              <option value="premium">Insurance premium</option>
              <option value="other">Other</option>
            </select></label>
          <label className="field">Amount / month
            <input type="number" step="any" required value={rf.amount_monthly}
              onChange={(e) => setRf({ ...rf, amount_monthly: e.target.value })} /></label>
          <button className="btn" type="submit">Add</button>
        </form>
        {rec.length > 0 && (
          <table className="data" style={{ marginTop: 10 }}>
            <thead><tr><th>Name</th><th>Kind</th><th className="num">Monthly</th><th></th></tr></thead>
            <tbody>{rec.map((r) => (
              <tr key={r.id}>
                <td>{r.name}</td><td>{r.kind}{r.counts_as_investment ? ' · investment' : ''}</td>
                <td className="num">{inr(r.amount_monthly)}</td>
                <td><button className="icon" onClick={async () => { await api.del('/api/recurring/' + r.id); refresh() }}>🗑</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Income</h2>
          <EntryForm kind="income" owners={owners} onDone={refresh} />
          <div style={{ marginTop: 12 }}>
            <EntryTable rows={income} showFixed={false}
              onDelete={async (id) => { await api.del('/api/income/' + id); refresh() }} />
          </div>
        </div>
        <div className="card">
          <h2>Expenses</h2>
          <EntryForm kind="expense" owners={owners} onDone={refresh} />
          <div style={{ marginTop: 12 }}>
            <EntryTable rows={expenses} showFixed
              onDelete={async (id) => { await api.del('/api/expenses/' + id); refresh() }} />
          </div>
        </div>
      </div>
    </div>
  )
}
