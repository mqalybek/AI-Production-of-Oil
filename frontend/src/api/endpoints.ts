import { api } from './client'
import type {
  AlertOut,
  DailyFieldSummary,
  DataQualityMetrics,
  DeferredAggregateItem,
  DeferredParetoItem,
  FieldOut,
  MonthlyProductionOut,
  Page,
  ProductionSummaryPoint,
  WellCardData,
  WellEvent,
  DailyProductionOut,
  WellListItem,
  WellMonthlySummaryOut,
  WellTestOut,
  TelemetryPoint,
} from './types'

export function login(username: string, password: string) {
  return api.post<{ access_token: string; token_type: string }>('/api/auth/login', { username, password })
}

export function getFields() {
  return api.get<FieldOut[]>('/api/fields')
}

export function getWells(params: { field?: number; status?: string; reservoir_id?: number; limit?: number; offset?: number }) {
  return api.get<Page<WellListItem>>('/api/wells', params)
}

export function getWellCard(uwi: string) {
  return api.get<WellCardData>(`/api/wells/${uwi}`)
}

export function getWellProduction(uwi: string, from: string, to: string, granularity = 'day') {
  return api.get<DailyProductionOut[]>(`/api/wells/${uwi}/production`, { from, to, granularity })
}

export function getWellTests(uwi: string, params: { from?: string; to?: string; limit?: number; offset?: number } = {}) {
  return api.get<Page<WellTestOut>>(`/api/wells/${uwi}/tests`, params)
}

export function getWellTelemetry(uwi: string, from: string, to: string, tags?: string) {
  return api.get<TelemetryPoint[]>(`/api/wells/${uwi}/telemetry`, { from, to, tags })
}

export function getWellEvents(uwi: string, from?: string, to?: string) {
  return api.get<WellEvent[]>(`/api/wells/${uwi}/events`, { from, to })
}

export function getWellMonthlyProduction(uwi: string, from?: string, to?: string) {
  return api.get<MonthlyProductionOut[]>(`/api/wells/${uwi}/monthly-production`, { from, to })
}

export function getWellMonthlySummary(uwi: string) {
  return api.get<WellMonthlySummaryOut | null>(`/api/wells/${uwi}/monthly-summary`)
}

export function getMonthlySummaries(params: { field?: number; limit?: number; offset?: number } = {}) {
  return api.get<Page<WellMonthlySummaryOut>>('/api/monthly-production/wells', params)
}

export function getDailySummary(date: string, field?: number) {
  return api.get<DailyFieldSummary[]>('/api/production/daily', { date, field })
}

export function getProductionSummary(period: string, granularity = 'day', field?: number) {
  return api.get<ProductionSummaryPoint[]>('/api/production/summary', { period, granularity, field })
}

export function getDeferred(from: string, to: string, groupby: string, granularity = 'day') {
  return api.get<(DeferredAggregateItem | DeferredParetoItem)[]>('/api/deferred', { from, to, groupby, granularity })
}

export function getAlerts(params: { status?: string; severity?: string; limit?: number; offset?: number } = {}) {
  return api.get<Page<AlertOut>>('/api/alerts', params)
}

export function acknowledgeAlert(id: number, comment?: string) {
  return api.post<AlertOut>(`/api/alerts/${id}/acknowledge`, { comment })
}

export function getDataQuality(from: string, to: string) {
  return api.get<DataQualityMetrics>('/api/data-quality', { from, to })
}
