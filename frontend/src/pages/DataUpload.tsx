import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getDailyReportMappings, uploadDailyReport } from '../api/endpoints'
import { ApiError } from '../api/client'
import type { DailyReportUploadResult } from '../api/types'
import { DataTable, type Column } from '../components/DataTable'
import { MetricCard } from '../components/MetricCard'
import { Panel } from '../components/Panel'
import { formatDate, formatNumber } from '../utils/format'
import './DataUpload.css'

const STATUS_LABEL: Record<string, string> = {
  success: 'Загружено без замечаний',
  partial: 'Загружено частично',
  failed: 'Загрузка не удалась',
}

type AttentionRow = DailyReportUploadResult['attention'][number]

export function DataUpload() {
  const mappings = useQuery({ queryKey: ['daily-report-mappings'], queryFn: getDailyReportMappings })
  const [mapping, setMapping] = useState('standard_ru')
  const [file, setFile] = useState<File | null>(null)
  const [isUploading, setIsUploading] = useState(false)
  const [result, setResult] = useState<DailyReportUploadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleUpload() {
    if (!file) return
    setIsUploading(true)
    setError(null)
    setResult(null)
    try {
      const res = await uploadDailyReport(file, mapping)
      setResult(res)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить файл')
    } finally {
      setIsUploading(false)
    }
  }

  const attentionColumns: Column<AttentionRow>[] = [
    { key: 'uwi', header: 'Скважина', render: (r) => r.uwi ?? `#${r.well_id}` },
    { key: 'date', header: 'Дата', render: (r) => formatDate(r.date) },
    { key: 'status', header: 'Проблема', render: (r) => r.validation_status !== 'OK' ? r.validation_status : '—' },
    {
      key: 'reasons',
      header: 'Требует подтверждения',
      render: (r) => (r.need_confirmation_reasons.length > 0 ? r.need_confirmation_reasons.join('; ') : '—'),
    },
  ]

  return (
    <div className="data-upload">
      <Panel title="Загрузить суточный рапорт">
        <div className="data-upload__form">
          <label className="data-upload__field">
            <span>Формат файла</span>
            <select value={mapping} onChange={(e) => setMapping(e.target.value)}>
              {(mappings.data ?? ['standard_ru']).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="data-upload__field">
            <span>Файл (CSV/Excel)</span>
            <input
              type="file"
              accept=".csv,.xlsx,.xlsm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <button className="data-upload__submit" onClick={handleUpload} disabled={!file || isUploading}>
            {isUploading ? 'Загружаем…' : 'Загрузить'}
          </button>
        </div>
        {error && <div className="data-upload__error">{error}</div>}
      </Panel>

      {result && (
        <>
          <Panel title="Результат загрузки">
            <div className="data-upload__status">
              <span className={`data-upload__status-badge data-upload__status-badge--${result.status}`}>
                {STATUS_LABEL[result.status] ?? result.status}
              </span>
              <span>
                прочитано {result.records_read}, загружено {result.records_loaded}, в карантине{' '}
                {result.records_quarantined}
              </span>
            </div>
            {result.error_message && <div className="data-upload__error">{result.error_message}</div>}
          </Panel>

          {result.field_summaries.length > 0 && (
            <Panel title="Суточная сводка">
              <div className="data-upload__summaries">
                {result.field_summaries.map((s) => (
                  <div key={s.date} className="data-upload__summary-group">
                    <div className="data-upload__summary-date">{formatDate(s.date)}</div>
                    <div className="data-upload__summary-cards">
                      <MetricCard label="Добыча нефти" value={formatNumber(s.q_oil_t)} unit="т" />
                      <MetricCard label="Добыча жидкости" value={formatNumber(s.q_liquid_t)} unit="т" />
                      <MetricCard
                        label="Обводнённость"
                        value={s.weighted_water_cut_pct !== null ? formatNumber(s.weighted_water_cut_pct) : '—'}
                        unit="%"
                      />
                      <MetricCard
                        label="Скважин в работе"
                        value={String(s.wells_active)}
                        sub={`простаивает: ${s.wells_idle} из ${s.wells_total}`}
                      />
                      <MetricCard
                        label="Требует внимания"
                        value={String(s.wells_need_confirmation)}
                        sub="скважино-суток"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel title={`Требует внимания (${result.attention.length})`}>
            <DataTable columns={attentionColumns} rows={result.attention} rowKey={(r) => `${r.well_id}-${r.date}`} />
          </Panel>
        </>
      )}
    </div>
  )
}
