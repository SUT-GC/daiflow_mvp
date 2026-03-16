import { useState } from 'react'
import { getInitSessions } from '../api'
import { SessionStatus } from '../types/enums'
import { useWsSync } from './useWsSync'

export interface InitSession {
  session_id: string
  status: number
  layer: number
  error?: string | null
  started_at?: string | null
  finished_at?: string | null
}

function convertSessions(data: any[]): Record<number, InitSession[]> {
  const result: Record<number, InitSession[]> = {}
  for (const layerData of data) {
    result[layerData.layer] = layerData.sessions.map((s: any) => ({
      session_id: s.session_id,
      status: s.status,
      layer: layerData.layer,
      error: s.error,
      started_at: s.started_at,
      finished_at: s.finished_at,
    }))
  }
  return result
}

function allSessionsDone(layers: Record<number, InitSession[]>): boolean {
  const all = Object.values(layers).flat()
  return all.length > 0 && all.every(s => s.status >= SessionStatus.DONE)
}

export function useInitProgress(projectId: string | null) {
  const [layers, setLayers] = useState<Record<number, InitSession[]>>({})
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useWsSync({
    channel: projectId ? `project:init:${projectId}` : null,
    onEvent: (event) => {
      if (event.type === 'session_status') {
        setLayers(prev => {
          const newLayers = { ...prev }
          for (const [layer, sessions] of Object.entries(newLayers)) {
            newLayers[Number(layer)] = (sessions as InitSession[]).map(s =>
              s.session_id === event.session_id
                ? {
                    ...s,
                    status: event.status ?? s.status,
                    error: event.error ?? s.error,
                    started_at: event.started_at ?? s.started_at,
                    finished_at: event.finished_at ?? s.finished_at,
                  }
                : s
            )
          }
          return newLayers
        })
      } else if (event.type === 'done') {
        setDone(true)
        return true
      }
    },
    fetchData: async () => {
      try {
        const data = await getInitSessions(projectId!)
        const converted = convertSessions(data)
        setLayers(converted)

        if (allSessionsDone(converted)) {
          setDone(true)
          return true
        }
        return false
      } catch (err: any) {
        setError(err.message || 'Failed to load init progress')
        return false
      }
    },
  })

  return { layers, done, error }
}
