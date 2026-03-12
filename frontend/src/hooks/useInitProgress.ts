import { useState, useEffect } from 'react'
import { getInitSessions } from '../api'
import { SessionStatus } from '../types/enums'
import { wsClient } from '../ws'

export interface InitSession {
  session_id: string
  status: number
  layer: number
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export function useInitProgress(projectId: string | null) {
  const [layers, setLayers] = useState<Record<number, InitSession[]>>({})
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!projectId) return

    let unsub: (() => void) | null = null

    async function load() {
      try {
        const data = await getInitSessions(projectId!)
        setLayers(data)

        // Compute done from loaded data (covers page opened after init finished)
        const allSessions = (Object.values(data) as InitSession[][]).flat()
        if (allSessions.length > 0 && allSessions.every(s => s.status >= SessionStatus.DONE)) {
          setDone(true)
          return // No need for WS — already finished
        }

        // Subscribe to project-level init bus via WebSocket
        unsub = wsClient.subscribe(
          `project:init:${projectId}`,
          (event) => {
            if (event.type === 'session_status') {
              setLayers(prev => {
                const newLayers = { ...prev }
                for (const [layer, sessions] of Object.entries(newLayers)) {
                  newLayers[Number(layer)] = (sessions as InitSession[]).map(s =>
                    s.session_id === event.session_id
                      ? { ...s, status: event.status ?? s.status, error: event.error ?? s.error }
                      : s
                  )
                }
                return newLayers
              })
            } else if (event.type === 'done') {
              setDone(true)
            }
          },
        )
      } catch (err) {
        console.error('Init progress error:', err)
      }
    }

    load()
    return () => { unsub?.() }
  }, [projectId])

  return { layers, done }
}
