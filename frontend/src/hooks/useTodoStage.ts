import { useState, useEffect, useCallback } from 'react'
import { getTask, getTodos, TaskData, TodoData } from '../api'
import { SessionStatus } from '../types/enums'
import { sessionIds } from '../utils/sessionIds'
import type { WSEvent } from '../ws'
import { useAgent } from './useAgent'

export function useTodoStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [todos, setTodos] = useState<TodoData[]>([])
  const [localError, setLocalError] = useState<string | null>(null)

  const refreshTodos = useCallback(() => {
    if (taskId) {
      getTodos(taskId).then(setTodos).catch(err => setLocalError(err.message || 'Failed to load todos'))
    }
  }, [taskId])

  const refreshTask = useCallback(() => {
    if (taskId) {
      getTask(taskId).then(setTask).catch(err => setLocalError(err.message || 'Failed to load task'))
    }
  }, [taskId])

  useEffect(() => {
    refreshTask()
    refreshTodos()
  }, [refreshTask, refreshTodos])

  const sessionId = taskId ? sessionIds.todoSplit(taskId) : null

  const onUpdated = useCallback((event: WSEvent) => {
    if (event.type === 'todo_updated') {
      refreshTodos()
    }
  }, [refreshTodos])

  const agent = useAgent({
    sessionId,
    stage: 'todo',
    entityId: taskId || '',
    onUpdated,
  })

  // Refresh task and todos when session completes (DB is synced at that point)
  useEffect(() => {
    if (agent.status === SessionStatus.DONE) {
      refreshTask()
      refreshTodos()
    }
  }, [agent.status, refreshTask, refreshTodos])

  return {
    task,
    todos,
    setTodos,
    status: agent.status,
    logs: agent.logs,
    error: localError || agent.error,
    refreshSession: agent.refreshSession,
    isStale: agent.isStale,
    messages: agent.messages,
    sendMessage: agent.sendMessage,
    streaming: agent.streaming,
  }
}
