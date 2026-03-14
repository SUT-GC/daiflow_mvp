import { useState, useEffect, useCallback, useMemo } from 'react'
import { getTask, TaskData } from '../api'
import { SessionStatus } from '../types/enums'
import { sessionIds } from '../utils/sessionIds'
import { useSession } from './useSession'
import { useStageChat } from './useStageChat'

export function usePlanStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [initialPlan, setInitialPlan] = useState('')
  const [chatPlanContent, setChatPlanContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0)
  const [regenerating, setRegenerating] = useState(false)

  const refreshTask = useCallback(() => {
    if (taskId) {
      getTask(taskId).then(t => {
        setTask(t)
        setInitialPlan(t.tech_plan || '')
      }).catch(err => setError(err.message || 'Failed to load task'))
    }
  }, [taskId])

  useEffect(() => { refreshTask() }, [refreshTask])

  const sessionId = taskId ? sessionIds.plan(taskId) : null
  const { status, logs, error: sessionError } = useSession(sessionId, sessionRefreshKey)

  // Refresh task when session completes (tech_plan is synced to DB at that point)
  useEffect(() => {
    if (status === SessionStatus.DONE || status === SessionStatus.FAILED) {
      setRegenerating(false)
      refreshTask()
    }
  }, [status, refreshTask])

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
    sessionLogs: logs,
  })

  const refreshSession = useCallback(() => {
    setChatPlanContent(null)
    setRegenerating(true)
    setSessionRefreshKey(k => k + 1)
  }, [])

  return {
    task,
    planContent,
    status,
    logs,
    error: error || sessionError,
    refreshSession,
    regenerating,
    ...chat,
  }
}
