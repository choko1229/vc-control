import { useTranslation } from 'react-i18next'
import { Avatar } from '../../components/Avatar'
import { Badge } from '../../components/Badge'
import { Icon } from '../../components/Icon'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { resolveLocation } from './locationUtils'
import type { Participant, VoiceSession } from './types'

export interface ParticipantRowProps {
  participant: Participant
  session: VoiceSession
  selected: boolean
  onSelect: () => void
  onRecall: () => void
  onToggleMute: () => void
  onToggleDeafen: () => void
}

export function ParticipantRow({ participant, session, selected, onSelect, onRecall, onToggleMute, onToggleDeafen }: ParticipantRowProps) {
  const { t } = useTranslation()
  const formatDuration = useFormatDuration()
  const location = resolveLocation(participant, session)
  const canRecall = session.can_edit && location.kind !== 'root'

  const locationLabel =
    location.kind === 'root'
      ? t('voice.locationRoot')
      : location.kind === 'team'
        ? t('voice.locationTeam', { team: location.team })
        : t('voice.locationAway')

  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-3 rounded-icon border px-4 py-3 transition-colors ${
        selected ? 'border-brand bg-brand-tint' : 'border-border bg-surface-panel'
      }`}
    >
      <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 items-center gap-3 text-left">
        <Avatar name={participant.user.display_name} imageUrl={participant.user.avatar_url} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate font-heading text-sm font-bold text-text-primary">{participant.user.display_name}</span>
            <Badge tone="neutral">{locationLabel}</Badge>
            {participant.self_muted ? <Badge tone="warning">{t('voice.flagSelfMuted')}</Badge> : null}
            {participant.self_deafened ? <Badge tone="warning">{t('voice.flagSelfDeafened')}</Badge> : null}
            {participant.in_afk_channel ? <Badge tone="accent">{t('voice.flagAfk')}</Badge> : null}
          </div>
          <p className="mt-0.5 text-xs text-text-secondary">
            {t('voice.talkTime', { value: formatDuration(participant.talk_seconds) })} ・ {t('voice.afkTime', { value: formatDuration(participant.afk_seconds) })}
          </p>
        </div>
      </button>
      {session.can_edit ? (
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onRecall}
            disabled={!canRecall}
            title={t('voice.recall')}
            className="flex size-8 items-center justify-center rounded-icon bg-surface-sunken text-text-secondary transition-colors hover:bg-brand-tint hover:text-brand-dark disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Icon name="keyboard_return" size={18} />
          </button>
          <button
            type="button"
            onClick={onToggleMute}
            title={participant.server_muted ? t('voice.unmute') : t('voice.mute')}
            className={`flex size-8 items-center justify-center rounded-icon transition-colors ${
              participant.server_muted ? 'bg-brand text-white' : 'bg-surface-sunken text-text-secondary hover:bg-brand-tint hover:text-brand-dark'
            }`}
          >
            <Icon name={participant.server_muted ? 'mic_off' : 'mic'} size={18} />
          </button>
          <button
            type="button"
            onClick={onToggleDeafen}
            title={participant.server_deafened ? t('voice.undeafen') : t('voice.deafen')}
            className={`flex size-8 items-center justify-center rounded-icon transition-colors ${
              participant.server_deafened ? 'bg-brand text-white' : 'bg-surface-sunken text-text-secondary hover:bg-brand-tint hover:text-brand-dark'
            }`}
          >
            <Icon name={participant.server_deafened ? 'headset_off' : 'headset_mic'} size={18} />
          </button>
        </div>
      ) : null}
    </div>
  )
}
