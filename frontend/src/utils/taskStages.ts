/**
 * Shared task status → stage/path mapping utilities.
 *
 * 5 stages: Init → Plan → Todo → Coding → Review
 */

/** CSS tag class for each task status value (0-7). */
export const STATUS_TAGS: Record<number, string> = {
  0: 'tag-dim', 1: 'tag-amber', 2: 'tag-blue', 3: 'tag-blue',
  4: 'tag-teal', 5: 'tag-amber', 6: 'tag-purple', 7: 'tag-green',
}

/** Map task status (0-7) to a stage number (1-5). */
export function getStageFromStatus(status: number): number {
  if (status <= 1) return 1  // CREATED / INITIALIZING → Init
  if (status <= 2) return 2  // PLANNING → Plan
  if (status <= 4) return 3  // PLAN_LOCKED / TODO_READY → Todo
  if (status <= 5) return 4  // CODING → Coding
  return 5                   // REVIEWING / DONE → Review
}

/** Get the devflow page path for a task based on its current status. */
export function getDevFlowPath(taskId: string, status: number): string {
  if (status <= 1) return `/devflow/${taskId}/init`
  if (status <= 2) return `/devflow/${taskId}/plan`
  if (status <= 4) return `/devflow/${taskId}/todo`
  if (status <= 5) return `/devflow/${taskId}/coding`
  return `/devflow/${taskId}/review`
}
