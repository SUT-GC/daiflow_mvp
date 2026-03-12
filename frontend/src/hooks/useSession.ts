import { useState, useEffect, useCallback, useRef } from 'react'
import { getSessionStatus, getSessionLogs, connectSSE } from '../api'

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

    let eventSource: { close: () => void } | null = null

    async function load() {
      try {
        // 1. Fetch status
        const statusData = await getSessionStatus(sessionId!)
        setStatus(statusData.status)

        // 2. Fetch logs
        const logsData = await getSessionLogs(sessionId!)
        if (Array.isArray(logsData)) {
          logsRef.current = logsData
          setLogs(logsData)
        }

        // 3. If running, connect SSE
        if (statusData.status === 1) {
          eventSource = connectSSE(
            `/sessions/${sessionId}/stream`,
            (event) => {
              logsRef.current = [...logsRef.current, event]
              // Batch log updates via rAF
              if (rafRef.current === null) {
                rafRef.current = requestAnimationFrame(flushLogs)
              }
              if (event.type === 'status_change') {
                if (event.status != null) setStatus(event.status)
                if (event.error) setError(event.error)
              }
            },
            () => {
              eventSource = null
              // Final flush on completion
              if (rafRef.current !== null) {
                cancelAnimationFrame(rafRef.current)
                rafRef.current = null
              }
              flushLogs()
            }
          )
        }
      } catch (err: any) {
        setError(err.message)
      }
    }

    load()
    return () => {
      eventSource?.close()
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
    }
  }, [sessionId, flushLogs])

  return { status, logs, error }
}
