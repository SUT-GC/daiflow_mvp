import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import { listProjects, deleteProject, getInitSessions } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import type { ProjectData } from '../../api'
import './Projects.css'

type InitStatus = 'none' | 'running' | 'done' | 'partial'

function computeInitStatus(sessions: Record<string, any[]>): InitStatus {
  const all = Object.values(sessions).flat()
  if (all.length === 0) return 'none'
  const statuses = all.map((s: any) => s.status as number)
  if (statuses.some(s => s <= 1)) return 'running'  // 0=waiting, 1=running
  if (statuses.every(s => s === 2)) return 'done'
  return 'partial' // some failed
}

const STATUS_CLASS: Record<InitStatus, string> = {
  none: 'kb-none',
  running: 'kb-running',
  done: 'kb-done',
  partial: 'kb-partial',
}

export default function Projects() {
  const navigate = useNavigate()
  const { t } = useLocale()
  const [projects, setProjects] = useState<ProjectData[]>([])
  const [initStatuses, setInitStatuses] = useState<Record<string, InitStatus>>({})

  const STATUS_LABEL: Record<InitStatus, string> = {
    none: t('projects.status.none'),
    running: t('projects.status.running'),
    done: t('projects.status.done'),
    partial: t('projects.status.partial'),
  }

  useEffect(() => {
    listProjects().then((list: ProjectData[]) => {
      setProjects(list)
      list.forEach(p => {
        getInitSessions(p.id)
          .then(sessions => setInitStatuses(prev => ({ ...prev, [p.id]: computeInitStatus(sessions) })))
          .catch(() => setInitStatuses(prev => ({ ...prev, [p.id]: 'none' })))
      })
    }).catch(() => {})
  }, [])

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(t('projects.delete_confirm'))) return
    await deleteProject(id)
    setProjects(prev => prev.filter(p => p.id !== id))
  }

  return (
    <>
      <Topbar title={t('projects.title')} />
      <div className="content">
        <div className="page-header">
          <div>
            <h1 className="page-heading">{t('projects.heading')}</h1>
            <p className="page-sub">{t('projects.sub')}</p>
          </div>
        </div>
        <div className="project-grid">
          {projects.map(p => {
            const status = initStatuses[p.id] || 'none'
            return (
              <div key={p.id} className="card project-card" onClick={() => navigate(`/tasks?project_id=${p.id}`)}>
                <div className="project-card-top">
                  <span className="project-name">{p.name}</span>
                </div>
                <p className="project-desc">{p.description}</p>
                <div className="repo-chips">
                  {p.repos?.map((r, i) => (
                    <span key={i} className="repo-chip">
                      <span className={`dot ${r.repo_type === 'frontend' ? 'dot-fe' : r.repo_type === 'backend' ? 'dot-be' : ''}`} />
                      {r.repo_type}
                    </span>
                  ))}
                </div>
                <div className="kb-row">
                  <div
                    className={`kb-status ${STATUS_CLASS[status]}`}
                    onClick={(e) => { e.stopPropagation(); navigate(`/projects/${p.id}/init`) }}
                    title="View generation process"
                  >
                    <span className={`kb-dot ${STATUS_CLASS[status]}`} />
                    {STATUS_LABEL[status]}
                  </div>
                  {status === 'done' || status === 'partial' ? (
                    <div
                      className="kb-status kb-view"
                      onClick={(e) => { e.stopPropagation(); navigate(`/projects/${p.id}/knowledge`) }}
                      title="View knowledge content"
                    >
                      📄 {t('projects.view_knowledge')}
                    </div>
                  ) : null}
                </div>
                <div className="project-card-foot">
                  <span className="project-meta">
                    {t('projects.created')} {p.created_at ? new Date(p.created_at).toLocaleDateString() : ''}
                  </span>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button
                      className="btn btn-ghost btn-xs"
                      onClick={(e) => { e.stopPropagation(); navigate(`/projects/${p.id}/edit`) }}
                    >
                      {t('projects.edit')}
                    </button>
                    <button
                      className="btn btn-danger btn-xs"
                      onClick={(e) => handleDelete(p.id, e)}
                    >
                      {t('projects.delete')}
                    </button>
                  </div>
                </div>
              </div>
            )
          })}

          <div className="card new-card" onClick={() => navigate('/projects/new')}>
            <span className="new-icon">+</span>
            <span className="new-text">{t('projects.new')}</span>
          </div>
        </div>
      </div>
    </>
  )
}
