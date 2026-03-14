import { useState, useEffect, useRef } from 'react'
import { SessionStatus } from '../types/enums'

/**
 * Detect stale sessions — sessions that are RUNNING but haven't received
 * any new events for a configurable duration (default 60s).
 *
 * This helps users identify sessions that may have been interrupted
 * without a proper status update (e.g. server crash during execution).
 */
export function useStaleDetection(
  status: number,
  logsLength: number,
  thresholdMs = 60_000,
): boolean {
  const [isStale, setIsStale] = useState(false)
  const lastEventTimeRef = useRef(Date.now())

  useEffect(() => {
    if (status !== SessionStatus.RUNNING) {
      setIsStale(false)
      return
    }

    // Reset last event time when new logs arrive
    lastEventTimeRef.current = Date.now()
    setIsStale(false)

    const timer = setInterval(() => {
      if (Date.now() - lastEventTimeRef.current > thresholdMs) {
        setIsStale(true)
      }
    }, 10_000)

    return () => clearInterval(timer)
  }, [status, logsLength, thresholdMs])

  return isStale
}
