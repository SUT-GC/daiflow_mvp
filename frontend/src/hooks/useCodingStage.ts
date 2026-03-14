import { useState, useEffect, useCallback, useRef } from 'react'
import { getTask, getTodos, getTaskDiff, getTodoDiff, joinDiffs, TaskData, TodoData } from '../api'
import { SessionStatus, TodoStatus } from '../types/enums'
import { sessionIds } from '../utils/sessionIds'
import { useAgent } from './useAgent'
import type { WSEvent } from '../ws'

/** Debounce delay (ms) before fetching diff after code_updated events. */
const CODE_UPDATE_DEBOUNCE_MS = 500

export function useCodingStage(taskId: string | undefined) {
  const [task, setTask] = useState<TaskData | null>(null)
  const [todos, setTodos] = useState<TodoData[]>([])
  const [selectedTodo, setSelectedTodo] = useState<string | null>(null)
  const [diff, setDiff] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

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
      setLocalError(err.message || 'Failed to load coding stage data')
    }
  }, [taskId])

  useEffect(() => { loadData() }, [loadData])

  const currentTodo = todos.find(t => t.id === selectedTodo)
  const sessionId = currentTodo && taskId ? sessionIds.todoExec(taskId, currentTodo.id) : null

  // Fetch per-todo diff when selecting a completed/failed todo
  const fetchTodoDiff = useCallback(async (todoId: string) => {
    let todoDiff = ''
    try {
      const data = await getTodoDiff(todoId)
      todoDiff = joinDiffs(data)
    } catch {
      // per-todo diff failed, will fallback below
    }
    // If per-todo diff is empty, fallback to task-level diff
    if (todoDiff) {
      setDiff(todoDiff)
      return
    }
    if (taskId) {
      try {
        const data = await getTaskDiff(taskId)
        setDiff(joinDiffs(data))
      } catch {
        setDiff('')
      }
    }
  }, [taskId])

  // When selecting a todo, load its diff and clear any pending debounce
  useEffect(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    if (!selectedTodo) {
      setDiff('')
      return
    }
    const todo = todos.find(t => t.id === selectedTodo)
    if (todo && (todo.status === TodoStatus.DONE || todo.status === TodoStatus.FAILED)) {
      fetchTodoDiff(selectedTodo)
    }
  }, [selectedTodo, todos, fetchTodoDiff])

  const onUpdated = useCallback(async (event: WSEvent) => {
    if (event.type === 'code_updated' && taskId) {
      // During execution, use task-level diff (uncommitted changes)
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(async () => {
        try {
          const diffData = await getTaskDiff(taskId)
          const allDiffs = joinDiffs(diffData)
          setDiff(allDiffs)
          const td = await getTodos(taskId)
          setTodos(td)
        } catch (err: any) {
          setLocalError(err.message || 'Failed to refresh diff')
        }
      }, CODE_UPDATE_DEBOUNCE_MS)
    }
  }, [taskId])

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const agent = useAgent({
    sessionId,
    stage: 'todo_exec',
    entityId: currentTodo?.id || '',
    onUpdated,
  })

  // Reload data when a todo execution completes, then fetch per-todo diff
  useEffect(() => {
    if (agent.status === SessionStatus.DONE || agent.status === SessionStatus.FAILED) {
      loadData()
      if (selectedTodo) {
        // Small delay to let backend commit the HEAD hash
        setTimeout(() => fetchTodoDiff(selectedTodo), 300)
      }
    }
  }, [agent.status, loadData, selectedTodo, fetchTodoDiff])

  const allDone = todos.length > 0 && todos.every(t => t.status === TodoStatus.DONE || t.status === TodoStatus.SKIPPED)

  return {
    task,
    todos,
    selectedTodo,
    setSelectedTodo,
    diff,
    todoSessionStatus: agent.status,
    logs: agent.logs,
    loadData,
    allDone,
    isStale: agent.isStale,
    error: localError || agent.error,
    messages: agent.messages,
    sendMessage: agent.sendMessage,
    streaming: agent.streaming,
  }
}
