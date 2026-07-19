import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../lib/apiClient'
import type { ChannelCatalog, GuildIdentity } from '../voiceBoard/types'

export interface AdminSettings {
  client_id: string
  redirect_uri: string
  base_url: string
  owner_user_id: string
  dashboard_host: string
  dashboard_port: string
  timeline_retention_days: string
  has_bot_token: boolean
  has_client_secret: boolean
}

export interface GuildConfigData {
  managed_category_id: number | null
  base_voice_channel_id: number | null
  notification_channel_id: number | null
  first_empty_notice_sec: number
  final_delete_sec: number
  solo_cleanup_mode: string
  solo_notice_after_sec: number
  solo_delete_warning_after_sec: number
  solo_repeat_notice_sec: number
  ranking_post_enabled: boolean
  ranking_post_channel_id: number | null
  ranking_post_frequencies: string[]
  ranking_post_time: string
  ranking_post_targets: string[]
  team_mode: string
  team_names: string[]
  enabled: boolean
  guild_language: string
}

export interface Diagnostic {
  level: string
  code: string
}

export interface ErrorLogRow {
  created_at: string
  level: string
  source: string
  message: string
}

export interface RecentSessionRow {
  sessionId: string
  guild: GuildIdentity
  rootChannelName: string
  endedAt: string
  totalTalkSeconds: number
}

export function useAdminSettings() {
  return useQuery({
    queryKey: ['admin', 'settings'],
    queryFn: () => api.get<{ settings: AdminSettings; recommendedRedirectUri: string | null }>('/api/admin/settings'),
  })
}

export function useUpdateAdminSettings() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post('/api/admin/settings', body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'settings'] })
    },
  })
}

export function useAdminGuilds() {
  return useQuery({
    queryKey: ['admin', 'guilds'],
    queryFn: () => api.get<{ guilds: GuildIdentity[] }>('/api/admin/guilds'),
  })
}

export function useAdminGuildDetail(guildId: string) {
  return useQuery({
    queryKey: ['admin', 'guild', guildId],
    queryFn: () => api.get<{ config: GuildConfigData; diagnostics: Diagnostic[]; channels: ChannelCatalog }>(`/api/admin/guilds/${guildId}`),
    enabled: !!guildId,
  })
}

export function useUpdateAdminGuildSettings(guildId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/api/admin/guilds/${guildId}/settings`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'guild', guildId] })
    },
  })
}

export function usePostRankingNow(guildId: string) {
  return useMutation({
    mutationFn: () => api.post<{ ok: true; messageKey: string }>(`/api/admin/guilds/${guildId}/rankings/post`),
  })
}

export function useAdminErrorLogs(page: number) {
  return useQuery({
    queryKey: ['admin', 'error-logs', page],
    queryFn: () => api.get<{ errorLogs: ErrorLogRow[]; totalLogs: number; page: number }>(`/api/admin/error-logs?page=${page}`),
  })
}

export function useAdminRecentSessions() {
  return useQuery({
    queryKey: ['admin', 'recent-sessions'],
    queryFn: () => api.get<{ sessions: RecentSessionRow[] }>('/api/admin/recent-sessions'),
  })
}
