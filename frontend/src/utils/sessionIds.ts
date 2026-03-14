/** Centralized session ID construction — mirrors backend daiflow/session_ids.py. */

export const sessionIds = {
  plan: (taskId: string) => `task:${taskId}:plan`,
  todoSplit: (taskId: string) => `task:${taskId}:todo_split`,
  todoExec: (taskId: string, todoId: string) => `task:${taskId}:todo:${todoId}`,
  review: (taskId: string) => `task:${taskId}:review`,
  taskInitBus: (taskId: string) => `task:init:${taskId}`,
}
