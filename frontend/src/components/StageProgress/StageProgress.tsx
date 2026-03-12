import { useNavigate } from 'react-router-dom'
import { useLocale } from '../../hooks/useLocale'
import type { TranslationKey } from '../../i18n'
import { TaskStatus } from '../../types/enums'

interface StageProgressProps {
  taskId: string
  currentStage: number  // 1-4 (which page we're on)
  taskStatus?: number   // task.status from DB (0-7), determines which stages are reachable
}

const STAGES: { num: number; labelKey: TranslationKey; path: string; minStatus: number }[] = [
  { num: 1, labelKey: 'stage.1', path: 'plan', minStatus: TaskStatus.PLANNING },
  { num: 2, labelKey: 'stage.2', path: 'todo', minStatus: TaskStatus.PLAN_LOCKED },
  { num: 3, labelKey: 'stage.3', path: 'coding', minStatus: TaskStatus.CODING },
  { num: 4, labelKey: 'stage.4', path: 'review', minStatus: TaskStatus.REVIEWING },
]

export default function StageProgress({ taskId, currentStage, taskStatus }: StageProgressProps) {
  const navigate = useNavigate()
  const { t } = useLocale()
  // Use taskStatus to determine reachable stages; fall back to currentStage-based logic
  const reachableStage = taskStatus != null
    ? STAGES.filter(s => taskStatus >= s.minStatus).length
    : currentStage

  return (
    <div className="stage-bar">
      {STAGES.map((stage, i) => {
        const isDone = stage.num < reachableStage
        const isActive = stage.num === currentStage
        const isReachable = stage.num <= reachableStage
        const cls = isDone && !isActive ? 'done' : isActive ? 'active' : ''

        return (
          <span key={stage.num}>
            {i > 0 && <span className="stage-chevron"> › </span>}
            <span
              className={`stage-step ${cls}`}
              onClick={() => isReachable
                ? navigate(`/devflow/${taskId}/${stage.path}`)
                : undefined
              }
              style={isReachable ? undefined : { cursor: 'default', opacity: 0.5 }}
            >
              <span className="step-num">
                {isDone && !isActive ? '✓' : stage.num}
              </span>
              {t(stage.labelKey)}
            </span>
          </span>
        )
      })}
    </div>
  )
}
