import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts'
import { useMemo, useState } from 'react'
import { getDeferred, getDeferredMonthly, getFields, getWells } from '../api/endpoints'
import type { DeferredAggregateItem, DeferredParetoItem } from '../api/types'
import { Chart } from '../components/Chart'
import { MetricCard } from '../components/MetricCard'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { addDays, formatNumber, todayISO } from '../utils/format'
import { CATEGORY_LABEL } from '../utils/labels'
import './LossAnalysis.css'

const GROUPBY_OPTIONS = [
  { value: 'well', label: 'По скважинам' },
  { value: 'node', label: 'По узлам сбора' },
  { value: 'reservoir', label: 'По объектам' },
  { value: 'field', label: 'По месторождениям' },
]

const MODE_OPTIONS = [
  { value: 'daily', label: 'Сутки (АГЗУ)' },
  { value: 'monthly', label: 'Месяц (простой)' },
]

export function LossAnalysis() {
  const to = todayISO()
  const [from, setFrom] = useState(addDays(to, -30))
  const [groupBy, setGroupBy] = useState('well')
  const [mode, setMode] = useState<'daily' | 'monthly'>('daily')
  const isMonthly = mode === 'monthly'

  const pareto = useQuery({
    queryKey: ['deferred-pareto', from, to],
    queryFn: () => getDeferred(from, to, 'reason') as Promise<DeferredParetoItem[]>,
    enabled: !isMonthly,
  })
  const breakdown = useQuery({
    queryKey: ['deferred-breakdown', mode, from, to, groupBy],
    queryFn: () =>
      isMonthly ? getDeferredMonthly(from, to, groupBy) : (getDeferred(from, to, groupBy, 'day') as Promise<DeferredAggregateItem[]>),
  })
  const dynamics = useQuery({
    queryKey: ['deferred-dynamics', mode, from, to],
    queryFn: () =>
      isMonthly ? getDeferredMonthly(from, to, 'field') : (getDeferred(from, to, 'field', 'day') as Promise<DeferredAggregateItem[]>),
  })
  const wells = useQuery({ queryKey: ['wells-all'], queryFn: () => getWells({ limit: 500 }), enabled: groupBy === 'well' })
  const fields = useQuery({ queryKey: ['fields'], queryFn: getFields, enabled: groupBy === 'field' })

  const breakdownLabel = useMemo(() => {
    const map = new Map<number, string>()
    if (groupBy === 'well') for (const w of wells.data?.items ?? []) map.set(w.id, w.uwi)
    if (groupBy === 'field') for (const f of fields.data ?? []) map.set(f.id, f.name)
    return (id: number) => map.get(id) ?? `#${id}`
  }, [groupBy, wells.data, fields.data])

  const paretoOption = useMemo(() => {
    const rows = pareto.data ?? []
    const labels = rows.map((r) => r.reason_name ?? CATEGORY_LABEL[r.category] ?? r.category)
    return {
      grid: { left: 60, right: 50, top: 20, bottom: 70 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: labels, axisLabel: { rotate: 35, fontSize: 10 } },
      yAxis: [
        { type: 'value', name: 'т' },
        { type: 'value', name: '%', min: 0, max: 100, position: 'right' },
      ],
      series: [
        { name: 'Потери, т', type: 'bar', data: rows.map((r) => r.volume_oil_t), itemStyle: { color: '#1e5eff' } },
        {
          name: 'Накопленная доля, %',
          type: 'line',
          yAxisIndex: 1,
          data: rows.map((r) => r.cumulative_pct),
          itemStyle: { color: '#d92d20' },
        },
      ],
    } as echarts.EChartsOption
  }, [pareto.data])

  const breakdownOption = useMemo(() => {
    const totals = new Map<number, number>()
    for (const r of breakdown.data ?? []) {
      if (r.group === null) continue
      totals.set(r.group, (totals.get(r.group) ?? 0) + r.volume_oil_t)
    }
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15)
    return {
      grid: { left: 70, right: 20, top: 10, bottom: 24 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'value', name: 'т' },
      yAxis: { type: 'category', data: top.map(([id]) => breakdownLabel(id)).reverse(), axisLabel: { fontSize: 10 } },
      series: [{ type: 'bar', data: top.map(([, v]) => v).reverse(), itemStyle: { color: '#1e5eff' } }],
    } as echarts.EChartsOption
  }, [breakdown.data, breakdownLabel])

  const dynamicsOption = useMemo(() => {
    const byDate = new Map<string, number>()
    for (const r of dynamics.data ?? []) byDate.set(r.period, (byDate.get(r.period) ?? 0) + r.volume_oil_t)
    const dates = [...byDate.keys()].sort()
    return {
      grid: { left: 50, right: 16, top: 10, bottom: 24 },
      tooltip: { trigger: 'axis' },
      xAxis: {
        type: 'category',
        data: dates,
        axisLabel: { formatter: (v: string) => (isMonthly ? v.slice(0, 7) : v.slice(5)), fontSize: 10 },
      },
      yAxis: { type: 'value', name: isMonthly ? 'т/мес' : 'т/сут' },
      series: [
        { type: 'bar', data: dates.map((d) => byDate.get(d) ?? 0), itemStyle: { color: '#1e5eff' } },
      ],
    } as echarts.EChartsOption
  }, [dynamics.data, isMonthly])

  const totalLoss = isMonthly
    ? (breakdown.data ?? []).reduce((acc, r) => acc + r.volume_oil_t, 0)
    : (pareto.data ?? []).reduce((acc, r) => acc + r.volume_oil_t, 0)
  const affectedGroups = new Set((breakdown.data ?? []).filter((r) => r.group !== null).map((r) => r.group)).size

  return (
    <div className="loss-analysis">
      <div className="loss-analysis__controls">
        <label>
          С <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} max={to} />
        </label>
        <select value={mode} onChange={(e) => setMode(e.target.value as 'daily' | 'monthly')}>
          {MODE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <span className="loss-analysis__total">Итого потерь: {formatNumber(totalLoss)} т</span>
      </div>

      <div className="loss-analysis__row">
        {isMonthly ? (
          <Panel title="Оценка потерь от простоя" className="loss-analysis__panel">
            <div className="loss-analysis__monthly-stats">
              <MetricCard label="Потери от простоя" value={formatNumber(totalLoss)} unit="т" />
              <MetricCard
                label={GROUPBY_OPTIONS.find((o) => o.value === groupBy)?.label ?? 'Групп'}
                value={String(affectedGroups)}
                sub="затронуто простоем"
              />
            </div>
            <p className="loss-analysis__note">
              Парето по причинам недоступно для помесячных данных — причина простоя не фиксируется в отчёте, только
              факт (отработанные дни меньше календарных).
            </p>
          </Panel>
        ) : (
          <Panel title="Парето по причинам" className="loss-analysis__panel">
            <QueryState isLoading={pareto.isLoading} error={pareto.error}>
              <Chart option={paretoOption} height={260} />
            </QueryState>
          </Panel>
        )}

        <Panel
          title="Разбивка по узлу"
          className="loss-analysis__panel"
          action={
            <select value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
              {GROUPBY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          }
        >
          <QueryState isLoading={breakdown.isLoading} error={breakdown.error}>
            <Chart option={breakdownOption} height={260} />
          </QueryState>
        </Panel>
      </div>

      <Panel title={isMonthly ? 'Динамика потерь по месяцам' : 'Динамика потерь по суткам'}>
        <QueryState isLoading={dynamics.isLoading} error={dynamics.error}>
          <Chart option={dynamicsOption} height={180} />
        </QueryState>
      </Panel>
    </div>
  )
}
