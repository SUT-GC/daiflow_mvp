import { useState, useEffect, useRef, useCallback, Fragment } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import Topbar from '../../components/Shell/Topbar'
import { listTasks, createTask, deleteTask, listProjects, uploadPrdImage } from '../../api'
import { useLocale } from '../../hooks/useLocale'
import { STATUS_TAGS, getStageFromStatus, getDevFlowPath } from '../../utils/taskStages'
import { useToast } from '../../components/Toast/ToastContext'
import type { TaskData } from '../../api'
import type { TranslationKey } from '../../i18n'
import './Tasks.css'

interface PrdImagePreview {
  file: File
  url: string // object URL for preview
}

export default function Tasks() {
  const navigate = useNavigate()
  const { t } = useLocale()
  const toast = useToast()
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
  const [prdImages, setPrdImages] = useState<PrdImagePreview[]>([])
  const [creating, setCreating] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    listTasks(projectId).then(setTasks).catch(err => console.error('Failed to load tasks:', err))
    listProjects().then(setProjects).catch(err => console.error('Failed to load projects:', err))
  }, [projectId])

  // Cleanup object URLs on unmount
  useEffect(() => {
    return () => { prdImages.forEach(img => URL.revokeObjectURL(img.url)) }
  }, [prdImages])

  const filteredTasks = tasks.filter(t => {
    if (filter === 'active') return t.status > 0 && t.status < 7
    if (filter === 'done') return t.status === 7
    return true
  })

  const addImageFiles = useCallback((files: File[]) => {
    const valid = files.filter(f => f.type.startsWith('image/'))
    if (valid.length === 0) return
    const previews = valid.map(f => ({ file: f, url: URL.createObjectURL(f) }))
    setPrdImages(prev => [...prev, ...previews])
  }, [])

  const removeImage = useCallback((index: number) => {
    setPrdImages(prev => {
      const next = [...prev]
      URL.revokeObjectURL(next[index].url)
      next.splice(index, 1)
      return next
    })
  }, [])

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items
    if (!items) return
    const imageFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile()
        if (file) imageFiles.push(file)
      }
    }
    if (imageFiles.length > 0) {
      addImageFiles(imageFiles)
    }
  }, [addImageFiles])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const files = Array.from(e.dataTransfer.files)
    addImageFiles(files)
  }, [addImageFiles])

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

      // Upload PRD images after task creation
      if (prdImages.length > 0) {
        await Promise.all(prdImages.map(img => uploadPrdImage(task.id, img.file)))
      }

      setShowDrawer(false)
      navigate(getDevFlowPath(task.id, task.status))
    } catch (err: any) {
      toast.error(err.message)
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
                    {[1, 2, 3, 4, 5].map(s => (
                      <div key={s} className={`pip ${task.status >= 7 ? 'done' : s < stage ? 'done' : s === stage ? 'active' : ''}`} />
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
                {[1, 2, 3].map((s, index) => (
                  <Fragment key={s}>
                    {index > 0 && (
                      <span className={`step-line ${s <= step ? 'done' : ''}`} />
                    )}
                    <span className={`step-dot ${s === step ? 'active' : s < step ? 'done' : ''}`}>{s}</span>
                  </Fragment>
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
                    <textarea
                      className="input md-area"
                      rows={12}
                      placeholder={t('tasks.prd_placeholder')}
                      value={taskPrd}
                      onChange={e => setTaskPrd(e.target.value)}
                      onPaste={handlePaste}
                      onDrop={handleDrop}
                      onDragOver={e => e.preventDefault()}
                    />
                  </div>
                  <div className="field">
                    <label className="field-label">{t('tasks.prd_images_label')}</label>
                    <div
                      className="prd-image-drop-zone"
                      onClick={() => fileInputRef.current?.click()}
                      onDrop={handleDrop}
                      onDragOver={e => e.preventDefault()}
                    >
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        multiple
                        style={{ display: 'none' }}
                        onChange={e => {
                          if (e.target.files) addImageFiles(Array.from(e.target.files))
                          e.target.value = ''
                        }}
                      />
                      <span className="drop-zone-text">{t('tasks.prd_images_hint')}</span>
                    </div>
                    {prdImages.length > 0 && (
                      <div className="prd-image-grid">
                        {prdImages.map((img, i) => (
                          <div key={i} className="prd-image-thumb">
                            <img src={img.url} alt={img.file.name} />
                            <button className="prd-image-remove" onClick={() => removeImage(i)}>×</button>
                          </div>
                        ))}
                      </div>
                    )}
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
