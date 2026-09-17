import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getFields, getMonthlySummaries, getWells } from '../api/endpoints'
import type { WellListItem, WellMonthlySummaryOut } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { WellStatusBadge } from '../components/StatusBadge'
import { exportToCsv } from '../utils/csvExport'
import { formatNumber } from '../utils/format'
import { WELL_TYPE_LABEL } from '../utils/labels'
import './WellFund.css'

const STATUS_OPTIONS = [
  { value: '', label: 'Все статусы' },
  { value: 'active', label: 'В работе' },
  { value: 'idle', label: 'Простой' },
  { value: 'mothballed', label: 'Законсервирована' },
  { value: 'abandoned', label: 'Ликвидирована' },
  { value: 'drilling', label: 'Бурение' },
]

export function WellFund() {
  const navigate = useNavigate()
  const [fieldId, setFieldId] = useState<number | undefined>(undefined)
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')

  const fields = useQuery({ queryKey: ['fields'], queryFn: getFields })
  const wells = useQuery({
    queryKey: ['wells', fieldId, status],
    queryFn: () => getWells({ field: fieldId, status: status || undefined, limit: 500 }),
  })
  const monthlySummaries = useQuery({
    queryKey: ['monthly-summaries', fieldId],
    queryFn: () => getMonthlySummaries({ field: fieldId, limit: 500 }),
  })

  const filteredRows = useMemo(() => {
    const items = wells.data?.items ?? []
    if (!search.trim()) return items
    const q = search.trim().toLowerCase()
    return items.filter((w) => w.uwi.toLowerCase().includes(q) || (w.name ?? '').toLowerCase().includes(q))
  }, [wells.data, search])

  const fieldNameById = useMemo(() => {
    const map = new Map<number, string>()
    for (const f of fields.data ?? []) map.set(f.id, f.name)
    return map
  }, [fields.data])

  const summaryByWellId = useMemo(() => {
    const map = new Map<number, WellMonthlySummaryOut>()
    for (const s of monthlySummaries.data?.items ?? []) map.set(s.well_id, s)
    return map
  }, [monthlySummaries.data])

  const columns: Column<WellListItem>[] = [
    { key: 'uwi', header: 'UWI', render: (w) => w.uwi, sortValue: (w) => w.uwi },
    { key: 'name', header: 'Название', render: (w) => w.name ?? '—', sortValue: (w) => w.name ?? '' },
    {
      key: 'field',
      header: 'Месторождение',
      render: (w) => fieldNameById.get(w.field_id) ?? w.field_id,
      sortValue: (w) => fieldNameById.get(w.field_id) ?? '',
    },
    { key: 'type', header: 'Тип', render: (w) => WELL_TYPE_LABEL[w.well_type] ?? w.well_type, sortValue: (w) => w.well_type },
    {
      key: 'status',
      header: 'Статус',
      render: (w) => <WellStatusBadge status={w.status} />,
      sortValue: (w) => w.status,
    },
    {
      key: 'last_month',
      header: 'Посл. месяц',
      render: (w) => summaryByWellId.get(w.id)?.last_period.slice(0, 7) ?? '—',
      sortValue: (w) => summaryByWellId.get(w.id)?.last_period ?? '',
    },
    {
      key: 'oil_rate',
      header: 'Дебит нефти, т/сут',
      render: (w) => {
        const rate = summaryByWellId.get(w.id)?.q_oil_rate_t_d
        return rate != null ? formatNumber(rate) : '—'
      },
      sortValue: (w) => summaryByWellId.get(w.id)?.q_oil_rate_t_d ?? -1,
      align: 'right',
    },
    {
      key: 'water_cut',
      header: 'Обв., %',
      render: (w) => {
        const wc = summaryByWellId.get(w.id)?.water_cut_pct
        return wc != null ? formatNumber(wc) : '—'
      },
      sortValue: (w) => summaryByWellId.get(w.id)?.water_cut_pct ?? -1,
      align: 'right',
    },
    {
      key: 'trend',
      header: 'Тренд',
      render: (w) => {
        const delta = summaryByWellId.get(w.id)?.delta_oil_pct
        if (delta == null) return '—'
        const arrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '—'
        const tone = delta > 0 ? 'var(--color-success)' : delta < 0 ? 'var(--color-critical)' : 'var(--color-text-muted)'
        return (
          <span style={{ color: tone }}>
            {arrow} {formatNumber(Math.abs(delta), 0)}%
          </span>
        )
      },
      sortValue: (w) => summaryByWellId.get(w.id)?.delta_oil_pct ?? 0,
      align: 'right',
    },
  ]

  function handleExport() {
    exportToCsv(
      `well_fund_${new Date().toISOString().slice(0, 10)}.csv`,
      ['UWI', 'Название', 'Месторождение', 'Тип', 'Статус', 'Посл. месяц', 'Дебит нефти, т/сут', 'Обв., %'],
      filteredRows.map((w) => {
        const s = summaryByWellId.get(w.id)
        return [
          w.uwi,
          w.name ?? '',
          fieldNameById.get(w.field_id) ?? String(w.field_id),
          WELL_TYPE_LABEL[w.well_type] ?? w.well_type,
          STATUS_OPTIONS.find((opt) => opt.value === w.status)?.label ?? w.status,
          s?.last_period.slice(0, 7) ?? '',
          s?.q_oil_rate_t_d != null ? formatNumber(s.q_oil_rate_t_d) : '',
          s?.water_cut_pct != null ? formatNumber(s.water_cut_pct) : '',
        ]
      }),
    )
  }

  return (
    <Panel
      title={`Фонд скважин (${filteredRows.length})`}
      className="well-fund"
      action={
        <button className="well-fund__export" onClick={handleExport}>
          Экспорт в Excel
        </button>
      }
    >
      <div className="well-fund__filters">
        <input
          className="well-fund__search"
          placeholder="Поиск по UWI или названию…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={fieldId ?? ''} onChange={(e) => setFieldId(e.target.value ? Number(e.target.value) : undefined)}>
          <option value="">Все месторождения</option>
          {(fields.data ?? []).map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      <QueryState isLoading={wells.isLoading} error={wells.error}>
        <DataTable
          columns={columns}
          rows={filteredRows}
          rowKey={(w) => w.id}
          onRowClick={(w) => navigate(`/wells/${w.uwi}`)}
        />
      </QueryState>
    </Panel>
  )
}
