import { useState, useEffect } from 'react'
import { getInitSessions, connectSSE } from '../api'

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

    let eventSource: { close: () => void } | null = null

    async function load() {
      try {
        const data = await getInitSessions(projectId!)
        setLayers(data)

        // Compute done from loaded data (covers page opened after init finished)
        const allSessions = (Object.values(data) as InitSession[][]).flat()
        if (allSessions.length > 0 && allSessions.every(s => s.status >= 2)) {
          setDone(true)
          return // No need for SSE — already finished
        }

        // Connect to project-level SSE bus
        eventSource = connectSSE(
          `/projects/${projectId}/init/stream`,
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
          () => { eventSource = null }
        )
      } catch (err) {
        console.error('Init progress error:', err)
      }
    }

    load()
    return () => { eventSource?.close() }
  }, [projectId])

  return { layers, done }
}
