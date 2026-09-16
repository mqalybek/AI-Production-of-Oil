import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getDataQuality } from '../api/endpoints'
import { MetricCard } from '../components/MetricCard'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { addDays, todayISO } from '../utils/format'
import './DataQuality.css'

export function DataQuality() {
  const to = todayISO()
  const [from, setFrom] = useState(addDays(to, -30))

  const dq = useQuery({ queryKey: ['data-quality', from, to], queryFn: () => getDataQuality(from, to) })

  const validShare =
    dq.data && dq.data.valid_tests + dq.data.invalid_tests > 0
      ? (100 * dq.data.valid_tests) / (dq.data.valid_tests + dq.data.invalid_tests)
      : null

  return (
    <div className="data-quality">
      <div className="data-quality__controls">
        <label>
          С <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} max={to} />
        </label>
        <span className="data-quality__period">по {to}</span>
      </div>

      <Panel title="Метрики качества данных за период">
        <QueryState isLoading={dq.isLoading} error={dq.error}>
          {dq.data && (
            <div className="data-quality__grid">
              <MetricCard
                label="Забракованные замеры"
                value={String(dq.data.invalid_tests)}
                sub={`из ${dq.data.valid_tests + dq.data.invalid_tests} всего`}
              />
              <MetricCard
                label="Доля валидных замеров"
                value={validShare !== null ? validShare.toFixed(0) : '—'}
                unit="%"
              />
              <MetricCard label="Записи в карантине загрузки" value={String(dq.data.quarantined_records)} />
              <MetricCard label="Скважины без свежих замеров" value={String(dq.data.wells_without_recent_test)} />
              <MetricCard
                label="Суток с низкой уверенностью аллокации"
                value={String(dq.data.low_confidence_allocation_days)}
                sub="material balance discrepancy proxy"
              />
            </div>
          )}
        </QueryState>
      </Panel>
    </div>
  )
}
