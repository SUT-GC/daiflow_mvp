import { useNavigate } from 'react-router-dom'
import { useTheme } from '../../hooks/useTheme'

interface TopbarProps {
  title: string
  subtitle?: string
  branch?: string
  backTo?: string
  backLabel?: string
  actions?: React.ReactNode
}

export default function Topbar({ title, subtitle, branch, backTo, backLabel, actions }: TopbarProps) {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()

  return (
    <div className="topbar">
      {backTo && (
        <button className="topbar-back" onClick={() => navigate(backTo)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', font: 'inherit' }}>
          &larr; {backLabel || 'Back'}
        </button>
      )}
      <span className="topbar-title">{title}</span>
      {subtitle && (
        <>
          <span className="topbar-sep">/</span>
          <span className="topbar-sub">{subtitle}</span>
        </>
      )}
      {branch && <span className="topbar-branch">{branch}</span>}
      <div className="topbar-right">
        <button className="theme-btn" onClick={toggleTheme}>
          {theme === 'dark' ? '\u2600' : '\u263D'}
        </button>
        {actions}
      </div>
    </div>
  )
}
