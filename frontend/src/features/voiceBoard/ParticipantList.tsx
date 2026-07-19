import { useTranslation } from 'react-i18next'
import { EmptyState } from '../../components/EmptyState'
import { useMemberState, useTeamRecall } from './useVoiceSession'
import { ParticipantRow } from './ParticipantRow'
import type { VoiceSession } from './types'

export interface ParticipantListProps {
  guildId: string
  channelId: string
  session: VoiceSession
  selectedUserId: string | null
  onSelectUser: (userId: string) => void
}

export function ParticipantList({ guildId, channelId, session, selectedUserId, onSelectUser }: ParticipantListProps) {
  const { t } = useTranslation()
  const memberState = useMemberState(guildId, channelId)
  const teamRecall = useTeamRecall(guildId, channelId)

  const activeParticipants = session.participants.filter((participant) => participant.current_channel_id !== null)

  if (activeParticipants.length === 0) {
    return <EmptyState title={t('voice.noParticipants')} />
  }

  return (
    <div className="space-y-2">
      {activeParticipants.map((participant) => (
        <ParticipantRow
          key={participant.user_id}
          participant={participant}
          session={session}
          selected={participant.user_id === selectedUserId}
          onSelect={() => onSelectUser(participant.user_id)}
          onRecall={() => teamRecall.mutate({ user_id: participant.user_id })}
          onToggleMute={() => memberState.mutate({ user_id: participant.user_id, mute: !participant.server_muted })}
          onToggleDeafen={() => memberState.mutate({ user_id: participant.user_id, deafen: !participant.server_deafened })}
        />
      ))}
    </div>
  )
}
