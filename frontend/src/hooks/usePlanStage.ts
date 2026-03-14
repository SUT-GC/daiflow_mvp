import { useState, useEffect, useCallback, useMemo } from 'react'
import { getTask, TaskData } from '../api'
import { SessionStatus } from '../types/enums'
import { sessionIds } from '../utils/sessionIds'
import { useAgent } from './useAgent'

export function usePlanStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [initialPlan, setInitialPlan] = useState('')
  const [chatPlanContent, setChatPlanContent] = useState<string | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)

  const refreshTask = useCallback(() => {
    if (taskId) {
      getTask(taskId).then(t => {
        setTask(t)
        setInitialPlan(t.tech_plan || '')
      }).catch(err => setLocalError(err.message || 'Failed to load task'))
    }
  }, [taskId])

  useEffect(() => { refreshTask() }, [refreshTask])

  const sessionId = taskId ? sessionIds.plan(taskId) : null

  const onUpdated = useCallback((event: any) => {
    if (event.type === 'plan_updated' && event.content) {
      setChatPlanContent(event.content)
    }
  }, [])

  const agent = useAgent({
    sessionId,
    stage: 'plan',
    entityId: taskId || '',
    onUpdated,
  })

  // Refresh task when session completes (tech_plan is synced to DB at that point)
  useEffect(() => {
    if (agent.status === SessionStatus.DONE || agent.status === SessionStatus.FAILED) {
      setRegenerating(false)
      refreshTask()
    }
  }, [agent.status, refreshTask])

  // Derive plan content from logs — only use plan_updated events (actual plan.md content)
  const logDerivedPlan = useMemo(() => {
    if (agent.logs.length === 0) return ''
    for (let i = agent.logs.length - 1; i >= 0; i--) {
      if (agent.logs[i].type === 'plan_updated' && agent.logs[i].content) {
        return agent.logs[i].content!
      }
    }
    return ''
  }, [agent.logs])

  const planContent = chatPlanContent ?? (logDerivedPlan || initialPlan)

  const refreshSession = useCallback(() => {
    setChatPlanContent(null)
    setRegenerating(true)
    agent.refreshSession()
  }, [agent.refreshSession])

  return {
    task,
    planContent,
    status: agent.status,
    logs: agent.logs,
    error: localError || agent.error,
    refreshSession,
    regenerating,
    isStale: agent.isStale,
    messages: agent.messages,
    sendMessage: agent.sendMessage,
    streaming: agent.streaming,
  }
}
