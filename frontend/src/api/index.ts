const BASE = '/api'

async function request<T = any>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

// ── Types ──
export interface SSEEvent {
  type: 'text_delta' | 'thinking' | 'tool_call' | 'tool_result' | 'done' | 'status_change' | 'error' | 'user_message' | 'plan_updated' | 'todo_updated' | 'code_updated' | 'session_status'
  content?: string
  tool_name?: string
  args?: Record<string, any>
  tool_call_id?: string
  status?: number
  error?: string
  session_id?: string
  ts?: string
}

export interface TaskData {
  id: string
  name: string
  project_id: string
  description: string
  branch: string
  prd: string
  tech_plan: string
  status: number
  mr_info: Record<string, any>
  created_at: string | null
  updated_at: string | null
}

export interface TodoData {
  id: string
  seq: number
  title: string
  description: string
  status: number
  cody_session_id?: string
}

export interface ProjectData {
  id: string
  name: string
  description: string
  skill_names: string[]
  repos?: RepoData[]
  created_at: string | null
  updated_at: string | null
}

export interface RepoData {
  id: string
  git_url: string
  local_path: string
  repo_type: string
  repo_type_label: string
  description: string
}

// ── Settings ──
export const getSettings = () => request('/settings')
export const updateSettings = (data: Record<string, string>) =>
  request('/settings', { method: 'PUT', body: JSON.stringify(data) })
export const checkSettings = () => request<{ configured: boolean; model: string }>('/settings/check')

// ── Projects ──
export const listProjects = () => request('/projects')
export const getProject = (id: string) => request(`/projects/${id}`)
export const createProject = (data: any) =>
  request('/projects', { method: 'POST', body: JSON.stringify(data) })
export const updateProject = (id: string, data: any) =>
  request(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteProject = (id: string) =>
  request(`/projects/${id}`, { method: 'DELETE' })
export const initProject = (id: string) =>
  request(`/projects/${id}/init`, { method: 'POST' })
export const getInitSessions = (id: string) =>
  request(`/projects/${id}/init/sessions`)
export const retryInit = (id: string) =>
  request(`/projects/${id}/init/retry`, { method: 'POST' })
export const getProjectKnowledge = (id: string) =>
  request<{ project_id: string; files: { name: string; type: string; content: string }[] }>(`/projects/${id}/knowledge`)

// ── Tasks ──
export const listTasks = (projectId?: string) =>
  request(`/tasks${projectId ? `?project_id=${projectId}` : ''}`)
export const getTask = (id: string) => request(`/tasks/${id}`)
export const createTask = (data: any) =>
  request('/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id: string, data: any) =>
  request(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteTask = (id: string) =>
  request(`/tasks/${id}`, { method: 'DELETE' })
export const lockPlan = (id: string) =>
  request(`/tasks/${id}/lock-plan`, { method: 'POST' })
export const startCoding = (id: string) =>
  request(`/tasks/${id}/start-coding`, { method: 'POST' })
export const startReview = (id: string) =>
  request(`/tasks/${id}/start-review`, { method: 'POST' })
export const triggerPlan = (id: string) =>
  request(`/tasks/${id}/plan`, { method: 'POST' })
export const triggerTodo = (id: string) =>
  request(`/tasks/${id}/todo`, { method: 'POST' })
export const getTodos = (taskId: string) =>
  request(`/tasks/${taskId}/todos`)
export const getTaskDiff = (taskId: string) =>
  request(`/tasks/${taskId}/diff`)
export const submitMR = (taskId: string, commitMessage: string) =>
  request(`/tasks/${taskId}/submit-mr`, {
    method: 'POST',
    body: JSON.stringify({ commit_message: commitMessage }),
  })

// ── Todos ──
export const executeTodo = (todoId: string) =>
  request(`/todos/${todoId}/execute`, { method: 'POST' })

// ── Sessions ──
export const getSessionStatus = (sessionId: string) =>
  request(`/sessions/${sessionId}/status`)
export const getSessionLogs = (sessionId: string) =>
  request(`/sessions/${sessionId}/logs`)

// ── SSE Helpers ──
export function connectSSE(
  path: string,
  onEvent: (event: SSEEvent) => void,
  onDone?: () => void,
  maxRetries = 3,
  heartbeatTimeout = 30000,
) {
  const url = `${BASE}${path}`
  let retries = 0
  let stopped = false
  let currentES: EventSource | null = null
  let heartbeatTimer: ReturnType<typeof setTimeout> | null = null

  function resetHeartbeat(eventSource: EventSource) {
    if (heartbeatTimer) clearTimeout(heartbeatTimer)
    heartbeatTimer = setTimeout(() => {
      // No message received within timeout — assume connection is stale
      if (!stopped) {
        eventSource.close()
        if (retries < maxRetries) {
          retries++
          setTimeout(connect, 1000 * retries)
        } else {
          onDone?.()
        }
      }
    }, heartbeatTimeout)
  }

  function connect() {
    const eventSource = new EventSource(url)
    currentES = eventSource
    resetHeartbeat(eventSource)

    eventSource.onmessage = (e) => {
      resetHeartbeat(eventSource)
      try {
        const data = JSON.parse(e.data) as SSEEvent
        retries = 0
        onEvent(data)
        if (data.type === 'done' || (data.type === 'status_change' && (data.status ?? 0) >= 2)) {
          stopped = true
          if (heartbeatTimer) clearTimeout(heartbeatTimer)
          eventSource.close()
          onDone?.()
        }
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    }

    eventSource.onerror = () => {
      if (heartbeatTimer) clearTimeout(heartbeatTimer)
      eventSource.close()
      if (!stopped && retries < maxRetries) {
        retries++
        setTimeout(connect, 1000 * retries)
      } else {
        onDone?.()
      }
    }
  }

  connect()

  return {
    close: () => {
      stopped = true
      if (heartbeatTimer) clearTimeout(heartbeatTimer)
      currentES?.close()
    },
  }
}

export async function* streamChat(
  path: string,
  message: string,
  signal?: AbortSignal,
): AsyncGenerator<any> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
    signal,
  })

  if (!res.ok) throw new Error(`Chat error: ${res.status}`)
  if (!res.body) return

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            yield JSON.parse(line.slice(6))
          } catch (err) {
            console.warn('SSE JSON parse error:', line, err)
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
