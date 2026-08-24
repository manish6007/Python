import { useEffect, useState } from 'react'
import { api, BUCKET_LABELS } from '../api'

export default function Settings({ owners, reload }) {
  const [settings, setSettings] = useState(null)
  const [newOwner, setNewOwner] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => { api.get('/api/settings').then(setSettings) }, [])
  if (!settings) return <p className="muted">Loading…</p>

  const targets = settings.targets
  const targetSum = Object.values(targets).reduce((a, b) => a + (+b || 0), 0)

  const save = async () => {
    await api.put('/api/settings', settings)
    setMsg('Saved.')
    reload()
  }

  const addOwner = async (e) => {
    e.preventDefault()
    try {
      await api.post('/api/owners', { name: newOwner })
      setNewOwner('')
      reload()
    } catch (err) { setMsg('Error: ' + err.message) }
  }

  const loadDemo = async () => {
    await api.post('/api/demo-data')
    setMsg('Demo data loaded (all names start with DEMO — delete them from Portfolio when done exploring).')
    reload()
  }

  return (
    <div className="grid">
      {msg && <div className="notice">{msg}</div>}

      <div className="card">
        <h2>Household members</h2>
        <div className="row">
          {owners.map((o) => (
            <span key={o.id} className="card" style={{ padding: '6px 12px' }}>
              {o.name}
              <button className="icon" title="Delete (must have no holdings)"
                onClick={async () => {
                  try { await api.del('/api/owners/' + o.id); reload() }
                  catch (err) { setMsg('Error: ' + err.message) }
                }}>✕</button>
            </span>
          ))}
          <form className="row" onSubmit={addOwner}>
            <input placeholder="Add member (e.g. Wife)" value={newOwner}
              onChange={(e) => setNewOwner(e.target.value)} />
            <button className="btn secondary" type="submit">Add</button>
          </form>
        </div>
      </div>

      <div className="card">
        <h2>Target asset allocation (%)</h2>
        <div className="row">
          {Object.keys(BUCKET_LABELS).map((b) => (
            <label className="field" key={b}>{BUCKET_LABELS[b]}
              <input type="number" step="any" style={{ width: 90 }}
                value={targets[b] ?? 0}
                onChange={(e) => setSettings({
                  ...settings,
                  targets: { ...targets, [b]: +e.target.value || 0 },
                })} />
            </label>
          ))}
        </div>
        <p className={'small ' + (Math.abs(targetSum - 100) > 0.5 ? '' : 'muted')}
          style={Math.abs(targetSum - 100) > 0.5 ? { color: 'var(--critical)' } : {}}>
          Total: {targetSum.toFixed(0)}% {Math.abs(targetSum - 100) > 0.5 && '— should add up to 100%'}
        </p>
      </div>

      <div className="card">
        <h2>Planning inputs</h2>
        <div className="row">
          {[['emergency_fund_target', 'Emergency fund target (₹)'],
            ['savings_float', 'Savings account float (₹, keep this much idle)'],
            ['tax_80c_used', '80C used this FY (₹, blank = not tracked)'],
            ['tax_80ccd1b_used', 'NPS 80CCD(1B) used this FY (₹)']].map(([k, label]) => (
              <label className="field" key={k}>{label}
                <input type="number" step="any" style={{ width: 200 }}
                  value={settings[k]}
                  onChange={(e) => setSettings({ ...settings, [k]: e.target.value })} />
              </label>
            ))}
        </div>
        <div className="row" style={{ marginTop: 12 }}>
          <button className="btn" onClick={save}>Save settings</button>
        </div>
      </div>

      <div className="card">
        <h2>Demo data</h2>
        <p className="muted small">Loads a realistic sample household (holdings
          named "DEMO …") so you can explore every screen before entering real data.</p>
        <div className="row">
          <button className="btn secondary" onClick={loadDemo}>Load demo data</button>
          <button className="btn secondary" onClick={async () => {
            const r = await api.del('/api/demo-data')
            setMsg('Removed ' + r.removed + ' demo records. Your own data was untouched.')
            reload()
          }}>Clear demo data</button>
        </div>
      </div>

      <div className="card">
        <h2>Danger zone</h2>
        <p className="muted small">Erases every holding, loan, entry, snapshot
          and member — a completely fresh start. Settings/targets are kept.
          (Equivalent to deleting backend/portfolio.db.)</p>
        <button className="btn danger" onClick={async () => {
          if (!window.confirm('Erase ALL data? This cannot be undone.')) return
          if (window.prompt('Type ERASE to confirm') !== 'ERASE') return
          await api.post('/api/reset', { confirm: 'ERASE' })
          setMsg('All data erased.')
          reload()
        }}>Erase ALL data</button>
      </div>
    </div>
  )
}
