import { useParams, useNavigate } from 'react-router-dom'
import { useState, useRef, useCallback, useEffect } from 'react'
import Topbar from '../../../components/Shell/Topbar'
import StageProgress from '../../../components/StageProgress/StageProgress'
import ChatPanel from '../../../components/ChatPanel/ChatPanel'
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

  // Resizable split pane state
  const [chatWidth, setChatWidth] = useState(340)
  const dragging = useRef(false)
  const startX = useRef(0)
  const startWidth = useRef(340)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true
    startX.current = e.clientX
    startWidth.current = chatWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [chatWidth])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return
      const delta = startX.current - e.clientX
      const newWidth = Math.max(240, Math.min(800, startWidth.current + delta))
      setChatWidth(newWidth)
    }
    const onMouseUp = () => {
      if (dragging.current) {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
    }
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
    return () => {
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

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

  // Issue 7: Plan is locked (status >= 3), disable all interactions
  const isLocked = task.status >= 3
  // Issue 5 & 6: AI is generating/streaming, disable buttons
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
      <div className="devflow-body">
        <div className="devflow-main">
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
        </div>
        {/* Resizable drag handle */}
        <div
          className="resize-handle"
          onMouseDown={onMouseDown}
        />
        <ChatPanel
          messages={messages}
          onSend={sendMessage}
          streaming={streaming}
          title={t('plan.chat_title')}
          disabled={chatDisabled}
          style={{ width: chatWidth }}
        />
      </div>
    </div>
  )
}
