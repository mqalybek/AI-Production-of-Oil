import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getFields, getWells } from '../api/endpoints'
import type { WellListItem } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { Panel } from '../components/Panel'
import { QueryState } from '../components/QueryState'
import { WellStatusBadge } from '../components/StatusBadge'
import { exportToCsv } from '../utils/csvExport'
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
  ]

  function handleExport() {
    exportToCsv(
      `well_fund_${new Date().toISOString().slice(0, 10)}.csv`,
      ['UWI', 'Название', 'Месторождение', 'Тип', 'Статус'],
      filteredRows.map((w) => [
        w.uwi,
        w.name ?? '',
        fieldNameById.get(w.field_id) ?? String(w.field_id),
        WELL_TYPE_LABEL[w.well_type] ?? w.well_type,
        STATUS_OPTIONS.find((s) => s.value === w.status)?.label ?? w.status,
      ]),
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
