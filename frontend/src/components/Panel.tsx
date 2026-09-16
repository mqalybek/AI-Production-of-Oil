import type { ReactNode } from 'react'
import './Panel.css'

interface PanelProps {
  title: string
  action?: ReactNode
  children: ReactNode
  className?: string
}

export function Panel({ title, action, children, className }: PanelProps) {
  return (
    <section className={'panel' + (className ? ` ${className}` : '')}>
      <header className="panel__header">
        <h2 className="panel__title">{title}</h2>
        {action}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  )
}
