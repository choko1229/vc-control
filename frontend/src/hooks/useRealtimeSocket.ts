import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/apiClient'

interface RealtimeMessage {
  event: string
  payload: Record<string, unknown>
}

const MAX_BACKOFF_MS = 30_000
const PING_INTERVAL_MS = 25_000

export function useRealtimeSocket(scopes: string[]) {
  const queryClient = useQueryClient()
  const scopeKey = scopes.join(',')

  useEffect(() => {
    if (!scopeKey) return
    let socket: WebSocket | null = null
    let reconnectAttempts = 0
    let reconnectTimer: number | undefined
    let pingTimer: number | undefined
    let cancelled = false

    function handleMessage(message: RealtimeMessage) {
      const guildId = message.payload?.guild_id as string | undefined
      const rootChannelId = message.payload?.root_channel_id as string | undefined

      switch (message.event) {
        case 'session_update':
        case 'session_event':
        case 'timeline_event':
          if (guildId && rootChannelId) {
            void queryClient.invalidateQueries({ queryKey: ['voice', guildId, rootChannelId] })
          }
          void queryClient.invalidateQueries({ queryKey: ['dashboard', 'me'] })
          break
        case 'important_notification':
          void queryClient.invalidateQueries({ queryKey: ['notifications'] })
          break
        case 'global_state':
          void queryClient.invalidateQueries({ queryKey: ['dashboard', 'me'] })
          break
        default:
          break
      }
    }

    async function connect() {
      if (cancelled) return
      try {
        const { token } = await api.get<{ token: string }>('/api/ws-token')
        if (cancelled) return
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
        socket = new WebSocket(`${protocol}://${window.location.host}/ws?token=${encodeURIComponent(token)}&scopes=${encodeURIComponent(scopeKey)}`)

        socket.onopen = () => {
          reconnectAttempts = 0
          pingTimer = window.setInterval(() => socket?.readyState === WebSocket.OPEN && socket.send('ping'), PING_INTERVAL_MS)
        }
        socket.onmessage = (event) => {
          if (event.data === 'pong') return
          try {
            handleMessage(JSON.parse(event.data) as RealtimeMessage)
          } catch {
            /* ignore malformed frame */
          }
        }
        socket.onclose = () => {
          window.clearInterval(pingTimer)
          if (cancelled) return
          const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** reconnectAttempts)
          reconnectAttempts += 1
          reconnectTimer = window.setTimeout(connect, delay)
        }
      } catch {
        if (cancelled) return
        const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** reconnectAttempts)
        reconnectAttempts += 1
        reconnectTimer = window.setTimeout(connect, delay)
      }
    }

    void connect()

    return () => {
      cancelled = true
      window.clearTimeout(reconnectTimer)
      window.clearInterval(pingTimer)
      socket?.close()
    }
  }, [scopeKey, queryClient])
}
