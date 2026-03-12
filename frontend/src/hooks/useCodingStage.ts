import { useState, useEffect, useCallback, useRef } from 'react'
import { getTask, getTodos, getTaskDiff, TaskData, TodoData } from '../api'
import { SessionStatus, TodoStatus } from '../types/enums'
import { useSession } from './useSession'
import { useStageChat } from './useStageChat'

export function useCodingStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [todos, setTodos] = useState<TodoData[]>([])
  const [selectedTodo, setSelectedTodo] = useState<string | null>(null)
  const [diff, setDiff] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Debounce timer for code_updated events
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadData = useCallback(async () => {
    if (!taskId) return
    try {
      const t = await getTask(taskId)
      setTask(t)
      const td = await getTodos(taskId)
      setTodos(td)
    } catch (err: any) {
      setError(err.message || 'Failed to load coding stage data')
    }
  }, [taskId])

  useEffect(() => { loadData() }, [loadData])

  const currentTodo = todos.find(t => t.id === selectedTodo)
  const sessionId = currentTodo ? `task:${taskId}:todo:${currentTodo.id}` : null

  const { status: todoSessionStatus, logs, error: sessionError } = useSession(sessionId)

  const onUpdated = useCallback(async (event: any) => {
    if (event.type === 'code_updated' && taskId) {
      // Debounce: wait 500ms before fetching to avoid N+1 rapid-fire requests
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(async () => {
        try {
          const diffData = await getTaskDiff(taskId)
          const allDiffs = diffData.diffs?.map((d: any) => d.diff).join('\n') || ''
          setDiff(allDiffs)
          const td = await getTodos(taskId)
          setTodos(td)
        } catch (err: any) {
          setError(err.message || 'Failed to refresh diff')
        }
      }, 500)
    }
  }, [taskId])

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const chat = useStageChat({
    sessionId,
    stage: 'todo_exec',
    entityId: currentTodo?.id || '',
    onUpdated,
  })

  // Reload data when a todo execution completes
  useEffect(() => {
    if (todoSessionStatus === SessionStatus.DONE || todoSessionStatus === SessionStatus.FAILED) {
      loadData()
    }
  }, [todoSessionStatus, loadData])

  const allDone = todos.length > 0 && todos.every(t => t.status === TodoStatus.DONE)

  return {
    task,
    todos,
    selectedTodo,
    setSelectedTodo,
    diff,
    setDiff,
    todoSessionStatus,
    logs,
    loadData,
    allDone,
    error: error || sessionError,
    ...chat,
  }
}
