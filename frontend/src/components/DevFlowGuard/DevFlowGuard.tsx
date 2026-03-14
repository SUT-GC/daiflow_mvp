import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getTask, type TaskData } from '../../api'
import { getDevFlowPath, getStageFromStatus, STAGE_PATH_TO_NUM } from '../../utils/taskStages'
import Loading from '../Loading/Loading'

/**
 * Route guard for devflow stage pages.
 *
 * Checks that the task's current status matches the requested stage URL.
 * If not, redirects to the correct stage (e.g. navigating to /coding when
 * the task is still in PLANNING will redirect to /plan).
 */
export default function DevFlowGuard({
  stagePath,
  children,
}: {
  /** The URL segment for this stage, e.g. "plan", "coding" */
  stagePath: string
  children: React.ReactNode
}) {
  const { taskId } = useParams()
  const navigate = useNavigate()
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    if (!taskId) return
    let cancelled = false

    getTask(taskId)
      .then((task: TaskData) => {
        if (cancelled) return
        const requestedStage = STAGE_PATH_TO_NUM[stagePath] ?? 1
        const currentStage = getStageFromStatus(task.status)

        // Only redirect if trying to access a stage ahead of the task's current progress
        if (requestedStage > currentStage) {
          navigate(getDevFlowPath(taskId, task.status), { replace: true })
        } else {
          setChecked(true)
        }
      })
      .catch(() => {
        if (!cancelled) setChecked(true) // Let the page handle 404
      })

    return () => { cancelled = true }
  }, [taskId, stagePath, navigate])

  if (!checked) return <Loading />
  return <>{children}</>
}
