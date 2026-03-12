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

