import { useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import { useSettingsContext } from '../../App'
import { useLocale } from '../../hooks/useLocale'

interface ShellProps {
  children: React.ReactNode
}

const SIDEBAR_KEY = 'daiflow-sidebar-collapsed'

export default function Shell({ children }: ShellProps) {
  const { configured, model } = useSettingsContext()
  const { t } = useLocale()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(SIDEBAR_KEY) === 'true')

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, String(collapsed))
  }, [collapsed])

  return (
    <div className="shell">
      <nav className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
        <NavLink to="/" className="logo">
          <div className="logo-mark">D</div>
          <div className="logo-text">dai<span>flow</span></div>
        </NavLink>

        <div className="nav-group">
          <div className="nav-label">{t('nav.workspace')}</div>
          <NavLink
            to="/projects"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            title={collapsed ? t('nav.projects') : undefined}
          >
            <span className="nav-icon">&#9783;</span>
            <span className="nav-text">{t('nav.projects')}</span>
          </NavLink>
          <NavLink
            to="/tasks"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            title={collapsed ? t('nav.tasks') : undefined}
          >
            <span className="nav-icon">&#9776;</span>
            <span className="nav-text">{t('nav.tasks')}</span>
          </NavLink>
          <NavLink
            to="/debug"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            title={collapsed ? t('nav.debug') : undefined}
          >
            <span className="nav-icon">&#9888;</span>
            <span className="nav-text">{t('nav.debug')}</span>
          </NavLink>
        </div>

        <div className="sidebar-bottom">
          <NavLink
            to="/settings"
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            title={collapsed ? t('nav.settings') : undefined}
          >
            <span className="nav-icon">&#9881;</span>
            <span className="nav-text">{t('nav.settings')}</span>
          </NavLink>
          <div className="sidebar-divider" />
          <button className="sidebar-toggle" onClick={() => setCollapsed(c => !c)}>
            {collapsed ? '\u00BB' : '\u00AB'}
          </button>
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
