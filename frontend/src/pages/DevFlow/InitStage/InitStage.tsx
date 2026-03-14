import { useEffect, useState, useMemo, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../../components/Shell/Topbar'
import StageProgress from '../../../components/StageProgress/StageProgress'
import { getTask, getTaskInitSessions, confirmInit, type TaskData, type InitSessionData } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { wsClient } from '../../../ws'
import type { TranslationKey } from '../../../i18n'
import '../../Projects/ProjectInit.css'

const SESSION_LABELS: Record<string, TranslationKey> = {
  fetch_code: 'init_stage.fetch_code',
  sync_skills: 'init_stage.sync_skills',
}

const STATUS_CLASSES = ['waiting', 'running', 'done', 'failed']

export default function InitStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [task, setTask] = useState<TaskData | null>(null)
  const [sessions, setSessions] = useState<InitSessionData[]>([])
  const [confirming, setConfirming] = useState(false)

  const loadData = useCallback(async () => {
    if (!taskId) return
    const [taskData, sessionsData] = await Promise.all([
      getTask(taskId),
      getTaskInitSessions(taskId),
    ])
    setTask(taskData)
    setSessions(sessionsData)
  }, [taskId])

  useEffect(() => { loadData() }, [loadData])

  // Subscribe to init WS channel for real-time updates
  useEffect(() => {
    if (!taskId) return
    const channel = `task:init:${taskId}`
    wsClient.subscribe(channel, (event: any) => {
      if (event.type === 'session_status') {
        setSessions(prev => prev.map(s =>
          s.session_id === event.session_id
            ? { ...s, status: event.status, error: event.error || null, started_at: event.started_at || s.started_at, finished_at: event.finished_at || s.finished_at }
            : s
        ))
      }
      if (event.type === 'done') {
        // Reload to get final state
        loadData()
      }
    })
    return () => { wsClient.unsubscribe(channel) }
  }, [taskId, loadData])

  const totalCount = sessions.length
  const doneCount = sessions.filter(s => s.status === 2).length
  const hasFailed = sessions.some(s => s.status === 3)
  const allDone = totalCount > 0 && doneCount === totalCount
  const progress = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0

  // If task has moved past INITIALIZING, redirect to appropriate stage
  useEffect(() => {
    if (task && task.status >= 2) {
      navigate(`/devflow/${taskId}/plan`, { replace: true })
    }
  }, [task, taskId, navigate])

  // Elapsed time
  const startTime = useMemo(() => {
    const times = sessions.map(s => s.started_at).filter(Boolean) as string[]
    if (times.length === 0) return null
    return Math.min(...times.map(st => new Date(st).getTime()))
  }, [sessions])

  const endTime = useMemo(() => {
    if (!allDone && !hasFailed) return null
    const times = sessions.map(s => s.finished_at).filter(Boolean) as string[]
    if (times.length === 0) return null
    return Math.max(...times.map(st => new Date(st).getTime()))
  }, [sessions, allDone, hasFailed])

  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if ((allDone || hasFailed) || !startTime) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [allDone, hasFailed, startTime])

  const elapsed = useMemo(() => {
    if (!startTime) return null
    const end = (allDone || hasFailed) && endTime ? endTime : now
    const ms = end - startTime
    if (ms < 0) return null
    const secs = Math.floor(ms / 1000)
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }, [startTime, endTime, allDone, hasFailed, now])

  const handleConfirm = async () => {
    if (!taskId || confirming) return
    setConfirming(true)
    try {
      await confirmInit(taskId)
      navigate(`/devflow/${taskId}/plan`)
    } catch (err) {
      console.error('Failed to confirm init:', err)
      setConfirming(false)
    }
  }

  const getSessionKey = (sessionId: string): string => {
    const parts = sessionId.split(':')
    return parts[parts.length - 1]
  }

  const statusKeys: TranslationKey[] = ['init.status.waiting', 'init.status.running', 'init.status.done', 'init.status.failed']

  return (
    <div className="stage-page">
      <Topbar
        title={task?.name || ''}
        branch={task?.branch}
        taskStatus={task?.status}
        backTo="/tasks"
        backLabel={t('nav.tasks')}
      />
      <StageProgress taskId={taskId!} currentStage={1} taskStatus={task?.status} />
      <div className="content">
        <div className="init-page">
          <div className="init-inner">
            <div className="init-header">
              <div className="init-title">
                {t('init_stage.title')}
                <span className={`tag ${allDone ? 'tag-green' : hasFailed ? 'tag-red' : 'tag-amber'}`}>
                  {allDone ? t('init_stage.completed') : hasFailed ? t('init_stage.failed') : t('init_stage.in_progress')}
                </span>
              </div>
              <p className="init-desc">
                {t('init_stage.desc')}
                {elapsed && <span className="init-elapsed">{elapsed}</span>}
              </p>
            </div>

            {totalCount > 0 && (
              <div className="progress-strip">
                <span className="progress-count">{doneCount}/{totalCount}</span>
                <div className="progress-bar">
                  <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
              </div>
            )}

            <div className="pipeline">
              {sessions.map((s, i) => {
                const key = getSessionKey(s.session_id)
                const labelKey = SESSION_LABELS[key]
                const label = labelKey ? t(labelKey) : key
                const statusClass = STATUS_CLASSES[s.status] || ''

                return (
                  <div key={s.session_id} className="pipeline-layer">
                    <div className={`layer-node ${statusClass}`}>
                      {t('init_stage.title')} {i + 1}
                    </div>
                    <div className="layer-children">
                      <div className={`know-item ${statusClass}`}>
                        <div className="know-icon">
                          {s.status === 2 ? '✓' : s.status === 1 ? <span className="spinner" /> : s.status === 3 ? '✗' : '○'}
                        </div>
                        <div className="know-info">
                          <div className="know-name">{label}</div>
                          <div className="know-desc">{key}</div>
                        </div>
                        <div className="know-status">{t(statusKeys[s.status])}</div>
                      </div>
                    </div>
                    {i < sessions.length - 1 && <div className="layer-connector" />}
                  </div>
                )
              })}
            </div>

            <div className="init-footer">
              <div style={{ flex: 1 }} />
              <button
                className="btn btn-primary"
                disabled={!allDone || confirming}
                onClick={handleConfirm}
              >
                {confirming ? '...' : t('init_stage.confirm')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
