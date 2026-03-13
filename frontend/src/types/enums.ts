/** Backend status enums mirrored for frontend use. */

export const TaskStatus = {
  CREATED: 0,
  INITIALIZING: 1,
  PLANNING: 2,
  PLAN_LOCKED: 3,
  TODO_READY: 4,
  CODING: 5,
  REVIEWING: 6,
  DONE: 7,
} as const

export const TodoStatus = {
  PENDING: 0,
  RUNNING: 1,
  DONE: 2,
  FAILED: 3,
  SKIPPED: 4,
} as const

export const SessionStatus = {
  WAITING: 0,
  RUNNING: 1,
  DONE: 2,
  FAILED: 3,
} as const
