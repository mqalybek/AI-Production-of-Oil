import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import * as echarts from 'echarts'
import { getAlerts, getDailySummary, getDeferred, getProductionSummary, getWells } from '../api/endpoints'
import type { DeferredParetoItem } from '../api/types'
import { Chart } from '../components/Chart'
import { MetricCard } from '../components/MetricCard'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { SeverityBadge } from '../components/StatusBadge'
import { addDays, daysInMonth, formatDate, formatDurationSince, formatNumber, monthPeriod, todayISO } from '../utils/format'
import { CATEGORY_LABEL } from '../utils/labels'
import './MorningSummary.css'

export function MorningSummary() {
  const navigate = useNavigate()
  const today = todayISO()
  const yesterday = addDays(today, -1)
  const trendFrom = addDays(today, -29)

  const todaySummary = useQuery({ queryKey: ['daily-summary', today], queryFn: () => getDailySummary(today) })
  const yesterdaySummary = useQuery({ queryKey: ['daily-summary', yesterday], queryFn: () => getDailySummary(yesterday) })
  const monthPlan = useQuery({
    queryKey: ['production-summary', monthPeriod(today)],
    queryFn: () => getProductionSummary(monthPeriod(today), 'month'),
  })
  const losses = useQuery({
    queryKey: ['deferred-reason', today],
    queryFn: () => getDeferred(today, today, 'reason') as Promise<DeferredParetoItem[]>,
  })
  const criticalAlerts = useQuery({
    queryKey: ['alerts', 'active', 'critical'],
    queryFn: () => getAlerts({ status: 'active', severity: 'critical', limit: 20 }),
  })
  const stoppedAlerts = useQuery({
    queryKey: ['alerts', 'active', 'well_stopped'],
    queryFn: () => getAlerts({ status: 'active', limit: 200 }),
  })
  const wells = useQuery({ queryKey: ['wells-all'], queryFn: () => getWells({ limit: 500 }) })

  const trendA = useQuery({
    queryKey: ['production-summary', monthPeriod(trendFrom), 'day'],
    queryFn: () => getProductionSummary(monthPeriod(trendFrom), 'day'),
  })
  const trendB = useQuery({
    queryKey: ['production-summary', monthPeriod(today), 'day'],
    queryFn: () => getProductionSummary(monthPeriod(today), 'day'),
  })

  const todayTotalOil = useMemo(() => sum(todaySummary.data, (r) => r.q_oil_t), [todaySummary.data])
  const yesterdayTotalOil = useMemo(() => sum(yesterdaySummary.data, (r) => r.q_oil_t), [yesterdaySummary.data])
  const monthPlanTotal = useMemo(() => monthPlan.data?.[0]?.plan_oil_t ?? null, [monthPlan.data])
  const dailyPlan = monthPlanTotal !== null ? monthPlanTotal / daysInMonth(today) : null

  const wellsActive = useMemo(() => sum(todaySummary.data, (r) => r.wells_active), [todaySummary.data])
  const wellsStopped = useMemo(() => sum(todaySummary.data, (r) => r.wells_stopped), [todaySummary.data])

  const uwiById = useMemo(() => {
    const map = new Map<number, string>()
    for (const w of wells.data?.items ?? []) map.set(w.id, w.uwi)
    return map
  }, [wells.data])

  const stoppedWells = useMemo(
    () => (stoppedAlerts.data?.items ?? []).filter((a) => a.type === 'well_stopped' && a.well_id !== null),
    [stoppedAlerts.data],
  )

  const trendOption = useMemo(() => {
    const merged = [...(trendA.data ?? []), ...(trendB.data ?? [])]
    const byDate = new Map(merged.map((p) => [p.period, p.q_oil_t]))
    const dates = [...byDate.keys()].filter((d) => d >= trendFrom && d <= today).sort()
    return {
      grid: { left: 44, right: 16, top: 16, bottom: 24 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: (v: string) => v.slice(5) } },
      yAxis: { type: 'value', name: 'т/сут' },
      tooltip: { trigger: 'axis' },
      series: [
        {
          type: 'line',
          data: dates.map((d) => byDate.get(d) ?? null),
          smooth: true,
          areaStyle: { opacity: 0.08 },
          lineStyle: { color: '#1e5eff' },
          itemStyle: { color: '#1e5eff' },
          connectNulls: true,
        },
      ],
    } as echarts.EChartsOption
  }, [trendA.data, trendB.data, trendFrom, today])

  const isLoadingTop = todaySummary.isLoading || yesterdaySummary.isLoading || monthPlan.isLoading
  const errorTop = todaySummary.error || yesterdaySummary.error || monthPlan.error

  return (
    <div className="morning">
      <div className="morning__kpis">
        <QueryState isLoading={isLoadingTop} error={errorTop}>
          <MetricCard
            label="Добыча нефти сегодня"
            value={formatNumber(todayTotalOil)}
            unit="т"
            delta={
              yesterdayTotalOil
                ? {
                    value: `${formatNumber(todayTotalOil - yesterdayTotalOil)} т к вчера`,
                    direction: todayTotalOil >= yesterdayTotalOil ? 'up' : 'down',
                    good: 'up',
                  }
                : undefined
            }
          />
          <MetricCard
            label="План на сутки"
            value={dailyPlan !== null ? formatNumber(dailyPlan) : '—'}
            unit="т"
            sub={dailyPlan !== null ? `выполнение ${formatNumber((todayTotalOil / dailyPlan) * 100, 0)}%` : 'план не задан'}
          />
          <MetricCard label="Вчера" value={formatNumber(yesterdayTotalOil)} unit="т" />
          <MetricCard label="Скважин в работе" value={String(wellsActive)} sub={`простаивает: ${wellsStopped}`} />
        </QueryState>
      </div>

      <div className="morning__row">
        <Panel title={`Простаивающие скважины (${stoppedWells.length})`} className="morning__panel">
          <QueryState isLoading={stoppedAlerts.isLoading || wells.isLoading} error={stoppedAlerts.error}>
            {stoppedWells.length === 0 && <div className="morning__empty">Все скважины фонда в работе</div>}
            <ul className="morning__list">
              {stoppedWells.map((a) => (
                <li
                  key={a.id}
                  className="morning__list-item"
                  onClick={() => a.well_id && navigate(`/wells/${uwiById.get(a.well_id) ?? a.well_id}`)}
                >
                  <div className="morning__list-title">{uwiById.get(a.well_id!) ?? `#${a.well_id}`}</div>
                  <div className="morning__list-sub">{a.message}</div>
                  <div className="morning__list-meta">{formatDurationSince(a.ts_detected)}</div>
                </li>
              ))}
            </ul>
          </QueryState>
        </Panel>

        <Panel title="Топ-5 причин потерь сегодня" className="morning__panel">
          <QueryState isLoading={losses.isLoading} error={losses.error}>
            {(losses.data ?? []).length === 0 && <div className="morning__empty">Потерь не зафиксировано</div>}
            <ul className="morning__list">
              {(losses.data ?? []).slice(0, 5).map((item, i) => (
                <li key={i} className="morning__list-item morning__list-item--static">
                  <div className="morning__list-title">{item.reason_name ?? CATEGORY_LABEL[item.category] ?? item.category}</div>
                  <div className="morning__loss-bar">
                    <div className="morning__loss-bar-fill" style={{ width: `${item.share_pct}%` }} />
                  </div>
                  <div className="morning__list-meta">
                    {formatNumber(item.volume_oil_t)} т ({formatNumber(item.share_pct, 0)}%)
                  </div>
                </li>
              ))}
            </ul>
          </QueryState>
        </Panel>

        <Panel title="Активные критичные алерты" className="morning__panel">
          <QueryState isLoading={criticalAlerts.isLoading} error={criticalAlerts.error}>
            {(criticalAlerts.data?.items ?? []).length === 0 && <div className="morning__empty">Критичных алертов нет</div>}
            <ul className="morning__list">
              {(criticalAlerts.data?.items ?? []).map((a) => (
                <li key={a.id} className="morning__list-item morning__list-item--static">
                  <div className="morning__list-title">
                    <SeverityBadge severity={a.severity} /> {a.well_id ? uwiById.get(a.well_id) ?? `#${a.well_id}` : `узел #${a.node_id}`}
                  </div>
                  <div className="morning__list-sub">{a.message}</div>
                  <div className="morning__list-meta">{formatDurationSince(a.ts_detected)}</div>
                </li>
              ))}
            </ul>
          </QueryState>
        </Panel>
      </div>

      <Panel title="Динамика добычи нефти, 30 суток" className="morning__trend">
        <QueryState isLoading={trendA.isLoading || trendB.isLoading} error={trendA.error || trendB.error}>
          <Chart option={trendOption} height={200} />
        </QueryState>
      </Panel>

      <div className="morning__caption">{formatDate(today)}</div>
    </div>
  )
}

function sum<T>(rows: T[] | undefined, pick: (row: T) => number): number {
  return (rows ?? []).reduce((acc, r) => acc + pick(r), 0)
}
