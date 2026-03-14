import { useState, useEffect, useMemo } from 'react'
import Topbar from '../../components/Shell/Topbar'
import { listProjects, listTasks, listSessions, getSessionLogs, getTodos, listJobs, getJobRuns } from '../../api'
import type { ProjectData, TaskData, SessionStatusData, TodoData, JobData, JobRunData } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import './Debug.css'

const SESSION_STATUS_LABELS: Record<number, { label: string; cls: string }> = {
  0: { label: 'waiting', cls: 'tag-dim' },
  1: { label: 'running', cls: 'tag-blue' },
  2: { label: 'done', cls: 'tag-green' },
  3: { label: 'failed', cls: 'tag-red' },
}

const JOB_RUN_STATUS_COLORS: Record<string, string> = {
  success: 'tag-green',
  failed: 'tag-red',
  running: 'tag-blue',
}

const STAGE_LABELS: Record<string, string> = {
  init: 'Init',
  plan: 'Plan',
  todo_split: 'Todo Split',
  todo_exec: 'Todo Exec',
  review: 'Review',
}

const STAGE_TAG_CLS: Record<string, string> = {
  init: 'tag-purple',
  plan: 'tag-blue',
  todo_split: 'tag-teal',
  todo_exec: 'tag-amber',
  review: 'tag-green',
}

const LOG_TYPE_FILTERS = ['all', 'text_delta', 'thinking', 'tool_call', 'tool_result', 'error', 'done', 'status_change']

export default function Debug() {
  const { t } = useLocale()

  // Data
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [tasks, setTasks] = useState<TaskData[]>([])
  const [todos, setTodos] = useState<TodoData[]>([])
  const [sessions, setSessions] = useState<SessionStatusData[]>([])
  const [logs, setLogs] = useState<Record<string, unknown>[]>([])
  const [jobs, setJobs] = useState<JobData[]>([])
  const [jobRuns, setJobRuns] = useState<JobRunData[]>([])

  // All-sessions overview
  const [allSessions, setAllSessions] = useState<SessionStatusData[]>([])
  const [showAllSessions, setShowAllSessions] = useState(false)
  const [allSessionsTypeFilter, setAllSessionsTypeFilter] = useState<string>('all')
  const [allSessionsStatusFilter, setAllSessionsStatusFilter] = useState<string>('all')

  // Selection
  const [selectedProject, setSelectedProject] = useState<string>('')
  const [selectedScope, setSelectedScope] = useState<string>('')  // "init", "jobs", or task_id
  const [selectedSession, setSelectedSession] = useState<string>('')

  // Filters
  const [logTypeFilter, setLogTypeFilter] = useState<string>('all')
  const [logSearch, setLogSearch] = useState<string>('')

  // Loading
  const [loadingLogs, setLoadingLogs] = useState(false)

  // Load projects
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {})
  }, [])

  // Load all sessions when overview is shown
  useEffect(() => {
    if (!showAllSessions) return
    listSessions().then(setAllSessions).catch(() => {})
  }, [showAllSessions])

  // Load tasks + jobs + clear downstream when project changes
  useEffect(() => {
    setTasks([])
    setTodos([])
    setSessions([])
    setLogs([])
    setJobs([])
    setJobRuns([])
    setSelectedScope('')
    setSelectedSession('')
    setLogTypeFilter('all')
    setLogSearch('')
    if (!selectedProject) return
    listTasks(selectedProject).then(setTasks).catch(() => {})
    listJobs(selectedProject).then(setJobs).catch(() => {})
  }, [selectedProject])

  // Load sessions/job runs when scope changes
  useEffect(() => {
    setSessions([])
    setLogs([])
    setJobRuns([])
    setSelectedSession('')
    setLogTypeFilter('all')
    setLogSearch('')
    if (!selectedScope) return

    if (selectedScope === 'init') {
      listSessions({ ref_id: selectedProject, type: 'init' }).then(setSessions).catch(() => {})
    } else if (selectedScope === 'jobs') {
      const projectJobs = jobs.filter(j => j.project_id === selectedProject)
      if (projectJobs.length > 0) {
        Promise.all(projectJobs.map(j => getJobRuns(j.id, 30))).then(results => {
          setJobRuns(results.flat().sort((a, b) =>
            (b.started_at || '').localeCompare(a.started_at || '')
          ))
        }).catch(() => {})
      }
    } else {
      // task scope
      listSessions({ ref_id: selectedScope }).then(setSessions).catch(() => {})
      getTodos(selectedScope).then(setTodos).catch(() => {})
    }
  }, [selectedScope, selectedProject, jobs])

  // Load logs when session selected
  useEffect(() => {
    setLogs([])
    setLogTypeFilter('all')
    setLogSearch('')
    if (!selectedSession) return
    setLoadingLogs(true)
    getSessionLogs(selectedSession)
      .then(setLogs)
      .catch(() => {})
      .finally(() => setLoadingLogs(false))
  }, [selectedSession])

  // Filtered logs
  const filteredLogs = useMemo(() => {
    let result = logs
    if (logTypeFilter !== 'all') {
      result = result.filter(e => (e.type as string) === logTypeFilter)
    }
    if (logSearch.trim()) {
      const q = logSearch.toLowerCase()
      result = result.filter(e => JSON.stringify(e).toLowerCase().includes(q))
    }
    return result
  }, [logs, logTypeFilter, logSearch])

  // Filtered all-sessions
  const filteredAllSessions = useMemo(() => {
    let result = allSessions
    if (allSessionsTypeFilter !== 'all') {
      result = result.filter(s => s.type === allSessionsTypeFilter)
    }
    if (allSessionsStatusFilter !== 'all') {
      result = result.filter(s => s.status === Number(allSessionsStatusFilter))
    }
    return result
  }, [allSessions, allSessionsTypeFilter, allSessionsStatusFilter])

  const allSessionTypes = useMemo(() => {
    const types = new Set(allSessions.map(s => s.type))
    return ['all', ...Array.from(types).sort()]
  }, [allSessions])

  function enterAllSessions() {
    setShowAllSessions(true)
    setSelectedProject('')
    setSelectedScope('')
    setSelectedSession('')
    setSessions([])
    setLogs([])
    setLogTypeFilter('all')
    setLogSearch('')
  }

  function exitAllSessions() {
    setShowAllSessions(false)
    setAllSessions([])
    setAllSessionsTypeFilter('all')
    setAllSessionsStatusFilter('all')
    setSelectedSession('')
    setLogs([])
  }

  // Helpers
  const selectedProjectObj = projects.find(p => p.id === selectedProject)
  const selectedTaskObj = tasks.find(t => t.id === selectedScope)
  const selectedSessionObj = sessions.find(s => s.session_id === selectedSession)
    || allSessions.find(s => s.session_id === selectedSession)

  function getSessionLabel(s: SessionStatusData): string {
    if (s.type === 'init') {
      const parts = s.session_id.split(':')
      return parts[parts.length - 1]
    }
    if (s.type === 'todo_exec') {
      const parts = s.session_id.split(':')
      const todoId = parts[parts.length - 1]
      const todo = todos.find(t => t.id === todoId)
      if (todo) return `#${todo.seq} ${todo.title}`
      return `todo ${todoId.slice(0, 6)}`
    }
    return STAGE_LABELS[s.type] || s.type
  }

  function formatDuration(start: string | null, end: string | null): string {
    if (!start || !end) return '-'
    const ms = new Date(end).getTime() - new Date(start).getTime()
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}s`
  }

  function formatTime(ts: string | null): string {
    if (!ts) return '-'
    try {
      return new Date(ts).toLocaleTimeString(undefined, { hour12: false })
    } catch {
      return '-'
    }
  }

  return (
    <>
      <Topbar title={t('debug.title')} />
      <div className="debug-page">
        {/* Breadcrumb */}
        <div className="debug-breadcrumb">
          <span className="breadcrumb-item" onClick={() => { exitAllSessions(); setSelectedProject(''); setSelectedScope(''); setSelectedSession('') }}>
            {t('debug.all_projects')}
          </span>
          {showAllSessions && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className={selectedSession ? 'breadcrumb-item' : 'breadcrumb-current'} onClick={() => setSelectedSession('')}>
                {t('debug.all_sessions')}
              </span>
            </>
          )}
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
          {selectedScope === 'jobs' && (
            <>
              <span className="breadcrumb-sep">/</span>
              <span className="breadcrumb-current">{t('debug.jobs')}</span>
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
            {/* All Sessions overview mode */}
            {showAllSessions && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.all_sessions')}</div>
                <div className="debug-all-sessions-filters">
                  <select
                    className="debug-select"
                    value={allSessionsTypeFilter}
                    onChange={e => setAllSessionsTypeFilter(e.target.value)}
                  >
                    {allSessionTypes.map(tp => (
                      <option key={tp} value={tp}>{tp === 'all' ? t('debug.all_types') : STAGE_LABELS[tp] || tp}</option>
                    ))}
                  </select>
                  <select
                    className="debug-select"
                    value={allSessionsStatusFilter}
                    onChange={e => setAllSessionsStatusFilter(e.target.value)}
                  >
                    <option value="all">{t('debug.all_status')}</option>
                    {Object.entries(SESSION_STATUS_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>{v.label}</option>
                    ))}
                  </select>
                  <span className="debug-item-meta">{filteredAllSessions.length}/{allSessions.length}</span>
                </div>
                {filteredAllSessions.map(s => {
                  const st = SESSION_STATUS_LABELS[s.status] || SESSION_STATUS_LABELS[0]
                  const typeLabel = STAGE_LABELS[s.type] || s.type
                  // Show a short label: extract the meaningful suffix from session_id
                  const shortLabel = s.session_id.split(':').slice(-1)[0]
                  return (
                    <button
                      key={s.session_id}
                      className={`debug-item ${selectedSession === s.session_id ? 'active' : ''}`}
                      onClick={() => setSelectedSession(s.session_id)}
                      title={s.session_id}
                    >
                      <span className="debug-item-name">
                        <span className={`tag tag-sm ${STAGE_TAG_CLS[s.type] || 'tag-dim'}`}>{typeLabel}</span>
                        {' '}{shortLabel}
                      </span>
                      <span className="debug-item-right">
                        <span className="debug-item-duration">{formatDuration(s.started_at, s.finished_at)}</span>
                        <span className={`tag ${st.cls}`}>{st.label}</span>
                      </span>
                    </button>
                  )
                })}
                {allSessions.length === 0 && <div className="debug-empty">{t('debug.no_sessions')}</div>}
                {allSessions.length > 0 && filteredAllSessions.length === 0 && (
                  <div className="debug-empty">{t('debug.no_matching_sessions')}</div>
                )}
              </div>
            )}

            {/* Project picker */}
            {!selectedProject && !showAllSessions && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.select_project')}</div>
                <button className="debug-item debug-all-sessions-btn" onClick={enterAllSessions}>
                  <span className="debug-item-name">{t('debug.all_sessions')}</span>
                  <span className="tag tag-purple">{t('debug.overview')}</span>
                </button>
                <div className="debug-section-sub">{t('debug.by_project')}</div>
                {projects.map(p => (
                  <button key={p.id} className="debug-item" onClick={() => setSelectedProject(p.id)}>
                    <span className="debug-item-name">{p.name}</span>
                    <span className="debug-item-meta">{p.repos?.length || 0} repos</span>
                  </button>
                ))}
                {projects.length === 0 && <div className="debug-empty">{t('debug.no_projects')}</div>}
              </div>
            )}

            {/* Scope picker: Init, Jobs, or Tasks */}
            {selectedProject && !selectedScope && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.select_scope')}</div>
                <button className="debug-item" onClick={() => setSelectedScope('init')}>
                  <span className="debug-item-name">{t('debug.project_init')}</span>
                  <span className="tag tag-purple">init</span>
                </button>
                <button className="debug-item" onClick={() => setSelectedScope('jobs')}>
                  <span className="debug-item-name">{t('debug.repo_monitor')}</span>
                  <span className="tag tag-teal">jobs</span>
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
            {selectedScope && selectedScope !== 'jobs' && (
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
                        <span className="debug-item-duration">{formatDuration(s.started_at, s.finished_at)}</span>
                        <span className={`tag ${st.cls}`}>{st.label}</span>
                      </span>
                    </button>
                  )
                })}
                {sessions.length === 0 && <div className="debug-empty">{t('debug.no_sessions')}</div>}
              </div>
            )}

            {/* Job runs list */}
            {selectedScope === 'jobs' && (
              <div className="debug-section">
                <div className="debug-section-title">{t('debug.job_runs')}</div>
                {jobs.map(j => (
                  <div key={j.id} className="debug-job-info">
                    <span className="debug-item-meta">{j.type}</span>
                    <span className={`tag ${j.enabled ? 'tag-green' : 'tag-dim'}`}>
                      {j.enabled ? 'on' : 'off'}
                    </span>
                    <span className="debug-item-meta">{j.interval}s</span>
                  </div>
                ))}
                {jobs.length === 0 && <div className="debug-empty">{t('debug.no_jobs')}</div>}
                {jobRuns.map(run => (
                  <div key={run.id} className="debug-item debug-job-run-item">
                    <span className="debug-item-name">
                      <span className="debug-job-run-time">{formatTime(run.started_at)}</span>
                    </span>
                    <span className="debug-item-right">
                      <span className="debug-item-duration">{formatDuration(run.started_at, run.finished_at)}</span>
                      <span className={`tag ${JOB_RUN_STATUS_COLORS[run.status] || 'tag-dim'}`}>{run.status}</span>
                    </span>
                  </div>
                ))}
                {jobRuns.length === 0 && jobs.length > 0 && <div className="debug-empty">{t('debug.no_job_runs')}</div>}
              </div>
            )}
          </div>

          {/* Right: Log viewer / Job detail */}
          <div className="debug-logs">
            {!selectedSession && selectedScope !== 'jobs' && !showAllSessions && (
              <div className="debug-placeholder">
                <div className="debug-placeholder-icon">&#128269;</div>
                <div>{t('debug.select_session_hint')}</div>
              </div>
            )}
            {!selectedSession && showAllSessions && (
              <div className="debug-placeholder">
                <div className="debug-placeholder-icon">&#128269;</div>
                <div>{t('debug.select_session_from_list')}</div>
              </div>
            )}
            {selectedScope === 'jobs' && (
              <div className="debug-logs-inner">
                {jobRuns.length > 0 ? (
                  <div className="debug-job-detail">
                    {jobRuns.map(run => (
                      <div key={run.id} className="debug-job-run-card">
                        <div className="debug-job-run-card-header">
                          <span className={`tag ${JOB_RUN_STATUS_COLORS[run.status] || 'tag-dim'}`}>{run.status}</span>
                          <span className="debug-item-meta">{run.started_at || '-'}</span>
                          <span className="debug-item-duration">{formatDuration(run.started_at, run.finished_at)}</span>
                        </div>
                        {run.error && (
                          <div className="debug-job-run-error">{run.error}</div>
                        )}
                        {(() => {
                          const changed = (run.result as Record<string, unknown>)?.repos_changed
                          if (Array.isArray(changed) && changed.length > 0) {
                            return (
                              <div className="debug-job-run-changes">
                                {changed.map((c: Record<string, string>, i: number) => (
                                  <div key={i} className="debug-job-run-change">
                                    <code>{c.repo_name}</code>
                                    <span className="debug-item-meta">{c.old} → {c.new}</span>
                                  </div>
                                ))}
                              </div>
                            )
                          }
                          return null
                        })()}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="debug-placeholder">
                    <div>{jobs.length > 0 ? t('debug.no_job_runs') : t('debug.no_jobs')}</div>
                  </div>
                )}
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
                {/* Log filters */}
                {logs.length > 0 && (
                  <div className="debug-log-filters">
                    <div className="debug-log-type-filters">
                      {LOG_TYPE_FILTERS.map(f => (
                        <button
                          key={f}
                          className={`debug-filter-btn ${logTypeFilter === f ? 'active' : ''}`}
                          onClick={() => setLogTypeFilter(f)}
                        >
                          {f}
                        </button>
                      ))}
                    </div>
                    <input
                      className="debug-log-search"
                      type="text"
                      placeholder={t('debug.search_logs')}
                      value={logSearch}
                      onChange={e => setLogSearch(e.target.value)}
                    />
                    <span className="debug-log-count">{filteredLogs.length}/{logs.length}</span>
                  </div>
                )}
                {/* Logs */}
                <div className="debug-log-list">
                  {filteredLogs.map((entry, i) => (
                    <LogEntry key={i} entry={entry} index={i} />
                  ))}
                  {logs.length === 0 && <div className="debug-empty">{t('debug.no_logs')}</div>}
                  {logs.length > 0 && filteredLogs.length === 0 && (
                    <div className="debug-empty">{t('debug.no_matching_logs')}</div>
                  )}
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
  const ts = entry.ts as string | undefined

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

  function formatLogTime(timestamp: string | undefined): string {
    if (!timestamp) return ''
    try {
      const d = new Date(timestamp)
      return d.toLocaleTimeString(undefined, { hour12: false })
    } catch {
      return ''
    }
  }

  return (
    <div className={`log-entry ${expanded ? 'expanded' : ''}`} onClick={() => setExpanded(e => !e)}>
      <div className="log-entry-header">
        <span className="log-index">#{index}</span>
        {ts && <span className="log-timestamp">{formatLogTime(ts)}</span>}
        <span className={`tag ${TYPE_COLORS[type] || 'tag-dim'}`}>{type}</span>
        {preview && <span className="log-preview">{preview}</span>}
      </div>
      {expanded && (
        <pre className="log-entry-json">{JSON.stringify(entry, null, 2)}</pre>
      )}
    </div>
  )
}
