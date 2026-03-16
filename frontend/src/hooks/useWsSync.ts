import { useEffect, useRef } from 'react'
import { wsClient, type WSEvent } from '../ws'

/** Polling interval (ms) for fallback status checks when state is non-terminal. */
const POLL_INTERVAL_MS = 5_000

export interface UseWsSyncOptions {
  /** WS channel to subscribe to. Pass null to skip entirely. */
  channel: string | null
  /**
   * Handler for real-time WS events (excluding the synthetic `_reconnected`).
   * Return `true` to signal that a terminal state was reached — useWsSync will
   * immediately stop polling and unsubscribe.
   */
  onEvent: (event: WSEvent) => boolean | void
  /**
   * Fetch current state from API. Called on:
   * - Initial mount (after subscribe)
   * - WS reconnection (_reconnected event)
   *
   * Must return `true` if the state is terminal (DONE/FAILED) — polling will not start.
   */
  fetchData: () => Promise<boolean>
  /**
   * Optional lighter poll function. Called every POLL_INTERVAL_MS when non-terminal.
   * Must return `true` if terminal — polling and subscription will be cleaned up.
   * Defaults to `fetchData` if not provided.
   */
  pollCheck?: () => Promise<boolean>
  /** Called before fetchData when the effect re-runs (channel/refreshKey change). */
  onReset?: () => void
  /** Increment to re-trigger the entire lifecycle (e.g. for session regeneration). */
  refreshKey?: number
}

/**
 * Unified WS status sync hook — three-layer defense:
 *
 * 1. **Subscribe-before-load**: subscribes to WS channel before fetching API,
 *    so no events are missed during the fetch window.
 * 2. **Reconnection re-fetch**: on WS reconnect (`_reconnected` synthetic event),
 *    automatically re-fetches from API to recover any events lost during disconnect.
 * 3. **Polling fallback**: when state is non-terminal, polls API every 5s to catch
 *    silently lost events.
 */
export function useWsSync({
  channel,
  onEvent,
  fetchData,
  pollCheck,
  onReset,
  refreshKey,
}: UseWsSyncOptions): void {
  // Use refs to avoid stale closures — the effect only re-runs on channel/refreshKey changes,
  // but always calls the latest callback versions.
  const onEventRef = useRef(onEvent)
  const fetchDataRef = useRef(fetchData)
  const pollCheckRef = useRef(pollCheck)
  const onResetRef = useRef(onReset)
  onEventRef.current = onEvent
  fetchDataRef.current = fetchData
  pollCheckRef.current = pollCheck
  onResetRef.current = onReset

  useEffect(() => {
    if (!channel) return

    let cancelled = false
    let pollTimer: ReturnType<typeof setInterval> | null = null
    let unsub: (() => void) | null = null

    const stopPoll = () => {
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    }

    const cleanup = () => {
      unsub?.()
      unsub = null
      stopPoll()
    }

    onResetRef.current?.()

    // 1. Subscribe FIRST
    unsub = wsClient.subscribe(channel, (event) => {
      if (event.type === '_reconnected') {
        doFetch()
        return
      }
      const isDone = onEventRef.current(event)
      if (isDone) cleanup()
    })

    // 2. Fetch, then conditionally start polling
    async function doFetch() {
      try {
        const isDone = await fetchDataRef.current()
        if (cancelled) return
        if (isDone) {
          cleanup()
          return
        }
        // 3. Start fallback polling (if not already running)
        if (!pollTimer) {
          pollTimer = setInterval(async () => {
            try {
              const check = pollCheckRef.current || fetchDataRef.current
              const isDone = await check()
              if (cancelled) return
              if (isDone) cleanup()
            } catch { /* ignore polling errors */ }
          }, POLL_INTERVAL_MS)
        }
      } catch { /* errors handled by consumer's fetchData via try/catch */ }
    }

    doFetch()

    return () => {
      cancelled = true
      cleanup()
    }
  }, [channel, refreshKey])
}
