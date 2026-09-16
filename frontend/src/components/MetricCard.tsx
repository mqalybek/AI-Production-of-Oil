import './MetricCard.css'

interface MetricCardProps {
  label: string
  value: string
  unit?: string
  delta?: { value: string; direction: 'up' | 'down' | 'flat'; good?: 'up' | 'down' | 'flat' }
  sub?: string
}

export function MetricCard({ label, value, unit, delta, sub }: MetricCardProps) {
  const deltaTone = delta ? (delta.direction === delta.good ? 'good' : delta.direction === 'flat' ? 'flat' : 'bad') : undefined

  return (
    <div className="metric-card">
      <div className="metric-card__label">{label}</div>
      <div className="metric-card__value">
        <span className="numeric">{value}</span>
        {unit && <span className="metric-card__unit">{unit}</span>}
      </div>
      {delta && (
        <div className={`metric-card__delta metric-card__delta--${deltaTone}`}>
          {delta.direction === 'up' ? '▲' : delta.direction === 'down' ? '▼' : '—'} {delta.value}
        </div>
      )}
      {sub && <div className="metric-card__sub">{sub}</div>}
    </div>
  )
}
