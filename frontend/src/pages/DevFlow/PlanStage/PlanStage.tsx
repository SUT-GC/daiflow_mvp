import { useParams, useNavigate } from 'react-router-dom'
import StageLayout, { isStageReadonly } from '../../../components/StageLayout/StageLayout'
import MarkdownViewer from '../../../components/MarkdownViewer/MarkdownViewer'
import { usePlanStage } from '../../../hooks/usePlanStage'
import { lockPlan, triggerPlan } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'

export default function PlanStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { task, planContent, status, messages, sendMessage, streaming, regenerating, refreshSession, isStale } = usePlanStage(taskId)

  const readonly = task ? isStageReadonly(task.status, 2) : false

  const handleRegenerate = async () => {
    if (!taskId) return
    await triggerPlan(taskId)
    refreshSession()
  }

  const handleLockPlan = async () => {
    if (!taskId) return
    try {
      await lockPlan(taskId)
      navigate(`/devflow/${taskId}/todo`)
    } catch (err: any) {
      console.error('Failed to lock plan:', err)
    }
  }

  const isGenerating = status === 1 || streaming || regenerating
  const lockDisabled = !planContent || isGenerating || readonly
  const regenerateDisabled = isGenerating || readonly

  return (
    <StageLayout
      taskId={taskId!}
      task={task}
      currentStage={2}
      content={
        <div className="card plan-card">
          <div className="plan-card-title">
            {t('plan.title')}
            <span className="file-badge">plan.md</span>
          </div>
          {planContent ? (
            <MarkdownViewer content={planContent} />
          ) : (
            <div style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
              {status === 1 ? (
                <div className="typing-row" style={{ justifyContent: 'center' }}>
                  <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
                </div>
              ) : (
                t('plan.generating')
              )}
            </div>
          )}
        </div>
      }
      actions={
        <>
          <button className="btn btn-primary" onClick={handleLockPlan} disabled={lockDisabled}>
            {t('plan.lock')}
          </button>
          <button className="btn btn-ghost" onClick={handleRegenerate} disabled={regenerateDisabled}>
            {t('plan.regenerate')}
          </button>
        </>
      }
      chatTitle={t('plan.chat_title')}
      chatMessages={messages}
      chatOnSend={sendMessage}
      chatStreaming={streaming}
      isStale={isStale}
      onRetry={refreshSession}
    />
  )
}
