import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { GuildIdentity } from '../voiceBoard/types'

export interface DailyChartRow {
  date: string
  talkSeconds: number
  afkSeconds: number
  effectiveSeconds: number
  widthPercent: number
}

export interface HourlyHeatmapRow {
  hour: number
  talkSeconds: number
  afkSeconds: number
  alpha: number
}

export interface StatsResponse {
  summary: { talkSeconds: number; afkSeconds: number; effectiveSeconds: number }
  talkRatio: { effectivePercent: number; afkPercent: number }
  breakdown: { guild: GuildIdentity; talkSeconds: number; afkSeconds: number }[]
  knownGuilds: GuildIdentity[]
  dailyChart: DailyChartRow[]
  hourlyHeatmap: HourlyHeatmapRow[]
}

export function useStats(period: string, guildId: string) {
  const params = new URLSearchParams({ period })
  if (guildId) params.set('guild_id', guildId)
  return useQuery({
    queryKey: ['stats', 'me', period, guildId],
    queryFn: () => api.get<StatsResponse>(`/api/stats/me?${params.toString()}`),
  })
}
