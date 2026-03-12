import { useState, useEffect, useCallback } from 'react'
import { getTask, getTodos, TaskData, TodoData } from '../api'
import { SessionStatus } from '../types/enums'
import type { WSEvent } from '../ws'
import { useSession } from './useSession'
import { useStageChat } from './useStageChat'

export function useTodoStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [todos, setTodos] = useState<TodoData[]>([])
  const [error, setError] = useState<string | null>(null)

  const refreshTodos = useCallback(() => {
    if (taskId) {
      getTodos(taskId).then(setTodos).catch(err => setError(err.message || 'Failed to load todos'))
    }
  }, [taskId])

  useEffect(() => {
    if (taskId) {
      getTask(taskId).then(setTask).catch(err => setError(err.message || 'Failed to load task'))
      refreshTodos()
    }
  }, [taskId, refreshTodos])

  const sessionId = taskId ? `task:${taskId}:todo_split` : null
  const { status, logs, error: sessionError } = useSession(sessionId)

  // Refresh todos when session completes (DB is synced at that point)
  useEffect(() => {
    if (status === SessionStatus.DONE) {
      refreshTodos()
    }
  }, [status, refreshTodos])

  const onUpdated = useCallback((event: WSEvent) => {
    if (event.type === 'todo_updated') {
      // Re-fetch from DB to get full todo records with ids
      refreshTodos()
    }
  }, [refreshTodos])

  const chat = useStageChat({
    sessionId,
    stage: 'todo',
    entityId: taskId || '',
    onUpdated,
  })

  return {
    task,
    todos,
    setTodos,
    status,
    logs,
    error: error || sessionError,
    ...chat,
  }
}
