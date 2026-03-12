import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import { listTasks, createTask, deleteTask, listProjects } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import type { TaskData } from '../../api'
import type { TranslationKey } from '../../i18n'
import './Tasks.css'

const STATUS_TAGS: Record<number, string> = {
  0: 'tag-dim', 1: 'tag-amber', 2: 'tag-blue', 3: 'tag-blue',
  4: 'tag-teal', 5: 'tag-amber', 6: 'tag-purple', 7: 'tag-green',
}

function getStageFromStatus(status: number): number {
  if (status <= 2) return 1
  if (status <= 3) return 2
  if (status <= 5) return 3
  return 4
}

function getDevFlowPath(taskId: string, status: number): string {
  if (status <= 2) return `/devflow/${taskId}/plan`
  if (status === 3) return `/devflow/${taskId}/todo`
  if (status <= 5) return `/devflow/${taskId}/coding`
  return `/devflow/${taskId}/review`
}

export default function Tasks() {
  const navigate = useNavigate()
  const { t } = useLocale()
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project_id') || undefined
  const [tasks, setTasks] = useState<TaskData[]>([])
  const [projects, setProjects] = useState<any[]>([])
  const [filter, setFilter] = useState<'all' | 'active' | 'done'>('all')
  const [showDrawer, setShowDrawer] = useState(false)
  const [step, setStep] = useState(1)

  // Form state
  const [taskName, setTaskName] = useState('')
  const [taskProjectId, setTaskProjectId] = useState(projectId || '')
  const [taskDesc, setTaskDesc] = useState('')
  const [taskBranch, setTaskBranch] = useState('')
  const [taskPrd, setTaskPrd] = useState('')
  const [taskTechPlan, setTaskTechPlan] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    listTasks(projectId).then(setTasks).catch(() => {})
    listProjects().then(setProjects).catch(() => {})
  }, [projectId])

  const filteredTasks = tasks.filter(t => {
    if (filter === 'active') return t.status > 0 && t.status < 7
    if (filter === 'done') return t.status === 7
    return true
  })

  const handleCreate = async () => {
    if (!taskName.trim() || !taskProjectId) return
    setCreating(true)
    try {
      const task = await createTask({
        name: taskName,
        project_id: taskProjectId,
        description: taskDesc,
        branch: taskBranch || `feature/${taskName.toLowerCase().replace(/\s+/g, '-')}`,
        prd: taskPrd,
        tech_plan: taskTechPlan,
      })
      setShowDrawer(false)
      navigate(getDevFlowPath(task.id, task.status))
    } catch (err: any) {
      alert('Error: ' + err.message)
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(t('tasks.delete_confirm'))) return
    await deleteTask(id)
    setTasks(prev => prev.filter(t => t.id !== id))
  }

  const filterLabels: Record<string, TranslationKey> = {
    all: 'tasks.filter.all',
    active: 'tasks.filter.active',
    done: 'tasks.filter.done',
  }

  return (
    <>
      <Topbar
        title={t('tasks.title')}
        actions={
          <button className="btn btn-primary btn-sm" onClick={() => setShowDrawer(true)}>
            {t('tasks.new')}
          </button>
        }
      />
      <div className="content">
        <div className="task-filters">
          {(['all', 'active', 'done'] as const).map(f => (
            <button key={f} className={`filter ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
              {t(filterLabels[f])}
            </button>
          ))}
        </div>

        <div className="task-list">
          {filteredTasks.map(task => {
            const stage = getStageFromStatus(task.status)
            const statusKey = `tasks.status.${task.status}` as TranslationKey
            return (
              <div key={task.id} className="task-row" onClick={() => navigate(getDevFlowPath(task.id, task.status))}>
                <div>
                  <div className="task-name">{task.name}</div>
                  <div className="task-info">
                    {task.branch && <span className="task-branch">{task.branch}</span>}
                    <span className="task-time">{task.created_at ? new Date(task.created_at).toLocaleDateString() : ''}</span>
                  </div>
                </div>
                <div className="task-right">
                  <div className="stage-pip">
                    {[1, 2, 3, 4].map(s => (
                      <div key={s} className={`pip ${s < stage ? 'done' : s === stage ? 'active' : ''}`} />
                    ))}
                  </div>
                  <span className={`tag ${STATUS_TAGS[task.status] || 'tag-dim'}`}>
                    {t(statusKey)}
                  </span>
                  <button className="btn btn-danger btn-xs" onClick={(e) => handleDelete(task.id, e)}>×</button>
                </div>
              </div>
            )
          })}
          {filteredTasks.length === 0 && (
            <div style={{ textAlign: 'center', color: 'var(--t3)', padding: '40px' }}>
              {t('tasks.empty')}
            </div>
          )}
        </div>
      </div>

      {/* New Task Drawer */}
      {showDrawer && (
        <>
          <div className="overlay" onClick={() => setShowDrawer(false)} />
          <div className="drawer">
            <div className="drawer-header">
              <span className="drawer-title">{t('tasks.drawer.title')}</span>
              <button className="drawer-close" onClick={() => setShowDrawer(false)}>×</button>
            </div>
            <div className="drawer-body">
              <div className="step-indicator">
                {[1, 2, 3].map(s => (
                  <span key={s}>
                    {s > 1 && <span className={`step-line ${s <= step ? 'done' : ''}`} />}
                    <span className={`step-dot ${s === step ? 'active' : s < step ? 'done' : ''}`}>{s}</span>
                  </span>
                ))}
              </div>
              <div className="step-label-row">
                <span className="step-label">{t('tasks.step.basic')}</span>
                <span className="step-label">{t('tasks.step.prd')}</span>
                <span className="step-label">{t('tasks.step.tech')}</span>
              </div>

              {step === 1 && (
                <div className="form-step active">
                  <div className="field">
                    <label className="field-label">{t('tasks.task_name')}</label>
                    <input className="input" placeholder={t('tasks.task_name_placeholder')} value={taskName} onChange={e => setTaskName(e.target.value)} />
                  </div>
                  <div className="field">
                    <label className="field-label">{t('tasks.project')}</label>
                    <select className="input" value={taskProjectId} onChange={e => setTaskProjectId(e.target.value)}>
                      <option value="">{t('tasks.select_project')}</option>
                      {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label className="field-label">{t('tasks.description')}</label>
                    <textarea className="input" rows={3} placeholder={t('tasks.desc_placeholder')} value={taskDesc} onChange={e => setTaskDesc(e.target.value)} />
                  </div>
                  <div className="field">
                    <label className="field-label">{t('tasks.branch')}</label>
                    <input className="input" placeholder={t('tasks.branch_placeholder')} value={taskBranch} onChange={e => setTaskBranch(e.target.value)} />
                    {taskBranch && <div className="field-hint">{t('tasks.branch')}: {taskBranch}</div>}
                  </div>
                </div>
              )}

              {step === 2 && (
                <div className="form-step active">
                  <div className="field">
                    <label className="field-label">{t('tasks.prd_label')}</label>
                    <textarea className="input md-area" rows={12} placeholder={t('tasks.prd_placeholder')} value={taskPrd} onChange={e => setTaskPrd(e.target.value)} />
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="form-step active">
                  <div style={{ padding: '12px 16px', background: 'var(--blue-d)', borderRadius: 'var(--r)', marginBottom: 16, fontSize: 12, color: 'var(--blue)' }}>
                    {t('tasks.tech_hint')}
                  </div>
                  <div className="field">
                    <label className="field-label">{t('tasks.tech_label')}</label>
                    <textarea className="input md-area" rows={12} placeholder={t('tasks.tech_placeholder')} value={taskTechPlan} onChange={e => setTaskTechPlan(e.target.value)} />
                  </div>
                </div>
              )}
            </div>
            <div className="drawer-footer">
              <div className="footer-left">{t('tasks.step_of').replace('{step}', String(step))}</div>
              <div style={{ display: 'flex', gap: 8 }}>
                {step > 1 && <button className="btn btn-ghost btn-sm" onClick={() => setStep(step - 1)}>{t('tasks.back')}</button>}
                {step < 3 ? (
                  <button className="btn btn-primary btn-sm" onClick={() => {
                    if (step === 1 && !taskName.trim()) return
                    setStep(step + 1)
                  }}>{t('tasks.next')}</button>
                ) : (
                  <button className="btn btn-teal btn-sm" onClick={handleCreate} disabled={creating}>
                    {creating ? t('tasks.creating') : t('tasks.create')}
                  </button>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </>
  )
}
