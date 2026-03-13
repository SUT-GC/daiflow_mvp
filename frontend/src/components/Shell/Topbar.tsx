import { useNavigate } from 'react-router-dom'
import { useTheme } from '../../hooks/useTheme'
import { TaskStatus } from '../../types/enums'

const STATUS_CONFIG: Record<number, { label: string; cls: string }> = {
  [TaskStatus.CREATED]:      { label: '未开始', cls: 'status-grey' },
  [TaskStatus.INITIALIZING]: { label: '初始化', cls: 'status-amber' },
  [TaskStatus.PLANNING]:     { label: '方案中', cls: 'status-amber' },
  [TaskStatus.PLAN_LOCKED]:  { label: '方案锁定', cls: 'status-teal' },
  [TaskStatus.TODO_READY]:   { label: '待编码', cls: 'status-blue' },
  [TaskStatus.CODING]:       { label: '编码中', cls: 'status-amber' },
  [TaskStatus.REVIEWING]:    { label: '审查中', cls: 'status-amber' },
  [TaskStatus.DONE]:         { label: '已完成', cls: 'status-teal' },
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
      {statusInfo && <span className={`topbar-status ${statusInfo.cls}`}>{statusInfo.label}</span>}
      <div className="topbar-right">
        <button className="theme-btn" onClick={toggleTheme}>
          {theme === 'dark' ? '\u2600' : '\u263D'}
        </button>
        {actions}
      </div>
    </div>
  )
}
