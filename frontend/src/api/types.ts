// Типы соответствуют pydantic-схемам src/api/schemas/*.py на бэкенде 1:1.

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface FieldOut {
  id: number
  name: string
  field_type: string
}

export interface WellListItem {
  id: number
  uwi: string
  name: string | null
  field_id: number
  well_type: string
  status: string
}

export interface EquipmentOut {
  id: number
  equipment_type: string
  type_size: string | null
  run_depth: number | null
  install_date: string
  pull_date: string | null
}

export interface CompletionOut {
  id: number
  reservoir_id: number
  top_md: number
  bottom_md: number
  perf_date: string
  status: string
}

export interface WellCardData {
  id: number
  uwi: string
  gos_number: string | null
  name: string | null
  field_id: number
  well_type: string
  status: string
  spud_date: string | null
  equipment: EquipmentOut[]
  completions: CompletionOut[]
}

export interface DailyProductionOut {
  date: string
  q_oil_t: number
  q_liquid_t: number
  q_water_m3: number
  q_gas_m3: number | null
  hours_on: number
  ke: number
  allocation_method: string | null
  confidence: string | null
}

export interface WellTestOut {
  id: number
  ts_start: string
  ts_end: string
  duration_h: number
  q_liquid: number
  q_oil: number
  q_water: number
  q_gas: number | null
  water_cut: number | null
  gor: number | null
  method: string | null
  is_valid: boolean
  validation_flags: Record<string, unknown> | null
}

export interface TelemetryPoint {
  ts: string
  tag: string
  value: number
  quality: string
}

export interface WellEvent {
  kind: 'gtm' | 'equipment' | 'downtime'
  date: string
  title: string
  detail: string | null
}

export interface DailyFieldSummary {
  field_id: number
  field_name: string
  date: string
  q_oil_t: number
  q_liquid_t: number
  q_water_m3: number
  wells_active: number
  wells_stopped: number
}

export interface ProductionSummaryPoint {
  period: string
  q_oil_t: number
  plan_oil_t: number | null
}

export interface DeferredAggregateItem {
  group: number | null
  period: string
  category: string
  volume_oil_t: number
}

export interface DeferredParetoItem {
  category: string
  reason_id: number | null
  reason_name: string | null
  volume_oil_t: number
  share_pct: number
  cumulative_pct: number
}

export type AlertSeverity = 'info' | 'warning' | 'critical'

export interface AlertOut {
  id: number
  well_id: number | null
  node_id: number | null
  type: string
  severity: AlertSeverity
  ts_detected: string
  ts_resolved: string | null
  value: number | null
  threshold: number | null
  message: string
  is_acknowledged: boolean
  acknowledged_by: string | null
  acknowledged_at: string | null
  comment: string | null
  snoozed_until: string | null
}

export interface DataQualityMetrics {
  period_start: string
  period_end: string
  quarantined_records: number
  invalid_tests: number
  valid_tests: number
  wells_without_recent_test: number
  low_confidence_allocation_days: number
}
