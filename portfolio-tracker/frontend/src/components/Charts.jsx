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

export function AllocationChart({ drift, bucketLabels }) {
  const data = drift
    .filter((d) => d.actual_pct > 0 || d.target_pct > 0)
    .map((d) => ({
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
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => v + '%'}
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
