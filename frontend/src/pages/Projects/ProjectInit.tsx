import { useParams, useNavigate } from 'react-router-dom'
import { useEffect, useState, useMemo } from 'react'
import Topbar from '../../components/Shell/Topbar'
import Modal from '../../components/Modal/Modal'
import ToolGroupBlock from '../../components/ToolGroupBlock/ToolGroupBlock'
import { groupLogBlocks } from '../../utils/groupToolEvents'
import { useInitProgress, type InitSession } from '../../hooks/useInitProgress'
import { useSession } from '../../hooks/useSession'
import { getProject, retryInit, initProject } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import type { TranslationKey } from '../../i18n'
import './ProjectInit.css'

const KNOWLEDGE_KEYS: Record<string, TranslationKey> = {
  skill_fetch: 'knowledge.skill_fetch',
  repo_clone: 'knowledge.repo_clone',
  'frontend-structure': 'knowledge.frontend_structure',
  'backend-structure': 'knowledge.backend_structure',
  'business-flow': 'knowledge.business_flow',
  'component-usage': 'knowledge.component_usage',
  'module-overview': 'knowledge.module_overview',
  'api-interaction': 'knowledge.api_interaction',
  'data-entity': 'knowledge.data_entity',
  dependencies: 'knowledge.dependencies',
  project_md: 'knowledge.project_md',
}

const STATUS_CLASSES = ['waiting', 'running', 'done', 'failed']

function SessionLogModal({ sessionId, label, onClose }: { sessionId: string; label: string; onClose: () => void }) {
  const { status, logs, error } = useSession(sessionId)
  const { t } = useLocale()
  const STATUS_KEYS: TranslationKey[] = ['init.status.waiting', 'init.status.running', 'init.status.done', 'init.status.failed']

  const blocks = useMemo(() => groupLogBlocks(logs), [logs])

  return (
    <Modal open onClose={onClose} width={700}>
      <div className="modal-title">{label}</div>
      <div className="modal-sub">
        Session: <code>{sessionId}</code> — Status: <span className={`tag tag-${status === 2 ? 'green' : status === 3 ? 'red' : status === 1 ? 'amber' : 'dim'}`}>{t(STATUS_KEYS[status])}</span>
      </div>
      {error && <div className="session-log-error">{error}</div>}
      <div className="session-log-container">
        {blocks.length === 0 ? (
          <div className="session-log-empty">{t('init.no_logs')}</div>
        ) : (
          blocks.map((block, i) => {
            if (block.kind === 'text') {
              return <div key={i} className="log-block log-block-text">{block.content}</div>
            }
            if (block.kind === 'tool-group') {
              return <ToolGroupBlock key={i} tools={block.tools} />
            }
            if (block.kind === 'error') {
              return <div key={i} className="log-block log-block-error">{block.content}</div>
            }
            if (block.kind === 'status') {
              return <div key={i} className="log-block log-block-status">Status → {t(STATUS_KEYS[block.status])}</div>
            }
            return null
          })
        )}
      </div>
    </Modal>
  )
}

export default function ProjectInit() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { layers, done } = useInitProgress(projectId || null)
  const [projectName, setProjectName] = useState('')

  useEffect(() => {
    if (projectId) {
      getProject(projectId).then(p => setProjectName(p.name)).catch(err => console.error('Failed to load project:', err))
    }
  }, [projectId])

  const [retrying, setRetrying] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [viewSession, setViewSession] = useState<{ id: string; label: string } | null>(null)

  const allSessions = Object.values(layers).flat()
  const totalCount = allSessions.length
  const doneCount = allSessions.filter(s => s.status === 2).length
  const failedCount = allSessions.filter(s => s.status === 3).length
  const hasFailed = failedCount > 0
  const progress = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0

  // Elapsed time computation
  const startTime = useMemo(() => {
    const times = allSessions.map(s => s.started_at).filter(Boolean) as string[]
    if (times.length === 0) return null
    return Math.min(...times.map(t => new Date(t).getTime()))
  }, [allSessions])

  const endTime = useMemo(() => {
    if (!done) return null
    const times = allSessions.map(s => s.finished_at).filter(Boolean) as string[]
    if (times.length === 0) return null
    return Math.max(...times.map(t => new Date(t).getTime()))
  }, [allSessions, done])

  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (done || !startTime) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [done, startTime])

  const elapsed = useMemo(() => {
    if (!startTime) return null
    const ms = (done && endTime ? endTime : now) - startTime
    if (ms < 0) return null
    const secs = Math.floor(ms / 1000)
    const m = Math.floor(secs / 60)
    const s = secs % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
  }, [startTime, endTime, done, now])

  const STATUS_KEYS: TranslationKey[] = ['init.status.waiting', 'init.status.running', 'init.status.done', 'init.status.failed']

  const handleRetry = async () => {
    if (!projectId || retrying) return
    setRetrying(true)
    try {
      await retryInit(projectId)
      window.location.reload()
    } catch (err) {
      console.error('Retry failed:', err)
      setRetrying(false)
    }
  }

  const handleRegenerate = async () => {
    if (!projectId || regenerating) return
    setRegenerating(true)
    try {
      await initProject(projectId)
      window.location.reload()
    } catch (err) {
      console.error('Regenerate failed:', err)
      setRegenerating(false)
    }
  }

  const getKnowledgeType = (sessionId: string) => {
    const parts = sessionId.split(':')
    return parts[parts.length - 1]
  }

  return (
    <>
      <Topbar
        title={projectName || 'Project'}
        subtitle={t('init.subtitle')}
        backTo="/projects"
        backLabel={t('nav.projects')}
      />
      <div className="content">
        <div className="init-page">
          <div className="init-inner">
            <div className="init-header">
              <div className="init-title">
                {t('init.knowledge_gen')}
                <span className={`tag ${done && !hasFailed ? 'tag-green' : hasFailed && done ? 'tag-red' : 'tag-amber'}`}>
                  {done && !hasFailed ? t('init.completed') : hasFailed && done ? t('init.partial') : t('init.in_progress')}
                </span>
              </div>
              <p className="init-desc">
                {t('init.desc')}
                {elapsed && <span className="init-elapsed">{elapsed}</span>}
              </p>
            </div>

            <div className="progress-strip">
              <span className="progress-count">{doneCount}/{totalCount}</span>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${progress}%` }} />
              </div>
            </div>

            <div className="pipeline">
              {Object.entries(layers).sort(([a], [b]) => Number(a) - Number(b)).map(([layer, sessions]) => (
                <div key={layer} className="pipeline-layer">
                  <div className={`layer-node ${
                    (sessions as InitSession[]).every(s => s.status === 2) ? 'done' :
                    (sessions as InitSession[]).some(s => s.status === 1) ? 'running' : ''
                  }`}>
                    {t('init.layer')} {layer}
                  </div>
                  <div className="layer-children">
                    {(sessions as InitSession[]).map(s => {
                      const kt = getKnowledgeType(s.session_id)
                      const labelKey = KNOWLEDGE_KEYS[kt]
                      const label = labelKey ? t(labelKey) : kt
                      return (
                        <div
                          key={s.session_id}
                          className={`know-item ${STATUS_CLASSES[s.status]} ${s.status > 0 ? 'clickable' : ''}`}
                          onClick={() => s.status > 0 && setViewSession({ id: s.session_id, label })}
                        >
                          <div className="know-icon">
                            {s.status === 2 ? '✓' : s.status === 1 ? <span className="spinner" /> : s.status === 3 ? '✗' : '○'}
                          </div>
                          <div className="know-info">
                            <div className="know-name">{label}</div>
                            <div className="know-desc">{kt}</div>
                          </div>
                          <div className="know-status">{t(STATUS_KEYS[s.status])}</div>
                        </div>
                      )
                    })}
                  </div>
                  {Number(layer) < Object.keys(layers).length && <div className="layer-connector" />}
                </div>
              ))}
            </div>

            <div className="init-footer">
              {hasFailed && done && (
                <button
                  className="btn btn-danger"
                  disabled={retrying}
                  onClick={handleRetry}
                >
                  {retrying ? t('init.retrying') : t('init.retry_failed').replace('{count}', String(failedCount))}
                </button>
              )}
              {done && (
                <button
                  className="btn btn-ghost"
                  disabled={regenerating}
                  onClick={handleRegenerate}
                >
                  {regenerating ? t('init.regenerating') : t('init.regenerate')}
                </button>
              )}
              <div style={{ flex: 1 }} />
              <button className="btn btn-ghost" onClick={() => navigate('/projects')}>
                {t('init.return_projects')}
              </button>
              <button
                className="btn btn-primary"
                disabled={!done}
                onClick={() => navigate(`/tasks?project_id=${projectId}`)}
              >
                {t('init.enter_project')}
              </button>
            </div>
          </div>
        </div>
      </div>
      {viewSession && (
        <SessionLogModal
          sessionId={viewSession.id}
          label={viewSession.label}
          onClose={() => setViewSession(null)}
        />
      )}
    </>
  )
}
