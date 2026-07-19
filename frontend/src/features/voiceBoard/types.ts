export interface UserIdentity {
  id: string
  display_name: string
  avatar_url: string | null
  initials: string
}

export interface GuildIdentity {
  id: string
  name: string
  icon_url: string | null
  initials: string
}

export interface Participant {
  user_id: string
  user: UserIdentity
  current_channel_id: string | null
  current_team: string | null
  talk_seconds: number
  afk_seconds: number
  self_muted: boolean
  self_deafened: boolean
  server_muted: boolean
  server_deafened: boolean
  in_afk_channel: boolean
  panel_creator: boolean
}

export interface Team {
  name: string
  channel_id: string | null
  member_count: number
  members: Participant[]
}

export type AccessMode = 'public' | 'invite' | 'role'

export interface VoiceSession {
  session_id: string
  guild_id: string
  guild: GuildIdentity
  root_channel_id: string
  root_channel: { id: string; name: string; user_limit: number; bitrate: number }
  owner: UserIdentity
  starter: UserIdentity
  started_at: string
  elapsed_seconds: number
  active_participant_count: number
  participants: Participant[]
  teams: Team[]
  unassigned_members: Participant[]
  team_names: string[]
  team_channels: Record<string, string>
  access_mode: AccessMode
  invited_user_ids: string[]
  access_role_ids: string[]
  can_edit: boolean
  can_assign_others: boolean
  management_url: string | null
}

export interface TimelineEvent {
  id: string
  created_at: string
  event_type: string
  user_id: string | null
  user_name: string
  message: string
}

export interface ChannelEntry {
  id: string
  name: string
  kind: 'category' | 'voice' | 'text'
}

export interface ChannelCatalog {
  categories: ChannelEntry[]
  voice_channels: ChannelEntry[]
  text_channels: ChannelEntry[]
}

export interface MemberEntry {
  id: string
  name: string
  username: string
}

export interface RoleEntry {
  id: string
  name: string
}
