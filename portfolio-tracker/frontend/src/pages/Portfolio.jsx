import { useMemo, useRef, useState } from 'react'
import { api, BUCKET_LABELS, inr } from '../api'

const UNIT_CLASSES = ['mutual_fund', 'stock', 'gold_etf', 'reit', 'sgb', 'nps', 'gold_physical']
const BALANCE_CLASSES = ['savings', 'epf', 'ppf', 'other']
const MF_CATEGORIES = ['equity', 'debt', 'hybrid', 'elss', 'liquid', 'gold']
const BUCKETS = ['equity', 'debt', 'gold', 'real_estate', 'cash', 'other']

const emptyForm = {
  asset_class: 'mutual_fund', name: '', identifier: '', units: '', avg_cost: '',
  last_price: '', manual_value: '', rate: '', start_date: '', category: 'equity',
  bucket: '', maturity_date: '', purchase_date: '', notes: '',
}

export default function Portfolio({ summary, meta, owners, reload }) {
  const [form, setForm] = useState({ ...emptyForm, owner_id: '' })
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [amfiQ, setAmfiQ] = useState('')
  const [amfiHits, setAmfiHits] = useState(null)
  const [editId, setEditId] = useState(null)
  const [editVal, setEditVal] = useState('')
  const [editMaturity, setEditMaturity] = useState('')
  const [splitId, setSplitId] = useState(null)
  const [splitVals, setSplitVals] = useState({})
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
        ...(form.bucket ? { bucket: form.bucket } : {}),
        ...(cls === 'fd' && form.maturity_date
          ? { maturity_date: form.maturity_date } : {}),
        ...(form.purchase_date ? { purchase_date: form.purchase_date } : {}),
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
    setEditMaturity(h.meta?.maturity_date || '')
    setEditVal(String(
      BALANCE_CLASSES.includes(h.asset_class) ? h.manual_value
        : h.asset_class === 'fd' ? h.avg_cost : h.last_price || 0))
  }

  const saveEdit = async (h) => {
    const v = +editVal || 0
    const payload = BALANCE_CLASSES.includes(h.asset_class)
      ? { manual_value: v }
      : h.asset_class === 'fd' ? { avg_cost: v } : { last_price: v }
    if (h.asset_class === 'fd') payload.meta = { maturity_date: editMaturity }
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

  const template = 'owner,asset_class,name,identifier,units,avg_cost,manual_value,last_price,rate,start_date,category,bucket,maturity_date,purchase_date\n' +
    'Me,mutual_fund,Parag Parikh Flexi Cap Dir-G,122639,512.33,55.1,0,81.2,0,,equity,,,2023-04-10\n' +
    'Me,stock,Reliance Industries,RELIANCE,10,2400,0,2950,0,,,,,2024-11-02\n' +
    'Wife,fd,HDFC sweep FD,XXXX1234,0,500000,0,0,7.1,2025-01-15,,cash,2026-01-15,\n' +
    'Me,fd,SBI 5yr tax saver FD,XXXX9911,0,150000,0,0,7.0,2024-03-01,,,2029-03-01,\n' +
    'Me,ppf,SBI PPF,,0,0,450000,0,7.1,,,,,\n'

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
              <label className="field">Maturity date
                <input type="date" value={form.maturity_date}
                  onChange={set('maturity_date')} />
              </label>
            </>)}
            {!isUnit && !isFd && (<>
              <label className="field">Current balance / value
                <input type="number" step="any" required value={form.manual_value} onChange={set('manual_value')} />
              </label>
              <label className="field">Rate % p.a. (0 = no accrual)
                <input type="number" step="any" value={form.rate} onChange={set('rate')} />
              </label>
            </>)}
            <label className="field">Bought on
              <input type="date" value={form.purchase_date}
                title="Enables short vs long-term classification"
                onChange={set('purchase_date')} />
            </label>
            <label className="field">Counts as
              <select value={form.bucket} onChange={set('bucket')}>
                <option value="">Auto (by asset class)</option>
                {BUCKETS.map((b) => (
                  <option key={b} value={b}>{BUCKET_LABELS[b]}</option>
                ))}
              </select>
            </label>
            <button className="btn" type="submit">Add holding</button>
          </div>
          <p className="small muted">
            <b>Counts as</b> overrides which allocation bucket this lands in.
            Leave it on Auto unless the default is wrong for you — e.g. file a
            sweep FD under Cash so it counts toward your emergency fund, while
            a 5-year FD stays in Debt. FDs also count as emergency money
            automatically once their maturity date is within 12 months.
            <b> Bought on</b> is what lets the app tell short-term from
            long-term holdings — without it, no tax view is possible.
          </p>
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
                <th>Owner</th><th>Class</th><th>Name</th><th>Counts as</th>
                <th className="num">Invested</th><th className="num">Current</th>
                <th className="num">P&L</th><th>Priced</th><th></th>
              </tr></thead>
              <tbody>
                {holdings.map((h) => [(
                  <tr key={h.id}>
                    <td>{h.owner}</td>
                    <td>{meta.asset_class_labels[h.asset_class]}</td>
                    <td>{h.name}</td>
                    <td>
                      <select value={h.meta?.bucket || ''}
                        style={{ padding: '2px 4px', fontSize: 12 }}
                        title={h.meta?.bucket
                          ? 'Overridden - click to change or return to auto'
                          : 'Automatic from the asset class'}
                        onChange={async (ev) => {
                          await api.put('/api/holdings/' + h.id,
                            { meta: { bucket: ev.target.value } })
                          reload()
                        }}>
                        <option value="">{BUCKET_LABELS[h.bucket]} (auto)</option>
                        {BUCKETS.map((b) => (
                          <option key={b} value={b}>{BUCKET_LABELS[b]}</option>
                        ))}
                      </select>
                      <button className="icon" title="Split across buckets (multi-asset funds)"
                        onClick={() => {
                          setSplitId(splitId === h.id ? null : h.id)
                          setSplitVals(h.meta?.splits || {})
                        }}>⊞</button>
                      {h.has_split && (
                        <span className="small muted"> split</span>
                      )}
                      {h.asset_class === 'fd' && (
                        <span className="small muted"> {h.meta?.maturity_date
                          ? 'mat. ' + h.meta.maturity_date : 'no maturity set'}</span>
                      )}
                    </td>
                    <td className="num">{inr(h.invested)}</td>
                    <td className="num">
                      {editId === h.id ? (
                        <span className="row">
                          <input autoFocus style={{ width: 110 }} type="number" step="any"
                            value={editVal} onChange={(e) => setEditVal(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && saveEdit(h)} />
                          {h.asset_class === 'fd' && (
                            <input type="date" title="Maturity date"
                              style={{ width: 140 }} value={editMaturity}
                              onChange={(e) => setEditMaturity(e.target.value)} />
                          )}
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
                ),
                splitId === h.id && (
                  <tr key={h.id + '-split'}>
                    <td colSpan={9} style={{ background: 'var(--page)' }}>
                      <div className="row" style={{ alignItems: 'end' }}>
                        <span className="small">
                          <b>Look-through split for {h.name}</b><br />
                          <span className="muted">
                            A multi-asset fund is not 100% equity. Enter the
                            fund&apos;s own asset mix; leave all blank for automatic.
                          </span>
                        </span>
                        {BUCKETS.map((b) => (
                          <label className="field" key={b}>{BUCKET_LABELS[b]} %
                            <input type="number" step="any" style={{ width: 78 }}
                              value={splitVals[b] ?? ''}
                              onChange={(e) => setSplitVals({
                                ...splitVals, [b]: e.target.value,
                              })} />
                          </label>
                        ))}
                        <button className="btn" onClick={async () => {
                          const clean = {}
                          for (const [k, v] of Object.entries(splitVals)) {
                            if (+v > 0) clean[k] = +v
                          }
                          await api.put('/api/holdings/' + h.id, {
                            meta: { splits: Object.keys(clean).length ? clean : '' },
                          })
                          setSplitId(null)
                          reload()
                        }}>Save split</button>
                        <button className="btn secondary"
                          onClick={() => setSplitId(null)}>Cancel</button>
                      </div>
                      <p className="small muted">
                        Percentages are normalised, so 65/20/15 and 13/4/3 mean
                        the same thing.
                      </p>
                    </td>
                  </tr>
                )]).flat().filter(Boolean)}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {summary.unrealised && summary.unrealised.totals.count > 0 && (
        <div className="card">
          <h2>Unrealised gains &amp; losses</h2>
          <div className="grid cols-4">
            <div className="stat">
              <div className="label">Unrealised gains</div>
              <div className="value pos">{inr(summary.unrealised.totals.gain)}</div>
              <div className="sub">
                long {inr(summary.unrealised.totals.long_gain)} · short{' '}
                {inr(summary.unrealised.totals.short_gain)}
              </div>
            </div>
            <div className="stat">
              <div className="label">Unrealised losses</div>
              <div className="value neg">{inr(summary.unrealised.totals.loss)}</div>
              <div className="sub">
                {summary.unrealised.totals.losers} of{' '}
                {summary.unrealised.totals.count} holdings underwater
              </div>
            </div>
            <div className="stat">
              <div className="label">Net</div>
              <div className="value">
                {inr(summary.unrealised.totals.gain + summary.unrealised.totals.loss)}
              </div>
            </div>
            <div className="stat">
              <div className="label">Term unknown</div>
              <div className="value">{summary.unrealised.totals.undated}</div>
              <div className="sub">holdings with no purchase date</div>
            </div>
          </div>
          <p className="small muted">
            Long vs short term uses a simplified rule (12 months for listed
            equity and equity funds, 24 otherwise) — confirm specifics with a
            CA. Losses offset gains <i>before</i> any exemption applies, so
            which year you book them in matters.
          </p>
        </div>
      )}

      <div className="card">
        <h2>Bulk import (CSV)</h2>
        <p className="small muted">
          Columns: owner, asset_class, name, identifier, units, avg_cost,
          manual_value, last_price, rate, start_date, category, bucket,
          maturity_date, purchase_date. Dates are YYYY-MM-DD; bucket
          overrides the allocation bucket (blank = automatic).
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
