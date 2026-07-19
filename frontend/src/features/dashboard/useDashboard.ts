import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'

export interface GuildIdentity {
  id: string
  name: string
  icon_url: string | null
  initials: string
}

export interface DashboardSession {
  sessionId: string
  guild: GuildIdentity
  rootChannelId: string
  rootChannelName: string
  startedAt: string
  activeParticipantCount: number
  canEdit: boolean
}

export interface GuildBreakdownRow {
  guild: GuildIdentity
  talkSeconds: number
  afkSeconds: number
}

export interface DashboardResponse {
  isAdmin: boolean
  sessions: DashboardSession[]
  summary: { talkSeconds: number; afkSeconds: number }
  guildBreakdown: GuildBreakdownRow[]
}

export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard', 'me'],
    queryFn: () => api.get<DashboardResponse>('/api/dashboard/me'),
  })
}
