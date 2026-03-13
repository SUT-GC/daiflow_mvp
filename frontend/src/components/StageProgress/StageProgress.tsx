import { useNavigate } from 'react-router-dom'
import { useLocale } from '../../hooks/useLocale'
import type { TranslationKey } from '../../i18n'
import { TaskStatus } from '../../types/enums'
import './StageProgress.css'

interface StageProgressProps {
  taskId: string
  currentStage: number  // 1-4 (which page we're on)
  taskStatus?: number   // task.status from DB (0-7), determines which stages are reachable
}

const STAGES: { num: number; labelKey: TranslationKey; path: string; minStatus: number; maxStatus: number }[] = [
  { num: 1, labelKey: 'stage.1', path: 'plan', minStatus: TaskStatus.PLANNING, maxStatus: TaskStatus.PLANNING },
  { num: 2, labelKey: 'stage.2', path: 'todo', minStatus: TaskStatus.PLAN_LOCKED, maxStatus: TaskStatus.TODO_READY },
  { num: 3, labelKey: 'stage.3', path: 'coding', minStatus: TaskStatus.CODING, maxStatus: TaskStatus.CODING },
  { num: 4, labelKey: 'stage.4', path: 'review', minStatus: TaskStatus.REVIEWING, maxStatus: TaskStatus.REVIEWING },
]

export default function StageProgress({ taskId, currentStage, taskStatus }: StageProgressProps) {
  const navigate = useNavigate()
  const { t } = useLocale()

  const reachableStage = taskStatus != null
    ? STAGES.filter(s => taskStatus >= s.minStatus).length
    : currentStage

  const allDone = taskStatus != null && taskStatus >= TaskStatus.DONE

  return (
    <div className="stepper-bar">
      {STAGES.map((stage, i) => {
        // "in progress" = task is currently within this stage's status range
        const isInProgress = taskStatus != null && taskStatus >= stage.minStatus && taskStatus <= stage.maxStatus
        // "done" = task has moved past this stage
        const isDone = (taskStatus != null && taskStatus > stage.maxStatus) || (stage.num === reachableStage && allDone)
        const isActive = stage.num === currentStage
        const isReachable = stage.num <= reachableStage

        const nodeClass = [
          'stepper-node',
          isDone ? 'done' : '',
          isInProgress ? 'in-progress' : '',
          isActive ? 'active' : '',
          !isReachable ? 'disabled' : '',
        ].filter(Boolean).join(' ')

        // Line is filled (green) if the stage it leads to is done or in-progress
        const lineFilled = isDone || isInProgress

        return (
          <div className="stepper-item" key={stage.num}>
            {i > 0 && (
              <div className={`stepper-line ${lineFilled ? 'filled' : isReachable ? 'reached' : ''}`} />
            )}

            <div
              className={nodeClass}
              onClick={() => isReachable ? navigate(`/devflow/${taskId}/${stage.path}`) : undefined}
            >
              <div className="stepper-circle">
                {isDone ? (
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2.5 6L5 8.5L9.5 3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                ) : (
                  <span>{stage.num}</span>
                )}
              </div>
              <span className="stepper-label">{t(stage.labelKey)}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
