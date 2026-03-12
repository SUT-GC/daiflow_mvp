import { useState, useEffect, useCallback, useMemo } from 'react'
import { getTask, TaskData } from '../api'
import { useSession } from './useSession'
import { useStageChat } from './useStageChat'

export function usePlanStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [initialPlan, setInitialPlan] = useState('')
  const [chatPlanContent, setChatPlanContent] = useState<string | null>(null)

  useEffect(() => {
    if (taskId) {
      getTask(taskId).then(t => {
        setTask(t)
        setInitialPlan(t.tech_plan || '')
      }).catch(err => console.error('Failed to load task:', err))
    }
  }, [taskId])

  const sessionId = taskId ? `task:${taskId}:plan` : null
  const { status, logs } = useSession(sessionId)

  // Derive plan content from logs in a single pass
  const logDerivedPlan = useMemo(() => {
    if (logs.length === 0) return ''
    // Prefer the last plan_updated event
    for (let i = logs.length - 1; i >= 0; i--) {
      if (logs[i].type === 'plan_updated' && logs[i].content) {
        return logs[i].content!
      }
    }
    // Fallback: reconstruct from text_delta
    let text = ''
    for (const event of logs) {
      if (event.type === 'text_delta') {
        text += event.content || ''
      }
    }
    return text
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
    ...chat,
  }
}
