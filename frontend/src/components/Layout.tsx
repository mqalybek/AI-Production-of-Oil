import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import './Layout.css'

const NAV_ITEMS = [
  { to: '/', label: 'Утренняя сводка', end: true },
  { to: '/wells', label: 'Фонд скважин' },
  { to: '/losses', label: 'Анализ потерь' },
  { to: '/data-quality', label: 'Качество данных' },
]

export function Layout() {
  const { logout } = useAuth()

  return (
    <div className="layout">
      <aside className="layout__sidebar">
        <div className="layout__brand">Мониторинг добычи</div>
        <nav className="layout__nav">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => 'layout__nav-link' + (isActive ? ' layout__nav-link--active' : '')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button className="layout__logout" onClick={logout}>
          Выйти
        </button>
      </aside>
      <main className="layout__content">
        <Outlet />
      </main>
    </div>
  )
}
