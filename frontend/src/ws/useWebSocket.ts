import { useEffect } from 'react'
import { wsClient } from './WebSocketClient'

/**
 * Initialize WebSocket connection at the app level.
 * Call once in App.tsx or a top-level provider.
 */
export function useWebSocket() {
  useEffect(() => {
    wsClient.connect()
    return () => wsClient.disconnect()
  }, [])
}
