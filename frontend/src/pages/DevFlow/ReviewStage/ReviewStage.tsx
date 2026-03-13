import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import DiffViewer, { parseDiff } from '../../../components/DiffViewer/DiffViewer'
import Modal from '../../../components/Modal/Modal'
import { useStageChat } from '../../../hooks/useStageChat'
import { getTask, getTaskDiff, generateCommitMessage, submitMR, TaskData } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import './ReviewStage.css'

export default function ReviewStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [task, setTask] = useState<TaskData | null>(null)
  const [diff, setDiff] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [showCommitModal, setShowCommitModal] = useState(false)
  const [commitMessage, setCommitMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [generating, setGenerating] = useState(false)

  const loadData = useCallback(async () => {
    if (!taskId) return
    const t = await getTask(taskId)
    setTask(t)
    const diffData = await getTaskDiff(taskId)
    const allDiffs = diffData.diffs?.map((d: any) => d.diff).join('\n') || ''
    setDiff(allDiffs)
  }, [taskId])

  useEffect(() => { loadData() }, [loadData])

  const onUpdated = useCallback(async () => {
    if (taskId) {
      const diffData = await getTaskDiff(taskId)
      const allDiffs = diffData.diffs?.map((d: any) => d.diff).join('\n') || ''
      setDiff(allDiffs)
    }
  }, [taskId])

  const sessionId = taskId ? `task:${taskId}:review` : null

  const { messages, sendMessage, streaming } = useStageChat({
    sessionId,
    stage: 'review',
    entityId: taskId || '',
    onUpdated,
  })

  const handleSubmitMR = async () => {
    if (!taskId || !commitMessage.trim()) return
    setSubmitting(true)
    try {
      await submitMR(taskId, commitMessage)
      setSubmitted(true)
    } catch (err: any) {
      alert('Error: ' + err.message)
    } finally {
      setSubmitting(false)
    }
  }

  const { additions, deletions, files } = useMemo(() => {
    const parsed = parseDiff(diff)
    return {
      additions: parsed.reduce((sum, f) => sum + f.additions, 0),
      deletions: parsed.reduce((sum, f) => sum + f.deletions, 0),
      files: parsed.length,
    }
  }, [diff])

  const readonly = task ? isStageReadonly(task.status, 4) : false

  return (
    <>
      <StageLayout
        taskId={taskId!}
        task={task}
        currentStage={4}
        content={
          <div className="diff-main">
            <div className="diff-summary-bar">
              <div className="summary-stat">
                <span className="summary-num" style={{ color: 'var(--green)' }}>+{additions}</span>
                <span className="summary-label">{t('review.additions')}</span>
              </div>
              <div className="summary-stat">
                <span className="summary-num" style={{ color: 'var(--red)' }}>-{deletions}</span>
                <span className="summary-label">{t('review.deletions')}</span>
              </div>
              <div className="summary-stat">
                <span className="summary-num" style={{ color: 'var(--blue)' }}>{files}</span>
                <span className="summary-label">{t('review.files')}</span>
              </div>
            </div>
            <DiffViewer
              diffs={diff}
              collapsed={collapsed}
              onToggleFile={(path) => setCollapsed(prev => ({ ...prev, [path]: !prev[path] }))}
            />
          </div>
        }
        actions={
          <button
            className="btn btn-teal"
            disabled={readonly || generating}
            onClick={async () => {
              setShowCommitModal(true)
              setGenerating(true)
              setCommitMessage('')
              try {
                const result = await generateCommitMessage(taskId!)
                setCommitMessage(result.commit_message)
              } catch {
                setCommitMessage(`feat: ${task?.name}\n\nImplemented via DaiFlow automated workflow.`)
              } finally {
                setGenerating(false)
              }
            }}
          >
            {t('review.submit_mr')}
          </button>
        }
        chatTitle={t('review.chat_title')}
        chatMessages={messages}
        chatOnSend={sendMessage}
        chatStreaming={streaming}
      />

      {/* Commit Modal */}
      <Modal open={showCommitModal} onClose={() => !submitting && setShowCommitModal(false)} width={560}>
        {!submitted ? (
          <>
            <div className="modal-title">{t('review.commit_title')}</div>
            <div className="modal-sub">{t('review.commit_sub')}</div>
            <div className="field">
              <label className="field-label">{t('review.commit_msg')}</label>
              <textarea
                className="input"
                rows={6}
                value={generating ? 'Generating commit message...' : commitMessage}
                onChange={e => setCommitMessage(e.target.value)}
                disabled={generating}
                style={{ fontFamily: 'var(--mono)', fontSize: '12px' }}
              />
            </div>
            <div className="git-meta">
              <div className="git-meta-row">
                <span className="git-meta-key">{t('review.branch')}</span>
                <span className="git-meta-val val-branch">{task?.branch}</span>
              </div>
              <div className="git-meta-row">
                <span className="git-meta-key">{t('review.changes')}</span>
                <span className="git-meta-val">
                  <span style={{ color: 'var(--green)' }}>+{additions}</span>{' / '}
                  <span style={{ color: 'var(--red)' }}>-{deletions}</span>{' in '}
                  {files} {t('review.files')}
                </span>
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20 }}>
              <button className="btn btn-ghost" onClick={() => setShowCommitModal(false)}>{t('review.cancel')}</button>
              <button className="btn btn-teal" onClick={handleSubmitMR} disabled={submitting || generating}>
                {submitting ? t('review.pushing') : t('review.confirm_push')}
              </button>
            </div>
          </>
        ) : (
          <div className="success-screen">
            <div className="success-icon">✓</div>
            <div className="success-title">{t('review.success')}</div>
            <div className="success-sub">{t('review.success_sub')}</div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
              <button className="btn btn-ghost" onClick={() => setShowCommitModal(false)}>{t('review.close')}</button>
              <button className="btn btn-primary" onClick={() => navigate('/tasks')}>{t('review.return_tasks')}</button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
