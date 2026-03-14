import { useState, useCallback } from 'react'
import { useSession, SessionEvent } from './useSession'
import { useStageChat, ChatMessage } from './useStageChat'
import { useStaleDetection } from './useStaleDetection'
import type { WSEvent } from '../ws'

export interface UseAgentOptions {
  sessionId: string | null
  /** Agent/chat stage: "plan", "todo", "todo_exec", "review" */
  stage: 'plan' | 'todo' | 'todo_exec' | 'review'
  entityId: string
  /** Whether to enable chat functionality */
  chattable?: boolean
  /** Callback when an artifact-updated event arrives via chat */
  onUpdated?: (event: WSEvent) => void
}

export interface UseAgentReturn {
  // Session state
  status: number
  logs: SessionEvent[]
  error: string | null
  isStale: boolean
  // Chat
  messages: ChatMessage[]
  streaming: boolean
  sendMessage: (text: string) => void
  // Actions
  refreshSession: () => void
  sessionRefreshKey: number
}

/**
 * Unified agent hook that composes useSession + useStageChat + useStaleDetection.
 *
 * Stage hooks (usePlanStage, useTodoStage, useCodingStage) use this as their
 * foundation, adding stage-specific data loading and artifact tracking on top.
 */
export function useAgent({
  sessionId,
  stage,
  entityId,
  chattable = true,
  onUpdated,
}: UseAgentOptions): UseAgentReturn {
  const [sessionRefreshKey, setSessionRefreshKey] = useState(0)

  // Session state tracking
  const { status, logs, error } = useSession(sessionId, sessionRefreshKey)

  // Stale detection
  const isStale = useStaleDetection(status, logs.length)

  // Chat (only active when chattable)
  const chat = useStageChat({
    sessionId: chattable ? sessionId : null,
    stage,
    entityId,
    onUpdated,
    sessionLogs: logs,
  })

  const refreshSession = useCallback(() => {
    setSessionRefreshKey((k: number) => k + 1)
  }, [])

  return {
    status,
    logs,
    error,
    isStale,
    messages: chat.messages,
    streaming: chat.streaming,
    sendMessage: chat.sendMessage,
    refreshSession,
    sessionRefreshKey,
  }
}
