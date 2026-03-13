import { useState, useEffect } from 'react'
import Topbar from '../../components/Shell/Topbar'
import { listProjects, listTasks, listSessions, getSessionLogs, getTodos } from '../../api'
import type { ProjectData, TaskData, SessionStatusData, TodoData } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import './Debug.css'

const SESSION_STATUS_LABELS: Record<number, { label: string; cls: string }> = {
  0: { label: 'waiting', cls: 'tag-dim' },
  1: { label: 'running', cls: 'tag-blue' },
  2: { label: 'done', cls: 'tag-green' },
  3: { label: 'failed', cls: 'tag-red' },
}

const STAGE_LABELS: Record<string, string> = {
  init: 'Init',
  plan: 'Plan',
  todo_split: 'Todo Split',
  todo_exec: 'Todo Exec',
  review: 'Review',
}

export default function Debug() {
  const { t } = useLocale()

  // Data
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [tasks, setTasks] = useState<TaskData[]>([])
  const [todos, setTodos] = useState<TodoData[]>([])
  const [sessions, setSessions] = useState<SessionStatusData[]>([])
  const [logs, setLogs] = useState<Record<string, unknown>[]>([])

  // Selection
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [selectedScope, setSelectedScope] = useState<string>('')  // "init" or task_id
  const [selectedSession, setSelectedSession] = useState<string>('')

  // Loading
  const [loadingLogs, setLoadingLogs] = useState(false)

  // Load projects
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {})
  }, [])

  // Load tasks + clear downstream when project changes
  useEffect(() => {
    setTasks([])
    setTodos([])
    setSessions([])
    setLogs([])
    setSelectedScope('')
    setSelectedSession('')
    if (!selectedProject) return
    listTasks(selectedProject).then(setTasks).catch(() => {})
  }, [selectedProject])

  // Load sessions when scope changes
  useEffect(() => {
    setSessions([])
    setLogs([])
    setSelectedSession('')
    if (!selectedScope) return

    if (selectedScope === 'init') {
      listSessions({ ref_id: selectedProject, type: 'init' }).then(setSessions).catch(() => {})
    } else {
      // task scope — load all session types for this task
      listSessions({ ref_id: selectedScope }).then(setSessions).catch(() => {})
      // also load todos so we can label todo_exec sessions
      getTodos(selectedScope).then(setTodos).catch(() => {})
    }
  }, [selectedScope, selectedProject])

  // Load logs when session selected
  useEffect(() => {
    setLogs([])
    if (!selectedSession) return
    setLoadingLogs(true)
    getSessionLogs(selectedSession)
      .then(setLogs)
      .catch(() => {})
      .finally(() => setLoadingLogs(false))
  }, [selectedSession])

  // Helpers
  const selectedProjectObj = projects.find(p => p.id === selectedProject)
  const selectedTaskObj = tasks.find(t => t.id === selectedScope)
  const selectedSessionObj = sessions.find(s => s.session_id === selectedSession)

  function getSessionLabel(s: SessionStatusData): string {
    if (s.type === 'init') {
      // e.g. init:abc123:frontend-structure → "frontend-structure"
      const parts = s.session_id.split(':')
      return parts[parts.length - 1]
    }
    if (s.type === 'todo_exec') {
      // Try to find matching todo
      const parts = s.session_id.split(':')
      const todoId = parts[parts.length - 1]
      const todo = todos.find(t => t.id === todoId)
      if (todo) return `#${todo.seq} ${todo.title}`
      return `todo ${todoId.slice(0, 6)}`
    }
    return STAGE_LABELS[s.type] || s.type
  }

  function formatDuration(s: SessionStatusData): string {
    if (!s.started_at || !s.finished_at) return '-'
    const ms = new Date(s.finished_at).getTime() - new Date(s.started_at).getTime()
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  return (
    <>
      <Topbar title={t('debug.title')} />
      <div className="debug-page">
        {/* Breadcrumb */}
        <div className="debug-breadcrumb">
          <span className="breadcrumb-item" onClick={() => { setSelectedProject(''); setSelectedScope(''); setSelectedSession('') }}>
            {t('debug.all_projects')}
          </span>
          {selectedProjectObj && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-item" onClick={() => { setSelectedScope(''); setSelectedSession('') }}>
                {selectedProjectObj.name}
              </span>
            </>
          )}
          {selectedScope === 'init' && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-item" onClick={() => setSelectedSession('')}>Init</span>
            </>
          )}
          {selectedTaskObj && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-item" onClick={() => setSelectedSession('')}>
                {selectedTaskObj.name}
              </span>
            </>
          )}
          {selectedSessionObj && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-current">{getSessionLabel(selectedSessionObj)}</span>
            </>
          )}
        </div>

        <div className="debug-layout">
          {/* Left: Navigator */}
          <div className="debug-nav">
            {/* Project picker */}
            {!selectedProject && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.select_project')}</div>
                {projects.map(p => (
                  <button key={p.id} className="debug-item" onClick={() => setSelectedProject(p.id)}>
                    <span className="debug-item-name">{p.name}</span>
                    <span className="debug-item-meta">{p.repos?.length || 0} repos</span>
                  </button>
                ))}
                {projects.length === 0 && <div className="debug-empty">{t('debug.no_projects')}</div>}
              </div>
            )}

            {/* Scope picker: Init or Tasks */}
            {selectedProject && !selectedScope && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.select_scope')}</div>
                <button className="debug-item" onClick={() => setSelectedScope('init')}>
                  <span className="debug-item-name">{t('debug.project_init')}</span>
                  <span className="tag tag-purple">init</span>
                </button>
                {tasks.length > 0 && <div className="debug-section-sub">{t('debug.tasks')}</div>}
                {tasks.map(task => (
                  <button key={task.id} className="debug-item" onClick={() => setSelectedScope(task.id)}>
                    <span className="debug-item-name">{task.name}</span>
                    <span className={`tag ${task.status >= 7 ? 'tag-green' : task.status > 0 ? 'tag-blue' : 'tag-dim'}`}>
                      {task.branch || `#${task.id.slice(0, 6)}`}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {/* Session list */}
            {selectedScope && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.sessions')}</div>
                {sessions.map(s => {
                  const st = SESSION_STATUS_LABELS[s.status] || SESSION_STATUS_LABELS[0]
                  return (
                    <button
                      key={s.session_id}
                      className={`debug-item ${selectedSession === s.session_id ? 'active' : ''}`}
                      onClick={() => setSelectedSession(s.session_id)}
                    >
                      <span className="debug-item-name">{getSessionLabel(s)}</span>
                      <span className="debug-item-right">
                        <span className="debug-item-duration">{formatDuration(s)}</span>
                        <span className={`tag ${st.cls}`}>{st.label}</span>
                      </span>
                    </button>
                  )
                })}
                {sessions.length === 0 && <div className="debug-empty">{t('debug.no_sessions')}</div>}
              </div>
            )}
          </div>

          {/* Right: Log viewer */}
          <div className="debug-logs">
            {!selectedSession && (
              <div className="debug-placeholder">
                <div className="debug-placeholder-icon">&#128269;</div>
                <div>{t('debug.select_session_hint')}</div>
              </div>
            )}
            {selectedSession && loadingLogs && (
              <div className="debug-placeholder">{t('debug.loading')}</div>
            )}
            {selectedSession && !loadingLogs && (
              <>
                {/* Session meta */}
                {selectedSessionObj && (
                  <div className="debug-session-meta">
                    <div className="meta-row">
                      <span className="meta-label">session_id</span>
                      <code>{selectedSessionObj.session_id}</code>
                    </div>
                    {selectedSessionObj.cody_session_id && (
                      <div className="meta-row">
                        <span className="meta-label">cody_session_id</span>
                        <code>{selectedSessionObj.cody_session_id}</code>
                      </div>
                    )}
                    {selectedSessionObj.error && (
                      <div className="meta-row error">
                        <span className="meta-label">error</span>
                        <code>{selectedSessionObj.error}</code>
                      </div>
                    )}
                  </div>
                )}
                {/* Logs */}
                <div className="debug-log-list">
                  {logs.map((entry, i) => (
                    <LogEntry key={i} entry={entry} index={i} />
                  ))}
                  {logs.length === 0 && <div className="debug-empty">{t('debug.no_logs')}</div>}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function LogEntry({ entry, index }: { entry: Record<string, unknown>; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const type = (entry.type as string) || 'unknown'

  const TYPE_COLORS: Record<string, string> = {
    text_delta: 'tag-dim',
    thinking: 'tag-purple',
    tool_call: 'tag-blue',
    tool_result: 'tag-teal',
    done: 'tag-green',
    status_change: 'tag-amber',
    error: 'tag-red',
  }

  const preview = type === 'text_delta'
    ? (entry.content as string || '').slice(0, 120)
    : type === 'tool_call'
    ? (entry.name as string) || (entry.tool as string) || ''
    : type === 'error'
    ? (entry.error as string || entry.message as string || '').slice(0, 120)
    : ''

  return (
    <div className={`log-entry ${expanded ? 'expanded' : ''}`} onClick={() => setExpanded(e => !e)}>
      <div className="log-entry-header">
        <span className="log-index">#{index}</span>
        <span className={`tag ${TYPE_COLORS[type] || 'tag-dim'}`}>{type}</span>
        {preview && <span className="log-preview">{preview}</span>}
      </div>
      {expanded && (
        <pre className="log-entry-json">{JSON.stringify(entry, null, 2)}</pre>
      )}
    </div>
  )
}
