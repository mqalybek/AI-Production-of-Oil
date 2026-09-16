import type { ReactNode } from 'react'

interface QueryStateProps {
  isLoading: boolean
  error: unknown
  children: ReactNode
}

export function QueryState({ isLoading, error, children }: QueryStateProps) {
  if (isLoading) return <div style={{ color: 'var(--color-text-faint)', padding: 12 }}>Загрузка…</div>
  if (error) {
    const message = error instanceof Error ? error.message : 'Не удалось загрузить данные'
    return <div style={{ color: 'var(--color-critical)', padding: 12 }}>{message}</div>
  }
  return <>{children}</>
}
