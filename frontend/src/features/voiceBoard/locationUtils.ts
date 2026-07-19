import type { Participant, VoiceSession } from './types'

export type LocationKind = 'root' | 'team' | 'away'

export function resolveLocation(participant: Participant, session: VoiceSession): { kind: LocationKind; team: string | null } {
  if (participant.current_channel_id === null) return { kind: 'away', team: null }
  if (participant.current_channel_id === session.root_channel_id) return { kind: 'root', team: null }
  const team = Object.entries(session.team_channels).find(([, channelId]) => channelId === participant.current_channel_id)?.[0]
  return { kind: 'team', team: team ?? null }
}
