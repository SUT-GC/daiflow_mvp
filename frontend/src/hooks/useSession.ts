import { useState, useEffect, useCallback, useRef } from 'react'
import { getSessionStatus, getSessionLogs, SessionStatusData } from '../api'
import { SessionStatus } from '../types/enums'
import { wsClient } from '../ws'

export interface SessionEvent {
  type: string
  content?: string
  tool_name?: string
  args?: any
  tool_call_id?: string
  status?: number
  error?: string
  ts?: string
}

// Convert API log response to SessionEvent
function convertLogToEvent(log: Record<string, unknown>): SessionEvent {
  return {
    type: (log.event_type as string) || (log.type as string) || 'unknown',
    content: log.content as string,
    tool_name: log.tool_name as string,
    args: log.args,
    tool_call_id: log.tool_call_id as string,
    status: log.status as number,
    error: log.error as string,
    ts: log.ts as string,
  }
}

export function useSession(sessionId: string | null) {
  const [status, setStatus] = useState<number>(0)
  const [logs, setLogs] = useState<SessionEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  // Use ref to accumulate logs and rAF to batch updates
  const logsRef = useRef<SessionEvent[]>([])
  const rafRef = useRef<number | null>(null)

  const flushLogs = useCallback(() => {
    rafRef.current = null
    setLogs([...logsRef.current])
  }, [])

  useEffect(() => {
    if (!sessionId) return

    let unsub: (() => void) | null = null

    async function load() {
      try {
        // 1. Fetch status
        const statusData = await getSessionStatus(sessionId!)
        setStatus(statusData.status)

        // 2. Fetch logs
        const logsData = await getSessionLogs(sessionId!)
        if (Array.isArray(logsData)) {
          const events = logsData.map(convertLogToEvent)
          logsRef.current = events
          setLogs(events)
        }

        // 3. Subscribe via WebSocket if not already finished
        if (statusData.status !== SessionStatus.DONE && statusData.status !== SessionStatus.FAILED) {
          unsub = wsClient.subscribe(
            `session:${sessionId}`,
            (event) => {
              logsRef.current.push(event)
              // Batch log updates via rAF
              if (rafRef.current === null) {
                rafRef.current = requestAnimationFrame(flushLogs)
              }
              if (event.type === 'status_change') {
                if (event.status != null) setStatus(event.status)
                if (event.error) setError(event.error)
              }
            },
          )
        }
      } catch (err: any) {
        setError(err.message)
      }
    }

    load()
    return () => {
      unsub?.()
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [sessionId, flushLogs])

  return { status, logs, error }
}
