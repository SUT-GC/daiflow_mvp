import { useState, useEffect, useCallback, useMemo } from 'react'
import { getTask, TaskData } from '../api'
import { useSession } from './useSession'
import { useStageChat } from './useStageChat'

export function usePlanStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [initialPlan, setInitialPlan] = useState('')
  const [chatPlanContent, setChatPlanContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (taskId) {
      getTask(taskId).then(t => {
        setTask(t)
        setInitialPlan(t.tech_plan || '')
      }).catch(err => setError(err.message || 'Failed to load task'))
    }
  }, [taskId])

  const sessionId = taskId ? `task:${taskId}:plan` : null
  const { status, logs, error: sessionError } = useSession(sessionId)

  // Derive plan content from logs — only use plan_updated events (actual plan.md content)
  // Do NOT fall back to text_delta accumulation since that is the AI's streaming response,
  // not the plan.md file content
  const logDerivedPlan = useMemo(() => {
    if (logs.length === 0) return ''
    // Use the last plan_updated event which contains actual plan.md content
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].type === 'plan_updated' && logs[i].content) {
        return logs[i].content!
      }
    }
    return ''
  }, [logs])

  const planContent = chatPlanContent ?? (logDerivedPlan || initialPlan)

  const onUpdated = useCallback((event: any) => {
    if (event.type === 'plan_updated' && event.content) {
      setChatPlanContent(event.content)
    }
  }, [])

  const chat = useStageChat({
    sessionId,
    stage: 'plan',
    entityId: taskId || '',
    onUpdated,
  })

  return {
    task,
    planContent,
    status,
    logs,
    error: error || sessionError,
    ...chat,
  }
}
