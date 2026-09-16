import { useQuery } from '@tanstack/react-query'
import * as echarts from 'echarts'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  getDeferred,
  getWellCard,
  getWellEvents,
  getWellProduction,
  getWellTelemetry,
  getWellTests,
} from '../api/endpoints'
import type { DeferredAggregateItem, WellTestOut } from '../api/types'
import { Chart } from '../components/Chart'
import type { Column } from '../components/DataTable'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { WellStatusBadge } from '../components/StatusBadge'
import { addDays, formatDate, formatDateTime, formatNumber, todayISO } from '../utils/format'
import { WELL_TYPE_LABEL } from '../utils/labels'
import './WellCardPage.css'

const TELEMETRY_TAGS = 'p_buf,p_zatr,esp_current_a,esp_load_pct'
const TAG_LABEL: Record<string, string> = {
  p_buf: 'Рбуф, атм',
  p_zatr: 'Рзатр, атм',
  esp_current_a: 'Ток ЭЦН, А',
  esp_load_pct: 'Загрузка ЭЦН, %',
}

const EQUIPMENT_LABEL: Record<string, string> = {
  esp: 'ЭЦН',
  srp: 'ШГН',
  flowing: 'Фонтан',
  gas_lift: 'Газлифт',
}

const EVENT_KIND_LABEL: Record<string, string> = {
  gtm: 'ГТМ',
  equipment: 'Оборудование',
  downtime: 'Простой',
}

export function WellCardPage() {
  const { uwi = '' } = useParams()
  const to = todayISO()
  const from90 = addDays(to, -90)
  const from30 = addDays(to, -30)

  const card = useQuery({ queryKey: ['well-card', uwi], queryFn: () => getWellCard(uwi) })
  const production = useQuery({
    queryKey: ['well-production', uwi, from90],
    queryFn: () => getWellProduction(uwi, from90, to, 'day'),
  })
  const telemetry = useQuery({
    queryKey: ['well-telemetry', uwi, from30],
    queryFn: () => getWellTelemetry(uwi, `${from30}T00:00:00Z`, `${to}T23:59:59Z`, TELEMETRY_TAGS),
  })
  const events = useQuery({ queryKey: ['well-events', uwi, from90], queryFn: () => getWellEvents(uwi, from90, to) })
  const tests = useQuery({ queryKey: ['well-tests', uwi], queryFn: () => getWellTests(uwi, { limit: 50 }) })
  const losses = useQuery({
    queryKey: ['well-losses', uwi, card.data?.id],
    queryFn: () => getDeferred(from90, to, 'well', 'day') as Promise<DeferredAggregateItem[]>,
    enabled: !!card.data,
  })

  const productionOption = useMemo(() => {
    const rows = production.data ?? []
    return {
      grid: { left: 44, right: 44, top: 24, bottom: 24 },
      legend: { top: 0, textStyle: { fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: rows.map((r) => r.date), axisLabel: { formatter: (v: string) => v.slice(5) } },
      yAxis: [
        { type: 'value', name: 'т/сут', position: 'left' },
        { type: 'value', name: '% воды', position: 'right', min: 0, max: 100 },
      ],
      series: [
        { name: 'Qж', type: 'line', data: rows.map((r) => r.q_liquid_t), smooth: true },
        { name: 'Qн', type: 'line', data: rows.map((r) => r.q_oil_t), smooth: true },
        {
          name: 'Обводнённость',
          type: 'line',
          yAxisIndex: 1,
          data: rows.map((r) => (r.q_liquid_t > 0 ? (r.q_water_m3 / r.q_liquid_t) * 100 : null)),
          smooth: true,
          lineStyle: { type: 'dashed' },
        },
      ],
    } as echarts.EChartsOption
  }, [production.data])

  const telemetryOption = useMemo(() => {
    const points = telemetry.data ?? []
    const tags = [...new Set(points.map((p) => p.tag))]
    return {
      grid: { left: 44, right: 16, top: 24, bottom: 24 },
      legend: { top: 0, textStyle: { fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'time' },
      yAxis: { type: 'value' },
      series: tags.map((tag) => ({
        name: TAG_LABEL[tag] ?? tag,
        type: 'line',
        showSymbol: false,
        data: points.filter((p) => p.tag === tag).map((p) => [p.ts, p.value]),
      })),
    } as echarts.EChartsOption
  }, [telemetry.data])

  const wellLosses = useMemo(
    () => (losses.data ?? []).filter((l) => l.group === card.data?.id),
    [losses.data, card.data],
  )
  const totalLoss = wellLosses.reduce((acc, l) => acc + l.volume_oil_t, 0)

  const testColumns: Column<WellTestOut>[] = [
    { key: 'ts_start', header: 'Дата', render: (t) => formatDateTime(t.ts_start) },
    { key: 'q_liquid', header: 'Qж, т', render: (t) => formatNumber(t.q_liquid), align: 'right' },
    { key: 'q_oil', header: 'Qн, т', render: (t) => formatNumber(t.q_oil), align: 'right' },
    { key: 'water_cut', header: 'Обв., %', render: (t) => (t.water_cut !== null ? formatNumber(t.water_cut) : '—'), align: 'right' },
    { key: 'gor', header: 'ГФ', render: (t) => (t.gor !== null ? formatNumber(t.gor) : '—'), align: 'right' },
    { key: 'method', header: 'Метод', render: (t) => t.method ?? '—' },
    { key: 'valid', header: 'Валидность', render: (t) => (t.is_valid ? 'ок' : 'брак') },
  ]

  if (card.isLoading) return <div style={{ padding: 12 }}>Загрузка…</div>
  if (card.error || !card.data) return <div style={{ padding: 12, color: 'var(--color-critical)' }}>Скважина не найдена</div>

  const well = card.data

  return (
    <div className="well-card">
      <div className="well-card__header">
        <div>
          <Link to="/wells" className="well-card__back">
            ← Фонд скважин
          </Link>
          <h1 className="well-card__title">
            {well.uwi} {well.name && <span className="well-card__name">— {well.name}</span>}
          </h1>
        </div>
        <WellStatusBadge status={well.status} />
      </div>

      <div className="well-card__grid">
        <Panel title="Паспорт" className="well-card__passport">
          <dl className="well-card__dl">
            <dt>Гос. номер</dt>
            <dd>{well.gos_number ?? '—'}</dd>
            <dt>Тип</dt>
            <dd>{WELL_TYPE_LABEL[well.well_type] ?? well.well_type}</dd>
            <dt>Дата бурения</dt>
            <dd>{well.spud_date ? formatDate(well.spud_date) : '—'}</dd>
            <dt>Потери за 90 сут</dt>
            <dd>{formatNumber(totalLoss)} т</dd>
          </dl>

          <div className="well-card__subtitle">Оборудование</div>
          <ul className="well-card__list">
            {well.equipment.length === 0 && <li className="well-card__list-empty">Нет данных</li>}
            {well.equipment.map((e) => (
              <li key={e.id}>
                {EQUIPMENT_LABEL[e.equipment_type] ?? e.equipment_type} {e.type_size && `(${e.type_size})`} —{' '}
                {formatDate(e.install_date)}
                {e.pull_date ? ` – ${formatDate(e.pull_date)}` : ' – по н.в.'}
              </li>
            ))}
          </ul>

          <div className="well-card__subtitle">Перфорации</div>
          <ul className="well-card__list">
            {well.completions.length === 0 && <li className="well-card__list-empty">Нет данных</li>}
            {well.completions.map((c) => (
              <li key={c.id}>
                {formatNumber(c.top_md)}–{formatNumber(c.bottom_md)} м, {c.status}, {formatDate(c.perf_date)}
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Добыча: Qж / Qн / обводнённость, 90 сут" className="well-card__chart">
          <QueryState isLoading={production.isLoading} error={production.error}>
            <Chart option={productionOption} height={230} />
          </QueryState>
        </Panel>

        <Panel title="Давления и телеметрия ЭЦН, 30 сут" className="well-card__chart">
          <QueryState isLoading={telemetry.isLoading} error={telemetry.error}>
            <Chart option={telemetryOption} height={230} />
          </QueryState>
        </Panel>

        <Panel title="Шкала событий" className="well-card__events">
          <QueryState isLoading={events.isLoading} error={events.error}>
            <ul className="well-card__timeline">
              {(events.data ?? []).length === 0 && <li className="well-card__list-empty">Событий нет</li>}
              {(events.data ?? [])
                .slice()
                .reverse()
                .map((ev, i) => (
                  <li key={i} className={`well-card__timeline-item well-card__timeline-item--${ev.kind}`}>
                    <span className="well-card__timeline-kind">{EVENT_KIND_LABEL[ev.kind]}</span>
                    <span className="well-card__timeline-date">{formatDate(ev.date)}</span>
                    <span className="well-card__timeline-title">{ev.title}</span>
                    {ev.detail && <span className="well-card__timeline-detail"> — {ev.detail}</span>}
                  </li>
                ))}
            </ul>
          </QueryState>
        </Panel>

        <Panel title="Замеры" className="well-card__tests">
          <QueryState isLoading={tests.isLoading} error={tests.error}>
            <table className="data-table">
              <thead>
                <tr>
                  {testColumns.map((c) => (
                    <th key={c.key} className={c.align === 'right' ? 'data-table__cell--right' : ''}>
                      {c.header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(tests.data?.items ?? []).map((t) => (
                  <tr key={t.id} className={t.is_valid ? undefined : 'well-card__row--invalid'}>
                    {testColumns.map((c) => (
                      <td key={c.key} className={c.align === 'right' ? 'data-table__cell--right' : ''}>
                        {c.render(t)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </QueryState>
        </Panel>
      </div>
    </div>
  )
}
