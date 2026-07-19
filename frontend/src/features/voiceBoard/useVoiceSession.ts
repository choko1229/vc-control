import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { ChannelCatalog, MemberEntry, RoleEntry, TimelineEvent, VoiceSession } from './types'

export function voiceQueryKey(guildId: string, channelId: string) {
  return ['voice', guildId, channelId] as const
}

export function useVoiceSession(guildId: string, channelId: string) {
  return useQuery({
    queryKey: voiceQueryKey(guildId, channelId),
    queryFn: () => api.get<VoiceSession>(`/api/voice/${guildId}/${channelId}`),
    refetchInterval: 15_000,
  })
}

export function useVoiceTimeline(
  guildId: string,
  channelId: string,
  filters: { userId?: string; eventType?: string; dateFrom?: string; dateTo?: string },
) {
  const params = new URLSearchParams()
  if (filters.userId) params.set('user_id', filters.userId)
  if (filters.eventType) params.set('event_type', filters.eventType)
  if (filters.dateFrom) params.set('date_from', filters.dateFrom)
  if (filters.dateTo) params.set('date_to', filters.dateTo)
  const query = params.toString()

  return useQuery({
    queryKey: ['voice-timeline', guildId, channelId, filters],
    queryFn: () => api.get<{ events: TimelineEvent[] }>(`/api/voice/${guildId}/${channelId}/timeline${query ? `?${query}` : ''}`),
  })
}

export function useGuildChannels(guildId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['guild-channels', guildId],
    queryFn: () => api.get<ChannelCatalog>(`/api/guilds/${guildId}/channels`),
    enabled,
  })
}

export function useGuildMembers(guildId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['guild-members', guildId],
    queryFn: () => api.get<{ members: MemberEntry[] }>(`/api/guilds/${guildId}/members`),
    enabled,
  })
}

export function useGuildRoles(guildId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['guild-roles', guildId],
    queryFn: () => api.get<{ roles: RoleEntry[] }>(`/api/guilds/${guildId}/roles`),
    enabled,
  })
}

function useVoiceMutation<TBody = void>(guildId: string, channelId: string, path: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: TBody) => api.post(`/api/voice/${guildId}/${channelId}${path}`, body ?? {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: voiceQueryKey(guildId, channelId) })
    },
  })
}

export function useUpdateSettings(guildId: string, channelId: string) {
  return useVoiceMutation<{ name?: string; user_limit?: number; bitrate?: number }>(guildId, channelId, '/settings')
}

export function useUpdateAccess(guildId: string, channelId: string) {
  return useVoiceMutation<{ access_mode: string; invited_user_ids?: string[]; access_role_ids?: string[] }>(
    guildId,
    channelId,
    '/access',
  )
}

export function useMemberState(guildId: string, channelId: string) {
  return useVoiceMutation<{ user_id: string; mute?: boolean; deafen?: boolean }>(guildId, channelId, '/member-state')
}

export function useTeamAssign(guildId: string, channelId: string) {
  return useVoiceMutation<{ user_id: string; team_name: string | null }>(guildId, channelId, '/team/assign')
}

export function useTeamSplit(guildId: string, channelId: string) {
  return useVoiceMutation(guildId, channelId, '/team/split')
}

export function useTeamAssemble(guildId: string, channelId: string) {
  return useVoiceMutation(guildId, channelId, '/team/assemble')
}

export function useTeamRecall(guildId: string, channelId: string) {
  return useVoiceMutation<{ user_id: string }>(guildId, channelId, '/team/recall')
}
