import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import DiffViewer, { parseDiff } from '../../../components/DiffViewer/DiffViewer'
import Modal from '../../../components/Modal/Modal'
import { useStageChat } from '../../../hooks/useStageChat'
import { useCommitModal } from '../../../hooks/useCommitModal'
import { getTask, getTaskDiff, joinDiffs, TaskData } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import { sessionIds } from '../../../utils/sessionIds'
import './ReviewStage.css'

export default function ReviewStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const [task, setTask] = useState<TaskData | null>(null)
  const [diff, setDiff] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const loadData = useCallback(async () => {
    if (!taskId) return
    const t = await getTask(taskId)
    setTask(t)
    const diffData = await getTaskDiff(taskId)
    setDiff(joinDiffs(diffData))
  }, [taskId])

  useEffect(() => { loadData() }, [loadData])

  const onUpdated = useCallback(async () => {
    if (taskId) {
      const diffData = await getTaskDiff(taskId)
      setDiff(joinDiffs(diffData))
    }
  }, [taskId])

  const sessionId = taskId ? sessionIds.review(taskId) : null

  const { messages, sendMessage, streaming } = useStageChat({
    sessionId,
    stage: 'review',
    entityId: taskId || '',
    onUpdated,
  })

  const commitModal = useCommitModal({ taskId, taskName: task?.name })

  const { additions, deletions, files } = useMemo(() => {
    const parsed = parseDiff(diff)
    return {
      additions: parsed.reduce((sum, f) => sum + f.additions, 0),
      deletions: parsed.reduce((sum, f) => sum + f.deletions, 0),
      files: parsed.length,
    }
  }, [diff])

  const readonly = task ? isStageReadonly(task.status, 5) : false

  return (
    <>
      <StageLayout
        taskId={taskId!}
        task={task}
        currentStage={5}
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
            disabled={readonly || commitModal.generating}
            onClick={commitModal.openModal}
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
      <Modal open={commitModal.open} onClose={commitModal.closeModal} width={560}>
        {!commitModal.submitted ? (
          <>
            <div className="modal-title">{t('review.commit_title')}</div>
            <div className="modal-sub">{t('review.commit_sub')}</div>
            <div className="field">
              <label className="field-label">{t('review.commit_msg')}</label>
              <textarea
                className="input"
                rows={6}
                value={commitModal.generating ? 'Generating commit message...' : commitModal.commitMessage}
                onChange={e => commitModal.setCommitMessage(e.target.value)}
                disabled={commitModal.generating}
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
              <button className="btn btn-ghost" onClick={commitModal.closeModal}>{t('review.cancel')}</button>
              <button className="btn btn-teal" onClick={commitModal.submit} disabled={commitModal.submitting || commitModal.generating}>
                {commitModal.submitting ? t('review.pushing') : t('review.confirm_push')}
              </button>
            </div>
          </>
        ) : (
          <div className="success-screen">
            <div className="success-icon">✓</div>
            <div className="success-title">{t('review.success')}</div>
            <div className="success-sub">{t('review.success_sub')}</div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 20 }}>
              <button className="btn btn-ghost" onClick={commitModal.closeModal}>{t('review.close')}</button>
              <button className="btn btn-primary" onClick={() => navigate('/tasks')}>{t('review.return_tasks')}</button>
            </div>
          </div>
        )}
      </Modal>
    </>
  )
}
