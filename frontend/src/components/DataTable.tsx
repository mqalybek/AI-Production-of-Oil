import { useMemo, useState, type ReactNode } from 'react'
import './DataTable.css'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
  sortValue?: (row: T) => string | number
  align?: 'left' | 'right'
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  onRowClick?: (row: T) => void
  emptyLabel?: string
}

export function DataTable<T>({ columns, rows, rowKey, onRowClick, emptyLabel = 'Нет данных' }: DataTableProps<T>) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null)

  const sortedRows = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sortValue) return rows
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a)
      const bv = col.sortValue!(b)
      if (av < bv) return -1 * sort.dir
      if (av > bv) return 1 * sort.dir
      return 0
    })
  }, [rows, sort, columns])

  function toggleSort(col: Column<T>) {
    if (!col.sortValue) return
    setSort((prev) => {
      if (prev?.key !== col.key) return { key: col.key, dir: 1 }
      if (prev.dir === 1) return { key: col.key, dir: -1 }
      return null
    })
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          {columns.map((col) => (
            <th
              key={col.key}
              className={col.align === 'right' ? 'data-table__cell--right' : ''}
              onClick={() => toggleSort(col)}
              style={{ cursor: col.sortValue ? 'pointer' : undefined }}
            >
              {col.header}
              {sort?.key === col.key && (sort.dir === 1 ? ' ▲' : ' ▼')}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortedRows.length === 0 && (
          <tr>
            <td colSpan={columns.length} className="data-table__empty">
              {emptyLabel}
            </td>
          </tr>
        )}
        {sortedRows.map((row) => (
          <tr key={rowKey(row)} onClick={() => onRowClick?.(row)} className={onRowClick ? 'data-table__row--clickable' : ''}>
            {columns.map((col) => (
              <td key={col.key} className={col.align === 'right' ? 'data-table__cell--right' : ''}>
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
