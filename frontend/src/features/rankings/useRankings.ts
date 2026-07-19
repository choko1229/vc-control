import { useQuery } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { GuildIdentity, UserIdentity } from '../voiceBoard/types'

export interface RankingRow {
  rank: number
  guild: GuildIdentity
  user: UserIdentity
  talkSeconds: number
  afkSeconds: number
}

export interface RankingsResponse {
  topRankings: RankingRow[]
  otherRankings: RankingRow[]
  knownGuilds: GuildIdentity[]
}

export function useRankings(period: string, guildId: string) {
  const params = new URLSearchParams({ period })
  if (guildId) params.set('guild_id', guildId)
  return useQuery({
    queryKey: ['rankings', period, guildId],
    queryFn: () => api.get<RankingsResponse>(`/api/rankings?${params.toString()}`),
  })
}
