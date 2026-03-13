import { useParams, useNavigate } from 'react-router-dom'
import Topbar from '../../../components/Shell/Topbar'
import StageProgress from '../../../components/StageProgress/StageProgress'
import ChatPanel from '../../../components/ChatPanel/ChatPanel'
import ResizableSplitPane from '../../../components/ResizableSplitPane/ResizableSplitPane'
import MarkdownViewer from '../../../components/MarkdownViewer/MarkdownViewer'
import Loading from '../../../components/Loading/Loading'
import { usePlanStage } from '../../../hooks/usePlanStage'
import { lockPlan, triggerPlan } from '../../../api'
import { useLocale } from '../../../hooks/useLocale'
import '../DevFlow.css'

export default function PlanStage() {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const { t } = useLocale()
  const { task, planContent, status, messages, sendMessage, streaming } = usePlanStage(taskId)

  const handleRegenerate = async () => {
    if (!taskId) return
    await triggerPlan(taskId)
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

  if (!task) return <Loading />

  const isLocked = task.status >= 3
  const isGenerating = status === 1 || streaming
  const lockDisabled = !planContent || isGenerating || isLocked
  const regenerateDisabled = isGenerating || isLocked
  const chatDisabled = isLocked

  return (
    <div id="page" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Topbar
        title={task.name}
        branch={task.branch}
        backTo="/tasks"
        backLabel={t('nav.tasks')}
      />
      <StageProgress taskId={taskId!} currentStage={1} taskStatus={task.status} />
      <ResizableSplitPane
        right={
          <ChatPanel
            messages={messages}
            onSend={sendMessage}
            streaming={streaming}
            title={t('plan.chat_title')}
            disabled={chatDisabled}
          />
        }
      >
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
        <div className="actions-row">
          <button className="btn btn-primary" onClick={handleLockPlan} disabled={lockDisabled}>
            {t('plan.lock')}
          </button>
          <button className="btn btn-ghost" onClick={handleRegenerate} disabled={regenerateDisabled}>{t('plan.regenerate')}</button>
        </div>
      </ResizableSplitPane>
    </div>
  )
}
