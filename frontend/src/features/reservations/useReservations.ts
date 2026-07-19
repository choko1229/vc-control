import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { ChannelCatalog, GuildIdentity, MemberEntry } from '../voiceBoard/types'

export interface Reservation {
  id: number
  guildId: string
  vcName: string
  categoryId: string | null
  userLimit: number
  bitrate: number | null
  mentionType: string
  mentionTargets: string[]
  description: string
  startAt: string
  endAt: string | null
  repeatMode: string
  repeatWeekdays: number[]
  status: string
  createdChannelId: string | null
}

export function useMyAdminGuilds() {
  return useQuery({
    queryKey: ['guilds', 'mine'],
    queryFn: () => api.get<{ guilds: GuildIdentity[] }>('/api/guilds/mine'),
  })
}

export function useGuildConfigSummary(guildId: string) {
  return useQuery({
    queryKey: ['guild-config-summary', guildId],
    queryFn: () => api.get<{ managedCategoryId: string | null }>(`/api/guilds/${guildId}/config`),
    enabled: !!guildId,
  })
}

export function useReservationChannels(guildId: string) {
  return useQuery({
    queryKey: ['guild-channels', guildId],
    queryFn: () => api.get<ChannelCatalog>(`/api/guilds/${guildId}/channels`),
    enabled: !!guildId,
  })
}

export function useReservationMembers(guildId: string) {
  return useQuery({
    queryKey: ['guild-members', guildId],
    queryFn: () => api.get<{ members: MemberEntry[] }>(`/api/guilds/${guildId}/members`),
    enabled: !!guildId,
  })
}

export function useReservationsList(guildId: string) {
  return useQuery({
    queryKey: ['reservations', guildId],
    queryFn: () => api.get<{ reservations: Reservation[] }>(`/api/guilds/${guildId}/reservations`),
    enabled: !!guildId,
  })
}

export function useCreateVoiceChannel(guildId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      vc_type: string
      owner_user_id?: string
      vc_name?: string
      user_limit?: number
      bitrate?: number
      end_at?: string
      description?: string
    }) => api.post<{ ok: true; channelId: string }>('/api/voice/create', { guild_id: guildId, ...body }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['dashboard', 'me'] })
    },
  })
}

export function useCreateReservation(guildId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/api/guilds/${guildId}/reservations`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reservations', guildId] })
    },
  })
}

export function useDeleteReservation(guildId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (scheduledId: number) => api.delete(`/api/reservations/${scheduledId}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['reservations', guildId] })
    },
  })
}
