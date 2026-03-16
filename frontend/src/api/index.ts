const BASE = '/api'

/** Default request timeout in milliseconds. */
const REQUEST_TIMEOUT_MS = 30_000

async function request<T = unknown>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal: controller.signal,
    })
    if (!res.ok) {
      let detail = `API error: ${res.status}`
      try {
        const body = await res.json()
        if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        // Response body is not JSON — keep the status-based message
      }
      throw new Error(detail)
    }
    return res.json()
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new Error(`Request timeout: ${path}`)
    }
    throw err
  } finally {
    clearTimeout(timeoutId)
  }
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

export interface SessionStatusData {
  session_id: string
  cody_session_id: string | null
  type: string
  ref_id: string
  layer: number | null
  status: number
  error: string | null
  started_at: string | null
  finished_at: string | null
}

export interface DiffData {
  diffs: { repo: string; repo_type: string; diff: string; error?: string }[]
}

/** Extract and join raw diff strings from a DiffData response. */
export function joinDiffs(data: DiffData): string {
  return data.diffs?.map(d => d.diff).join('\n') || ''
}

interface CreateProjectData {
  name: string
  description?: string
  repos?: { git_url: string; repo_type: string; repo_type_label?: string; description?: string }[]
}

interface CreateTaskData {
  name: string
  project_id: string
  description?: string
  branch?: string
  prd?: string
  tech_plan?: string
}

interface UpdateTaskData {
  name?: string
  description?: string
  branch?: string
  prd?: string
  tech_plan?: string
}

// ── Settings ──
export const getSettings = () => request<Record<string, string>>('/settings')
export const updateSettings = (data: Record<string, string>) =>
  request('/settings', { method: 'PUT', body: JSON.stringify(data) })
export const checkSettings = () => request<{ configured: boolean; model: string }>('/settings/check')
export const testConnection = (data: { cody_model: string; cody_base_url: string; cody_api_key: string }) =>
  request<{ ok: boolean; model: string }>('/settings/test', { method: 'POST', body: JSON.stringify(data) })

// ── Projects ──
export const listProjects = () => request<ProjectData[]>('/projects')
export const getProject = (id: string) => request<ProjectData>(`/projects/${id}`)
export const createProject = (data: CreateProjectData) =>
  request<ProjectData>('/projects', { method: 'POST', body: JSON.stringify(data) })
export const updateProject = (id: string, data: Partial<CreateProjectData>) =>
  request<ProjectData>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteProject = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}`, { method: 'DELETE' })
export const initProject = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}/init`, { method: 'POST' })
export interface InitLayerData {
  layer: number
  sessions: (Pick<SessionStatusData, 'session_id' | 'status' | 'error' | 'started_at' | 'finished_at'>)[]
  status: string
}
export const getInitSessions = (id: string) =>
  request<InitLayerData[]>(`/projects/${id}/init/sessions`)
export const retryProjectInit = (id: string) =>
  request<{ ok: boolean }>(`/projects/${id}/init/retry`, { method: 'POST' })
export const getProjectKnowledge = (id: string) =>
  request<{ project_id: string; files: { name: string; type: string; content: string }[] }>(`/projects/${id}/knowledge`)

export interface InitSessionData {
  session_id: string
  status: number
  error: string | null
  started_at: string | null
  finished_at: string | null
}

// ── Tasks ──
export const listTasks = (projectId?: string) =>
  request<TaskData[]>(`/tasks${projectId ? `?project_id=${projectId}` : ''}`)
export const getTask = (id: string) => request<TaskData>(`/tasks/${id}`)
export const createTask = (data: CreateTaskData) =>
  request<TaskData>('/tasks', { method: 'POST', body: JSON.stringify(data) })
export const updateTask = (id: string, data: UpdateTaskData) =>
  request<TaskData>(`/tasks/${id}`, { method: 'PUT', body: JSON.stringify(data) })
export const deleteTask = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}`, { method: 'DELETE' })
export const confirmInit = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/confirm-init`, { method: 'POST' })
export const retryTaskInit = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/retry-init`, { method: 'POST' })
export const getTaskInitSessions = (taskId: string) =>
  request<InitSessionData[]>(`/tasks/${taskId}/init/sessions`)
export const lockPlan = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/lock-plan`, { method: 'POST' })
export const startCoding = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/start-coding`, { method: 'POST' })
export const startReview = (id: string) =>
  request<{ ok: boolean; status: number }>(`/tasks/${id}/start-review`, { method: 'POST' })
export const triggerPlan = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}/plan`, { method: 'POST' })
export const triggerTodo = (id: string) =>
  request<{ ok: boolean }>(`/tasks/${id}/todo`, { method: 'POST' })
export const getTodos = (taskId: string) =>
  request<TodoData[]>(`/tasks/${taskId}/todos`)
export const getTaskDiff = (taskId: string) =>
  request<DiffData>(`/tasks/${taskId}/diff`)
export const generateCommitMessage = (taskId: string) =>
  request<{ commit_message: string }>(`/tasks/${taskId}/generate-commit-message`, { method: 'POST' })
export const submitMR = (taskId: string, commitMessage: string) =>
  request<{ ok: boolean; results: { repo: string; status: string; error?: string }[] }>(`/tasks/${taskId}/submit-mr`, {
    method: 'POST',
    body: JSON.stringify({ commit_message: commitMessage }),
  })

// ── Todos ──
export const executeTodo = (todoId: string) =>
  request<{ ok: boolean }>(`/todos/${todoId}/execute`, { method: 'POST' })
export const skipTodo = (todoId: string) =>
  request<{ ok: boolean }>(`/todos/${todoId}/skip`, { method: 'POST' })
export const getTodoDiff = (todoId: string) =>
  request<DiffData>(`/todos/${todoId}/diff`)

// ── Sessions ──
export const listSessions = (params?: { ref_id?: string; type?: string }) => {
  const qs = new URLSearchParams()
  if (params?.ref_id) qs.set('ref_id', params.ref_id)
  if (params?.type) qs.set('type', params.type)
  const query = qs.toString()
  return request<SessionStatusData[]>(`/sessions${query ? `?${query}` : ''}`)
}
export const getSessionStatus = (sessionId: string) =>
  request<SessionStatusData>(`/sessions/${sessionId}/status`)
export const getSessionLogs = (sessionId: string) =>
  request<Record<string, unknown>[]>(`/sessions/${sessionId}/logs`)

// ── Jobs ──
export interface JobData {
  id: string
  project_id: string
  type: string
  enabled: boolean
  interval: number
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface JobRunData {
  id: string
  job_id: string
  status: string
  result: Record<string, unknown>
  error: string | null
  started_at: string | null
  finished_at: string | null
  project_id?: string
  job_type?: string
}

export const listJobs = (projectId?: string) =>
  request<JobData[]>(`/jobs${projectId ? `?project_id=${projectId}` : ''}`)
export const getJobRuns = (jobId: string, limit = 50) =>
  request<JobRunData[]>(`/jobs/${jobId}/runs?limit=${limit}`)
