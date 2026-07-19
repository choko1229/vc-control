import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { MetricTile } from '../../components/MetricTile'
import { EmptyState } from '../../components/EmptyState'
import { Skeleton } from '../../components/Skeleton'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { EVENT_TYPE_KEYS } from '../voiceBoard/eventTypeLabels'
import { useSessionDetail } from './useSessionDetail'

export function SessionDetailPage() {
  const { t } = useTranslation()
  const { sessionId } = useParams<{ sessionId: string }>()
  const formatDuration = useFormatDuration()
  const { data, isLoading } = useSessionDetail(sessionId ?? '')

  if (isLoading || !data) {
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
          <CardTitle>{data.session.rootChannelName}</CardTitle>
        </CardHeader>
        <p className="mb-3 text-sm text-text-secondary">{data.session.guild.name}</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricTile label={t('sessionDetail.startedAt')} value={new Date(data.session.startedAt).toLocaleString()} />
          <MetricTile label={t('sessionDetail.endedAt')} value={new Date(data.session.endedAt).toLocaleString()} />
          <MetricTile label={t('sessionDetail.totalTalk')} value={formatDuration(data.session.totalTalkSeconds)} />
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('voice.timelineHeading')}</CardTitle>
        </CardHeader>
        {data.timeline.length === 0 ? (
          <EmptyState title={t('voice.noTimelineEvents')} />
        ) : (
          <ul className="space-y-1.5">
            {data.timeline.map((event) => (
              <li key={event.id} className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-3 py-2 text-sm">
                <span className="font-bold text-text-primary">{t(EVENT_TYPE_KEYS[event.event_type] ?? event.event_type)}</span>
                <span className="text-text-secondary">{event.user_name}</span>
                <span className="text-xs text-text-muted">{new Date(event.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
