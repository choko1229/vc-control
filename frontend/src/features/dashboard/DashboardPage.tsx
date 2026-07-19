import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { MetricTile } from '../../components/MetricTile'
import { ClickableListRow } from '../../components/ListRow'
import { Avatar } from '../../components/Avatar'
import { Badge } from '../../components/Badge'
import { EmptyState } from '../../components/EmptyState'
import { Skeleton } from '../../components/Skeleton'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { useDashboard } from './useDashboard'

function elapsedSeconds(startedAt: string): number {
  return Math.max(0, (Date.now() - new Date(startedAt).getTime()) / 1000)
}

export function DashboardPage() {
  const { t } = useTranslation()
  const formatDuration = useFormatDuration()
  const { data, isLoading } = useDashboard()

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  const effectiveSeconds = Math.max(0, data.summary.talkSeconds - data.summary.afkSeconds)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('dashboard.summaryHeading')}</CardTitle>
        </CardHeader>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricTile label={t('dashboard.talkSeconds')} value={formatDuration(data.summary.talkSeconds)} />
          <MetricTile label={t('dashboard.afkSeconds')} value={formatDuration(data.summary.afkSeconds)} />
          <MetricTile label={t('dashboard.effectiveSeconds')} value={formatDuration(effectiveSeconds)} />
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('dashboard.liveSessionsHeading')}</CardTitle>
        </CardHeader>
        {data.sessions.length === 0 ? (
          <EmptyState title={t('dashboard.liveSessionsEmpty')} description={t('dashboard.liveSessionsEmptyDesc')} />
        ) : (
          <div className="space-y-2">
            {data.sessions.map((session) => (
              <ClickableListRow
                key={session.sessionId}
                to={`/dashboard/voice/${session.guild.id}/${session.rootChannelId}`}
              >
                <div className="flex items-center gap-3">
                  <Avatar name={session.guild.name} imageUrl={session.guild.icon_url} />
                  <div>
                    <p className="font-heading text-sm font-bold text-text-primary">{session.rootChannelName}</p>
                    <p className="text-xs text-text-secondary">{session.guild.name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge tone={session.canEdit ? 'success' : 'neutral'}>
                    {session.canEdit ? t('dashboard.canEdit') : t('dashboard.viewOnly')}
                  </Badge>
                  <Badge tone="neutral">{t('dashboard.participants', { count: session.activeParticipantCount })}</Badge>
                  <span className="text-xs text-text-muted">{formatDuration(elapsedSeconds(session.startedAt))}</span>
                </div>
              </ClickableListRow>
            ))}
          </div>
        )}
      </Card>

      {data.guildBreakdown.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.guildBreakdownHeading')}</CardTitle>
          </CardHeader>
          <div className="space-y-2">
            {data.guildBreakdown.map((row) => (
              <div key={row.guild.id} className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-4 py-3">
                <div className="flex items-center gap-3">
                  <Avatar name={row.guild.name} imageUrl={row.guild.icon_url} size="xs" />
                  <span className="text-sm font-bold text-text-primary">{row.guild.name}</span>
                </div>
                <span className="text-sm text-text-secondary">{formatDuration(row.talkSeconds)}</span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
