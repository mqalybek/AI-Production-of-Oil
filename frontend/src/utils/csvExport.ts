// CSV, а не .xlsx: Excel открывает CSV нативно, и не нужна сторонняя
// библиотека для генерации бинарного формата (у пакетов для .xlsx на
// npm — неисправленные уязвимости, см. CLAUDE.md).

export function exportToCsv(filename: string, headers: string[], rows: (string | number)[][]): void {
  const escape = (v: string | number) => {
    const s = String(v)
    return /[;"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [headers, ...rows].map((row) => row.map(escape).join(';'))
  const csv = '﻿' + lines.join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
