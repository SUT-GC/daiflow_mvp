import Topbar from '../Shell/Topbar'
import StageProgress from '../StageProgress/StageProgress'
import ChatPanel from '../ChatPanel/ChatPanel'
import ResizableSplitPane from '../ResizableSplitPane/ResizableSplitPane'
import Loading from '../Loading/Loading'
import { useLocale } from '../../hooks/useLocale'
import { TaskStatus } from '../../types/enums'
import type { TaskData } from '../../api'
import type { ChatMessage } from '../../hooks/useStageChat'
import './StageLayout.css'

/** Map stage number (1-5) to the minimum task status that locks it. */
const STAGE_LOCK_STATUS: Record<number, number> = {
  1: TaskStatus.PLANNING,     // Init locks when status >= PLANNING (2)
  2: TaskStatus.PLAN_LOCKED,  // Plan locks when status >= PLAN_LOCKED (3)
  3: TaskStatus.CODING,       // Todo locks when status >= CODING (5)
  4: TaskStatus.REVIEWING,    // Coding locks when status >= REVIEWING (6)
  5: TaskStatus.DONE,         // Review locks when status >= DONE (7)
}

export function isStageReadonly(taskStatus: number, currentStage: number): boolean {
  const lockAt = STAGE_LOCK_STATUS[currentStage]
  if (lockAt == null) return false
  return taskStatus >= lockAt
}

interface StageLayoutProps {
  taskId: string
  task: TaskData | null
  currentStage: 1 | 2 | 3 | 4 | 5
  /** Main content area — each stage fills this in */
  content: React.ReactNode
  /** Action bar buttons — rendered at the bottom spanning full width */
  actions?: React.ReactNode
  /** Chat configuration */
  chatTitle: string
  chatMessages: ChatMessage[]
  chatOnSend: (msg: string) => void
  chatResponding: boolean
  /** Whether the session appears stale (no events for 60s while RUNNING) */
  isStale?: boolean
  /** Called when user clicks retry on the stale banner */
  onRetry?: () => void
}

export default function StageLayout({
  taskId,
  task,
  currentStage,
  content,
  actions,
  chatTitle,
  chatMessages,
  chatOnSend,
  chatResponding,
  isStale,
  onRetry,
}: StageLayoutProps) {
  const { t } = useLocale()

  if (!task) return <Loading />

  const readonly = isStageReadonly(task.status, currentStage)

  return (
    <div className="stage-page">
      <Topbar
        title={task.name}
        branch={task.branch}
        taskStatus={task.status}
        backTo="/tasks"
        backLabel={t('nav.tasks')}
      />
      <StageProgress taskId={taskId} currentStage={currentStage} taskStatus={task.status} />
      {isStale && (
        <div className="stage-stale-banner">
          <span>{t('stale.message')}</span>
          {onRetry && <button className="stage-stale-retry" onClick={onRetry}>{t('stale.retry')}</button>}
        </div>
      )}
      <div className="stage-body">
        <ResizableSplitPane
          right={
            <ChatPanel
              messages={chatMessages}
              onSend={chatOnSend}
              responding={chatResponding}
              title={chatTitle}
              disabled={readonly}
            />
          }
        >
          <div className="stage-content">
            {content}
          </div>
        </ResizableSplitPane>
      </div>
      {actions && (
        <div className={`stage-actions ${readonly ? 'stage-actions-disabled' : ''}`}>
          {actions}
        </div>
      )}
    </div>
  )
}
