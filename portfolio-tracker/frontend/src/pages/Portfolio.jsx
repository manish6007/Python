import { useMemo, useRef, useState } from 'react'
import { api, inr } from '../api'

const UNIT_CLASSES = ['mutual_fund', 'stock', 'gold_etf', 'reit', 'sgb', 'nps', 'gold_physical']
const BALANCE_CLASSES = ['savings', 'epf', 'ppf', 'other']
const MF_CATEGORIES = ['equity', 'debt', 'hybrid', 'elss', 'liquid', 'gold']
const BUCKETS = ['equity', 'debt', 'gold', 'real_estate', 'cash', 'other']

const emptyForm = {
  asset_class: 'mutual_fund', name: '', identifier: '', units: '', avg_cost: '',
  last_price: '', manual_value: '', rate: '', start_date: '', category: 'equity',
  bucket: 'other', notes: '',
}

export default function Portfolio({ summary, meta, owners, reload }) {
  const [form, setForm] = useState({ ...emptyForm, owner_id: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [amfiQ, setAmfiQ] = useState('')
  const [amfiHits, setAmfiHits] = useState(null)
  const [editId, setEditId] = useState(null)
  const [editVal, setEditVal] = useState('')
  const fileRef = useRef()

  const cls = form.asset_class
  const isUnit = UNIT_CLASSES.includes(cls)
  const isFd = cls === 'fd'
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const holdings = useMemo(
    () => [...summary.holdings].sort((a, b) => b.current_value - a.current_value),
    [summary.holdings])

  const submit = async (e) => {
    e.preventDefault()
    const payload = {
      asset_class: cls, name: form.name, identifier: form.identifier,
      owner_id: form.owner_id ? +form.owner_id : undefined,
      units: +form.units || 0, avg_cost: +form.avg_cost || 0,
      last_price: +form.last_price || 0, manual_value: +form.manual_value || 0,
      rate: +form.rate || 0, start_date: form.start_date || null,
      notes: form.notes,
      meta: {
        ...(cls === 'mutual_fund' ? { category: form.category } : {}),
        ...(cls === 'other' ? { bucket: form.bucket } : {}),
      },
    }
    try {
      await api.post('/api/holdings', payload)
      setForm({ ...emptyForm, owner_id: form.owner_id, asset_class: cls })
      setMsg('Added ' + payload.name)
      reload()
    } catch (err) { setMsg('Error: ' + err.message) }
  }

  const refreshPrices = async () => {
    setBusy(true)
    try {
      const r = await api.post('/api/prices/refresh')
      let m = `MF NAVs updated: ${r.mf_updated} · stocks updated: ${r.stocks_updated}`
      if (!r.amfi_reachable) m += ' · AMFI unreachable'
      if (r.stock_failed.length) m += ' · failed: ' + r.stock_failed.join(', ')
      setMsg(m)
      reload()
    } catch (err) { setMsg('Error: ' + err.message) }
    setBusy(false)
  }

  const searchAmfi = async () => {
    setAmfiHits(await api.get('/api/amfi/search?q=' + encodeURIComponent(amfiQ)))
  }

  const del = async (h) => {
    if (!window.confirm('Delete ' + h.name + '?')) return
    await api.del('/api/holdings/' + h.id)
    reload()
  }

  const startEdit = (h) => {
    setEditId(h.id)
    setEditVal(String(
      BALANCE_CLASSES.includes(h.asset_class) ? h.manual_value
        : h.asset_class === 'fd' ? h.avg_cost : h.last_price || 0))
  }

  const saveEdit = async (h) => {
    const v = +editVal || 0
    const payload = BALANCE_CLASSES.includes(h.asset_class)
      ? { manual_value: v }
      : h.asset_class === 'fd' ? { avg_cost: v } : { last_price: v }
    await api.put('/api/holdings/' + h.id, payload)
    setEditId(null)
    reload()
  }

  const importCsv = async (e) => {
    const f = e.target.files[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    try {
      const r = await api.post('/api/holdings/import', fd)
      setMsg(`Imported ${r.added} holdings.` +
        (r.errors.length ? ' Skipped: ' + r.errors.join('; ') : ''))
      reload()
    } catch (err) { setMsg('Import error: ' + err.message) }
    fileRef.current.value = ''
  }

  const template = 'owner,asset_class,name,identifier,units,avg_cost,manual_value,last_price,rate,start_date,category\n' +
    'Me,mutual_fund,Parag Parikh Flexi Cap Dir-G,122639,512.33,55.1,0,81.2,0,,equity\n' +
    'Me,stock,Reliance Industries,RELIANCE,10,2400,0,2950,0,,\n' +
    'Wife,fd,HDFC FD,XXXX1234,0,500000,0,0,7.1,2025-01-15,\n' +
    'Me,ppf,SBI PPF,,0,0,450000,0,7.1,,\n'

  return (
    <div className="grid">
      {msg && <div className="notice">{msg}</div>}

      <div className="card">
        <h2>Add a holding</h2>
        <form className="stack" onSubmit={submit}>
          <div className="row">
            <label className="field">Asset class
              <select value={cls} onChange={set('asset_class')}>
                {meta.asset_classes.map((c) => (
                  <option key={c} value={c}>{meta.asset_class_labels[c]}</option>
                ))}
              </select>
            </label>
            <label className="field">Owner
              <select value={form.owner_id} onChange={set('owner_id')}>
                <option value="">{owners[0]?.name || 'Me'}</option>
                {owners.slice(1).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            </label>
            <label className="field">Name
              <input required value={form.name} onChange={set('name')}
                placeholder="Scheme / stock / bank" style={{ minWidth: 220 }} />
            </label>
            <label className="field">Identifier
              <input value={form.identifier} onChange={set('identifier')}
                placeholder={cls === 'mutual_fund' ? 'AMFI code (auto-NAV)'
                  : cls === 'stock' ? 'NSE ticker e.g. RELIANCE' : 'Folio / account no.'} />
            </label>
          </div>
          <div className="row">
            {isUnit && (<>
              <label className="field">{cls === 'gold_physical' ? 'Grams' : 'Units / qty'}
                <input type="number" step="any" value={form.units} onChange={set('units')} />
              </label>
              <label className="field">Avg buy price/unit
                <input type="number" step="any" value={form.avg_cost} onChange={set('avg_cost')} />
              </label>
              <label className="field">Current price/unit
                <input type="number" step="any" value={form.last_price} onChange={set('last_price')}
                  placeholder="auto for MF/stocks" />
              </label>
              {cls === 'mutual_fund' && (
                <label className="field">Category
                  <select value={form.category} onChange={set('category')}>
                    {MF_CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </label>
              )}
            </>)}
            {isFd && (<>
              <label className="field">Principal
                <input type="number" step="any" required value={form.avg_cost} onChange={set('avg_cost')} />
              </label>
              <label className="field">Rate % p.a.
                <input type="number" step="any" value={form.rate} onChange={set('rate')} />
              </label>
              <label className="field">Start date
                <input type="date" value={form.start_date} onChange={set('start_date')} />
              </label>
            </>)}
            {!isUnit && !isFd && (<>
              <label className="field">Current balance / value
                <input type="number" step="any" required value={form.manual_value} onChange={set('manual_value')} />
              </label>
              <label className="field">Rate % p.a. (0 = no accrual)
                <input type="number" step="any" value={form.rate} onChange={set('rate')} />
              </label>
              {cls === 'other' && (
                <label className="field">Counts as
                  <select value={form.bucket} onChange={set('bucket')}>
                    {BUCKETS.map((b) => <option key={b}>{b}</option>)}
                  </select>
                </label>
              )}
            </>)}
            <button className="btn" type="submit">Add holding</button>
          </div>
        </form>
      </div>

      <div className="card">
        <div className="row">
          <button className="btn secondary" disabled={busy} onClick={refreshPrices}>
            {busy ? 'Refreshing…' : '🔄 Refresh MF NAVs + stock prices'}
          </button>
          <label className="field">Find AMFI scheme code
            <span className="row">
              <input value={amfiQ} onChange={(e) => setAmfiQ(e.target.value)}
                placeholder="scheme name contains…" />
              <button className="btn secondary" type="button" onClick={searchAmfi}>Search</button>
            </span>
          </label>
        </div>
        {amfiHits && (
          <table className="data" style={{ marginTop: 10 }}>
            <thead><tr><th>Code</th><th>Scheme</th><th className="num">NAV</th></tr></thead>
            <tbody>
              {amfiHits.length ? amfiHits.map((h) => (
                <tr key={h.code}><td>{h.code}</td><td>{h.name}</td>
                  <td className="num">{h.nav}</td></tr>
              )) : <tr><td colSpan={3} className="muted">No match (or AMFI unreachable).</td></tr>}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Holdings</h2>
        {!holdings.length ? <p className="muted">Nothing yet.</p> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data">
              <thead><tr>
                <th>Owner</th><th>Class</th><th>Name</th>
                <th className="num">Invested</th><th className="num">Current</th>
                <th className="num">P&L</th><th>Priced</th><th></th>
              </tr></thead>
              <tbody>
                {holdings.map((h) => (
                  <tr key={h.id}>
                    <td>{h.owner}</td>
                    <td>{meta.asset_class_labels[h.asset_class]}</td>
                    <td>{h.name}</td>
                    <td className="num">{inr(h.invested)}</td>
                    <td className="num">
                      {editId === h.id ? (
                        <span className="row">
                          <input autoFocus style={{ width: 110 }} type="number" step="any"
                            value={editVal} onChange={(e) => setEditVal(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && saveEdit(h)} />
                          <button className="btn" type="button" onClick={() => saveEdit(h)}>✓</button>
                        </span>
                      ) : inr(h.current_value)}
                    </td>
                    <td className="num" style={{ color: h.current_value - h.invested >= 0 ? 'var(--good-text)' : 'var(--critical)' }}>
                      {inr(h.current_value - h.invested)}
                    </td>
                    <td className="small muted">{h.price_date || h.value_date || ''}</td>
                    <td>
                      <button className="icon" title="Update value/price/balance" onClick={() => startEdit(h)}>✏️</button>
                      <button className="icon" title="Delete" onClick={() => del(h)}>🗑</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Bulk import (CSV)</h2>
        <p className="small muted">
          Columns: owner, asset_class, name, identifier, units, avg_cost,
          manual_value, last_price, rate, start_date (YYYY-MM-DD), category.
        </p>
        <div className="row">
          <a className="btn secondary" style={{ textDecoration: 'none' }}
            href={'data:text/csv;charset=utf-8,' + encodeURIComponent(template)}
            download="holdings_template.csv">Download template</a>
          <input ref={fileRef} type="file" accept=".csv" onChange={importCsv} />
        </div>
      </div>
    </div>
  )
}
