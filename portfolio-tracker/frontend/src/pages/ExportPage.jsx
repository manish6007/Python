import { useState } from 'react'
import { api } from '../api'

export default function ExportPage() {
  const [privacy, setPrivacy] = useState(true)
  const [preview, setPreview] = useState('')
  const [copied, setCopied] = useState(false)
  const p = privacy ? 1 : 0

  const loadPreview = async () => {
    setPreview(JSON.stringify(await api.get('/api/export/json?privacy=' + p), null, 2))
  }

  const copyAiPackage = async () => {
    const text = await api.get('/api/export/ai-package?privacy=' + p)
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2500)
  }

  return (
    <div className="grid">
      <div className="card">
        <h2>Export snapshot</h2>
        <p className="muted">
          Generate a portfolio snapshot to archive, or to paste into Claude for
          an optimization review. Privacy-safe mode strips owner names and
          masks folio/account numbers while keeping every number that matters.
        </p>
        <label className="row" style={{ alignItems: 'center', margin: '10px 0' }}>
          <input type="checkbox" checked={privacy}
            onChange={(e) => setPrivacy(e.target.checked)} />
          Privacy-safe mode (recommended before sharing with any AI)
        </label>
        <div className="row">
          <a className="btn" style={{ textDecoration: 'none' }}
            href={'/api/export/pdf?privacy=' + p}>⬇ Download PDF</a>
          <button className="btn secondary" onClick={copyAiPackage}>
            {copied ? '✓ Copied!' : '📋 Copy AI review package (prompt + JSON)'}
          </button>
          <button className="btn secondary" onClick={loadPreview}>Preview JSON</button>
        </div>
        <p className="small muted" style={{ marginTop: 10 }}>
          Workflow: copy the AI package → paste into a Claude chat → get an
          allocation / overlap / tax / debt review. It is educational analysis,
          not investment advice.
        </p>
      </div>
      {preview && (
        <div className="card">
          <h2>JSON preview</h2>
          <pre className="export">{preview}</pre>
        </div>
      )}
    </div>
  )
}
