import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import Cashflow from './pages/Cashflow'
import Dashboard from './pages/Dashboard'
import ExportPage from './pages/ExportPage'
import FI from './pages/FI'
import Loans from './pages/Loans'
import Portfolio from './pages/Portfolio'
import Settings from './pages/Settings'

const TABS = ['Dashboard', 'Portfolio', 'Cashflow', 'Loans', 'FI', 'Export', 'Settings']

export default function App() {
  const [tab, setTab] = useState('Dashboard')
  const [summary, setSummary] = useState(null)
  const [meta, setMeta] = useState(null)
  const [owners, setOwners] = useState([])
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [s, o] = await Promise.all([api.get('/api/summary'), api.get('/api/owners')])
      setSummary(s)
      setOwners(o)
      setError('')
    } catch (e) {
      setError('Cannot reach the backend (' + e.message + '). Is uvicorn running on port 8000?')
    }
  }, [])

  useEffect(() => {
    api.get('/api/meta').then(setMeta).catch(() => {})
    reload()
  }, [reload])

  const ctx = { summary, meta, owners, reload }
  return (
    <>
      <header className="topbar">
        <h1>💰 Portfolio Tracker</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={t === tab ? 'active' : ''}
              onClick={() => setTab(t)}>{t}</button>
          ))}
        </nav>
      </header>
      <main className="page">
        {error && <div className="notice">{error}</div>}
        {!summary || !meta ? (!error && <p className="muted">Loading…</p>) : (
          <>
            {tab === 'Dashboard' && <Dashboard {...ctx} />}
            {tab === 'Portfolio' && <Portfolio {...ctx} />}
            {tab === 'Cashflow' && <Cashflow {...ctx} />}
            {tab === 'Loans' && <Loans {...ctx} />}
            {tab === 'FI' && <FI {...ctx} />}
            {tab === 'Export' && <ExportPage {...ctx} />}
            {tab === 'Settings' && <Settings {...ctx} />}
          </>
        )}
      </main>
    </>
  )
}
