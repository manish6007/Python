import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { SERIES, inr, inrShort } from '../api'

const tooltipStyle = {
  background: 'var(--surface-1)', border: '1px solid var(--border)',
  borderRadius: 8, color: 'var(--text-primary)', fontSize: 12,
}
const axisTick = { fill: 'var(--muted)', fontSize: 11 }

// Fixed slot assignment: color follows the asset class, never its rank.
const CLASS_ORDER = [
  'mutual_fund', 'stock', 'gold_physical', 'sgb', 'gold_etf', 'reit',
  'fd', 'savings', 'epf', 'ppf', 'nps', 'other',
]
const classColor = (cls) =>
  SERIES[CLASS_ORDER.indexOf(cls) % SERIES.length]

export function DonutByClass({ byClass, labels }) {
  const data = Object.entries(byClass)
    .filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({ key: k, name: labels[k] || k, value: v }))
  if (!data.length) return <p className="muted">No holdings yet.</p>
  return (
    <>
      <ResponsiveContainer width="100%" height={260}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="55%"
            outerRadius="85%" paddingAngle={1.5} stroke="var(--surface-1)"
            strokeWidth={2}>
            {data.map((d) => <Cell key={d.key} fill={classColor(d.key)} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} formatter={(v) => inr(v)} />
        </PieChart>
      </ResponsiveContainer>
      <div className="legend">
        {data.map((d) => (
          <span key={d.key}>
            <i style={{ background: classColor(d.key) }} />
            {d.name} · {inrShort(d.value)}
          </span>
        ))}
      </div>
    </>
  )
}

export function OwnerBar({ byOwner }) {
  const data = Object.entries(byOwner).map(([k, v]) => ({ name: k, value: v }))
  if (!data.length) return <p className="muted">No holdings yet.</p>
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 8 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="name" tick={axisTick} axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
        <YAxis tick={axisTick} tickFormatter={inrShort} axisLine={false} tickLine={false} width={64} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => inr(v)}
          cursor={{ fill: 'var(--grid)', opacity: 0.4 }} />
        <Bar dataKey="value" name="Value" fill="var(--series-1)"
          radius={[4, 4, 0, 0]} maxBarSize={64} />
      </BarChart>
    </ResponsiveContainer>
  )
}

// Tooltip that answers "what is actually inside this bucket?"
function BucketTooltip({ active, payload, contents }) {
  if (!active || !payload || !payload.length) return null
  const row = payload[0].payload
  const items = (contents && contents[row.bucket]) || []
  const total = items.reduce((a, h) => a + h.current_value, 0)
  return (
    <div style={{
      background: 'var(--surface-1)', border: '1px solid var(--border)',
      borderRadius: 8, padding: '8px 10px', fontSize: 12,
      color: 'var(--text-primary)', maxWidth: 300,
    }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        {row.name} — {inr(total)}
      </div>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>
        actual {row.Actual}% · target {row.Target}%
      </div>
      {items.length ? (
        <>
          {items.slice(0, 6).map((h) => (
            <div key={h.id} style={{
              display: 'flex', justifyContent: 'space-between', gap: 12,
              color: 'var(--text-secondary)',
            }}>
              <span>{h.name.length > 30 ? h.name.slice(0, 29) + '…' : h.name}</span>
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                {inrShort(h.current_value)}
              </span>
            </div>
          ))}
          {items.length > 6 && (
            <div style={{ color: 'var(--muted)', marginTop: 4 }}>
              +{items.length - 6} more
            </div>
          )}
        </>
      ) : (
        <div style={{ color: 'var(--muted)' }}>Nothing in this bucket yet.</div>
      )}
    </div>
  )
}

export function AllocationChart({ drift, bucketLabels, holdings = [] }) {
  const contents = {}
  for (const h of holdings) {
    (contents[h.bucket] = contents[h.bucket] || []).push(h)
  }
  for (const k of Object.keys(contents)) {
    contents[k].sort((a, b) => b.current_value - a.current_value)
  }
  const data = drift
    .filter((d) => d.actual_pct > 0 || d.target_pct > 0)
    .map((d) => ({
      bucket: d.bucket,
      name: bucketLabels[d.bucket] || d.bucket,
      Actual: +d.actual_pct.toFixed(1),
      Target: +d.target_pct.toFixed(1),
    }))
  if (!data.length) return <p className="muted">Set targets in Settings.</p>
  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 8 }} barGap={2}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="name" tick={axisTick} axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
        <YAxis tick={axisTick} unit="%" axisLine={false} tickLine={false} width={44} />
        <Tooltip content={<BucketTooltip contents={contents} />}
          cursor={{ fill: 'var(--grid)', opacity: 0.4 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="Actual" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={40} />
        <Bar dataKey="Target" fill="var(--baseline)" radius={[4, 4, 0, 0]} maxBarSize={40} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function TrendChart({ snapshots }) {
  if (!snapshots.length) {
    return <p className="muted">Take a snapshot each month to build the trend.</p>
  }
  const data = snapshots.map((s) => ({
    date: s.date, 'Net worth': s.net_worth, Assets: s.total_assets,
    Liabilities: s.total_liabilities,
  }))
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 8 }}>
        <CartesianGrid stroke="var(--grid)" vertical={false} />
        <XAxis dataKey="date" tick={axisTick} axisLine={{ stroke: 'var(--baseline)' }} tickLine={false} />
        <YAxis tick={axisTick} tickFormatter={inrShort} axisLine={false} tickLine={false} width={64} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => inr(v)} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="Net worth" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 3 }} />
        <Line type="monotone" dataKey="Assets" stroke="var(--series-3)" strokeWidth={2} dot={{ r: 3 }} />
        <Line type="monotone" dataKey="Liabilities" stroke="var(--series-2)" strokeWidth={2} dot={{ r: 3 }} />
      </LineChart>
    </ResponsiveContainer>
  )
}
