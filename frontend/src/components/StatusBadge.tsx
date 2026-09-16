import type { ReactNode } from 'react'
import './StatusBadge.css'

const WELL_STATUS_LABEL: Record<string, string> = {
  active: 'В работе',
  idle: 'Простой',
  mothballed: 'Законсервирована',
  abandoned: 'Ликвидирована',
  drilling: 'Бурение',
}

const WELL_STATUS_TONE: Record<string, 'good' | 'warning' | 'critical' | 'neutral'> = {
  active: 'good',
  idle: 'warning',
  mothballed: 'neutral',
  abandoned: 'critical',
  drilling: 'neutral',
}

const SEVERITY_LABEL: Record<string, string> = {
  info: 'Инфо',
  warning: 'Внимание',
  critical: 'Критично',
}

const SEVERITY_TONE: Record<string, 'good' | 'warning' | 'critical' | 'neutral'> = {
  info: 'neutral',
  warning: 'warning',
  critical: 'critical',
}

function Badge({ tone, children }: { tone: 'good' | 'warning' | 'critical' | 'neutral'; children: ReactNode }) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>
}

export function WellStatusBadge({ status }: { status: string }) {
  return <Badge tone={WELL_STATUS_TONE[status] ?? 'neutral'}>{WELL_STATUS_LABEL[status] ?? status}</Badge>
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={SEVERITY_TONE[severity] ?? 'neutral'}>{SEVERITY_LABEL[severity] ?? severity}</Badge>
}
