import { NavLink } from 'react-router-dom'
import { useSettingsContext } from '../../App'
import { useLocale } from '../../hooks/useLocale'

interface ShellProps {
  children: React.ReactNode
}

export default function Shell({ children }: ShellProps) {
  const { configured, model } = useSettingsContext()
  const { t } = useLocale()

  return (
    <div className="shell">
      <nav className="sidebar">
        <NavLink to="/" className="logo">
          <div className="logo-mark">D</div>
          <div className="logo-text">dai<span>flow</span></div>
        </NavLink>

        <div className="nav-group">
          <div className="nav-label">{t('nav.workspace')}</div>
          <NavLink
            to="/projects"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <span className="nav-icon">&#9783;</span>
            {t('nav.projects')}
          </NavLink>
          <NavLink
            to="/tasks"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <span className="nav-icon">&#9776;</span>
            {t('nav.tasks')}
          </NavLink>
        </div>

        <div className="sidebar-bottom">
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <span className="nav-icon">&#9881;</span>
            {t('nav.settings')}
          </NavLink>
          <div className="sidebar-divider" />
          <div className="model-pill">
            <div className={`model-dot ${configured ? '' : 'disconnected'}`} />
            <div className="model-text">{model || t('nav.not_configured')}</div>
          </div>
        </div>
      </nav>

      <div className="main">
        {children}
      </div>
    </div>
  )
}
