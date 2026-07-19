import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Avatar } from '../../components/Avatar'
import { Badge } from '../../components/Badge'
import { Button } from '../../components/Button'
import { useToast } from '../../components/Toast'
import { useTeamAssemble, useTeamAssign, useTeamSplit } from './useVoiceSession'
import type { Participant, VoiceSession } from './types'

export interface TeamBoardProps {
  guildId: string
  channelId: string
  session: VoiceSession
  selectedUserId: string | null
  onAssigned: () => void
}

function MemberChip({ participant }: { participant: Participant }) {
  return (
    <div className="flex items-center gap-2 rounded-pill bg-surface-panel px-2.5 py-1">
      <Avatar name={participant.user.display_name} imageUrl={participant.user.avatar_url} size="xs" />
      <span className="text-xs font-bold text-text-primary">{participant.user.display_name}</span>
    </div>
  )
}

export function TeamBoard({ guildId, channelId, session, selectedUserId, onAssigned }: TeamBoardProps) {
  const { t } = useTranslation()
  const { show } = useToast()
  const [splitArmed, setSplitArmed] = useState(false)

  const teamAssign = useTeamAssign(guildId, channelId)
  const teamSplit = useTeamSplit(guildId, channelId)
  const teamAssemble = useTeamAssemble(guildId, channelId)

  function handleAssign(teamName: string | null) {
    if (!selectedUserId) {
      show('info', t('common.error'), t('voice.selectMemberFirst'))
      return
    }
    teamAssign.mutate(
      { user_id: selectedUserId, team_name: teamName },
      { onSuccess: onAssigned },
    )
  }

  function handleSplitClick() {
    if (!splitArmed) {
      setSplitArmed(true)
      show('warning', t('common.error'), t('voice.splitWarning'))
      window.setTimeout(() => setSplitArmed(false), 4000)
      return
    }
    setSplitArmed(false)
    teamSplit.mutate(undefined, {
      onError: (error) => show('danger', t('voice.saveError'), error.message),
    })
  }

  const groups: { name: string; slot: string | null; members: Participant[] }[] = [
    { name: t('voice.unassigned'), slot: null, members: session.unassigned_members },
    ...session.teams.map((team) => ({ name: team.name, slot: team.name, members: team.members })),
  ]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {groups.map((group) => (
          <button
            key={group.slot ?? '__unassigned__'}
            type="button"
            onClick={() => handleAssign(group.slot)}
            className="rounded-card border border-dashed border-border bg-surface-sunken p-3 text-left transition-colors hover:border-brand hover:bg-brand-tint"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-heading text-sm font-bold text-text-primary">{group.name}</span>
              <Badge tone="neutral">{group.members.length}</Badge>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {group.members.map((member) => (
                <MemberChip key={member.user_id} participant={member} />
              ))}
            </div>
          </button>
        ))}
      </div>

      {session.can_edit ? (
        <div className="flex flex-wrap gap-2">
          <Button variant={splitArmed ? 'destructive' : 'primary'} onClick={handleSplitClick} loading={teamSplit.isPending}>
            {splitArmed ? t('voice.splitConfirm') : t('voice.split')}
          </Button>
          <Button
            variant="secondary"
            loading={teamAssemble.isPending}
            onClick={() => teamAssemble.mutate(undefined, { onError: (error) => show('danger', t('voice.saveError'), error.message) })}
          >
            {t('voice.assemble')}
          </Button>
        </div>
      ) : null}
    </div>
  )
}
