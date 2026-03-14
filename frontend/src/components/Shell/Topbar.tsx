import { useNavigate } from 'react-router-dom'
import { useTheme } from '../../hooks/useTheme'
import { useLocale } from '../../hooks/useLocale'
import { TaskStatus } from '../../types/enums'
import type { TranslationKey } from '../../i18n'

const STATUS_CONFIG: Record<number, { labelKey: TranslationKey; cls: string }> = {
  [TaskStatus.CREATED]:      { labelKey: 'tasks.status.0', cls: 'status-grey' },
  [TaskStatus.INITIALIZING]: { labelKey: 'tasks.status.1', cls: 'status-amber' },
  [TaskStatus.PLANNING]:     { labelKey: 'tasks.status.2', cls: 'status-amber' },
  [TaskStatus.PLAN_LOCKED]:  { labelKey: 'tasks.status.3', cls: 'status-teal' },
  [TaskStatus.TODO_READY]:   { labelKey: 'tasks.status.4', cls: 'status-blue' },
  [TaskStatus.CODING]:       { labelKey: 'tasks.status.5', cls: 'status-amber' },
  [TaskStatus.REVIEWING]:    { labelKey: 'tasks.status.6', cls: 'status-amber' },
  [TaskStatus.DONE]:         { labelKey: 'tasks.status.7', cls: 'status-teal' },
}

interface TopbarProps {
  title: string
  subtitle?: string
  branch?: string
  taskStatus?: number
  backTo?: string
  backLabel?: string
  actions?: React.ReactNode
}

export default function Topbar({ title, subtitle, branch, taskStatus, backTo, backLabel, actions }: TopbarProps) {
  const navigate = useNavigate()
  const { theme, toggleTheme } = useTheme()
  const { t } = useLocale()

  const statusInfo = taskStatus != null ? STATUS_CONFIG[taskStatus] : null

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
      {statusInfo && <span className={`topbar-status ${statusInfo.cls}`}>{t(statusInfo.labelKey)}</span>}
      <div className="topbar-right">
        <button className="theme-btn" onClick={toggleTheme}>
          {theme === 'dark' ? '\u2600' : '\u263D'}
        </button>
        {actions}
      </div>
    </div>
  )
}
