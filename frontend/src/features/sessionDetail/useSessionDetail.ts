import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { GuildIdentity, TimelineEvent } from '../voiceBoard/types'

export interface SessionDetailResponse {
  session: {
    sessionId: string
    guild: GuildIdentity
    rootChannelName: string
    startedBy: string
    startedByName: string
    startedAt: string
    endedAt: string
    totalTalkSeconds: number
    totalAfkSeconds: number
  }
  timeline: TimelineEvent[]
}

export function useSessionDetail(sessionId: string) {
  return useQuery({
    queryKey: ['session-detail', sessionId],
    queryFn: () => api.get<SessionDetailResponse>(`/api/sessions/${sessionId}`),
  })
}
