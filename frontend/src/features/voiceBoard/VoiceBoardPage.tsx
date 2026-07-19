import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { MetricTile } from '../../components/MetricTile'
import { Skeleton } from '../../components/Skeleton'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { useRealtimeSocket } from '../../hooks/useRealtimeSocket'
import { useVoiceSession } from './useVoiceSession'
import { ParticipantList } from './ParticipantList'
import { TeamBoard } from './TeamBoard'
import { TimelineList } from './TimelineList'
import { SettingsForm } from './SettingsForm'
import { AccessForm } from './AccessForm'

export function VoiceBoardPage() {
  const { t } = useTranslation()
  const { guildId, channelId } = useParams<{ guildId: string; channelId: string }>()
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null)
  const formatDuration = useFormatDuration()

  useRealtimeSocket(guildId && channelId ? [`session:${channelId}`, `guild:${guildId}`] : [])

  const { data: session, isLoading } = useVoiceSession(guildId ?? '', channelId ?? '')

  if (isLoading || !session) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{session.root_channel.name}</CardTitle>
        </CardHeader>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricTile label={t('dashboard.participants', { count: session.active_participant_count })} value={String(session.active_participant_count)} />
          <MetricTile label={t('voice.summaryHeading')} value={formatDuration(session.elapsed_seconds)} />
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('voice.participantsHeading')}</CardTitle>
        </CardHeader>
        <ParticipantList
          guildId={guildId ?? ''}
          channelId={channelId ?? ''}
          session={session}
          selectedUserId={selectedUserId}
          onSelectUser={setSelectedUserId}
        />
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('voice.teamsHeading')}</CardTitle>
        </CardHeader>
        <TeamBoard
          guildId={guildId ?? ''}
          channelId={channelId ?? ''}
          session={session}
          selectedUserId={selectedUserId}
          onAssigned={() => setSelectedUserId(null)}
        />
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('voice.timelineHeading')}</CardTitle>
        </CardHeader>
        <TimelineList guildId={guildId ?? ''} channelId={channelId ?? ''} />
      </Card>

      {session.can_edit ? (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>{t('voice.settingsHeading')}</CardTitle>
            </CardHeader>
            <SettingsForm guildId={guildId ?? ''} channelId={channelId ?? ''} session={session} />
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>{t('voice.accessHeading')}</CardTitle>
            </CardHeader>
            <AccessForm guildId={guildId ?? ''} channelId={channelId ?? ''} session={session} />
          </Card>
        </div>
      ) : (
        <p className="text-sm text-text-secondary">{t('voice.readOnlyNotice')}</p>
      )}
    </div>
  )
}
