import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Select } from '../../components/Field'
import { EmptyState } from '../../components/EmptyState'
import { Skeleton } from '../../components/Skeleton'
import { useVoiceTimeline } from './useVoiceSession'

const EVENT_TYPE_KEYS: Record<string, string> = {
  vc_started: 'voice.eventVcStarted',
  vc_ended: 'voice.eventVcEnded',
  member_joined: 'voice.eventMemberJoined',
  member_left: 'voice.eventMemberLeft',
  member_moved: 'voice.eventMemberMoved',
  member_mute_changed: 'voice.eventMemberMuteChanged',
  teams_split: 'voice.eventTeamsSplit',
  teams_assembled: 'voice.eventTeamsAssembled',
  member_recalled: 'voice.eventMemberRecalled',
  voice_settings_changed: 'voice.eventVoiceSettingsChanged',
}

export interface TimelineListProps {
  guildId: string
  channelId: string
}

export function TimelineList({ guildId, channelId }: TimelineListProps) {
  const { t } = useTranslation()
  const [eventType, setEventType] = useState('')
  const { data, isLoading } = useVoiceTimeline(guildId, channelId, { eventType: eventType || undefined })

  return (
    <div className="space-y-3">
      <Select value={eventType} onChange={(event) => setEventType(event.target.value)} className="max-w-xs">
        <option value="">{t('voice.filterAll')}</option>
        {Object.entries(EVENT_TYPE_KEYS).map(([value, key]) => (
          <option key={value} value={value}>
            {t(key)}
          </option>
        ))}
      </Select>

      {isLoading ? (
        <Skeleton className="h-32" />
      ) : !data || data.events.length === 0 ? (
        <EmptyState title={t('voice.noTimelineEvents')} />
      ) : (
        <ul className="space-y-1.5">
          {data.events.map((event) => (
            <li key={event.id} className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-3 py-2 text-sm">
              <span className="font-bold text-text-primary">{t(EVENT_TYPE_KEYS[event.event_type] ?? event.event_type)}</span>
              <span className="text-text-secondary">{event.user_name}</span>
              <span className="text-xs text-text-muted">{new Date(event.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
