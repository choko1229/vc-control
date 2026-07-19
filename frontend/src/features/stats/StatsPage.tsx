import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { MetricTile } from '../../components/MetricTile'
import { PeriodGuildFilter } from '../../components/PeriodGuildFilter'
import { Skeleton } from '../../components/Skeleton'
import { EmptyState } from '../../components/EmptyState'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { useStats } from './useStats'

export function StatsPage() {
  const { t } = useTranslation()
  const formatDuration = useFormatDuration()
  const [period, setPeriod] = useState('all')
  const [guildId, setGuildId] = useState('')
  const { data, isLoading } = useStats(period, guildId)

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PeriodGuildFilter period={period} onPeriodChange={setPeriod} guildId={guildId} onGuildChange={setGuildId} knownGuilds={data.knownGuilds} />

      <Card>
        <CardHeader>
          <CardTitle>{t('dashboard.summaryHeading')}</CardTitle>
        </CardHeader>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <MetricTile label={t('dashboard.talkSeconds')} value={formatDuration(data.summary.talkSeconds)} />
          <MetricTile label={t('dashboard.afkSeconds')} value={formatDuration(data.summary.afkSeconds)} />
          <MetricTile label={t('dashboard.effectiveSeconds')} value={formatDuration(data.summary.effectiveSeconds)} />
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('stats.ratioHeading')}</CardTitle>
        </CardHeader>
        <div className="flex items-center gap-4">
          <div
            className="size-24 shrink-0 rounded-full"
            style={{
              background: `conic-gradient(var(--color-brand) 0% ${data.talkRatio.effectivePercent}%, var(--color-surface-sunken) ${data.talkRatio.effectivePercent}% 100%)`,
            }}
          />
          <div className="text-sm text-text-secondary">
            <p className="font-heading font-bold text-text-primary">{data.talkRatio.effectivePercent}%</p>
            <p>{t('dashboard.effectiveSeconds')}</p>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('stats.dailyChartHeading')}</CardTitle>
        </CardHeader>
        {data.dailyChart.length === 0 ? (
          <EmptyState title={t('stats.noData')} />
        ) : (
          <div className="space-y-2">
            {data.dailyChart.map((row) => (
              <div key={row.date} className="flex items-center gap-3 text-sm">
                <span className="w-20 shrink-0 text-text-secondary">{row.date}</span>
                <div className="h-3 flex-1 overflow-hidden rounded-pill bg-surface-sunken">
                  <div className="h-full rounded-pill bg-brand" style={{ width: `${row.widthPercent}%` }} />
                </div>
                <span className="w-24 shrink-0 text-right text-text-secondary">{formatDuration(row.talkSeconds)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('stats.heatmapHeading')}</CardTitle>
        </CardHeader>
        <div className="grid grid-cols-6 gap-2">
          {data.hourlyHeatmap.map((slot) => (
            <div
              key={slot.hour}
              className="flex aspect-square items-center justify-center rounded-icon text-xs font-bold text-text-primary"
              style={{ backgroundColor: `rgba(59, 130, 246, ${slot.alpha})` }}
              title={formatDuration(slot.talkSeconds)}
            >
              {String(slot.hour).padStart(2, '0')}
            </div>
          ))}
        </div>
      </Card>

      {data.breakdown.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('stats.serverBreakdownHeading')}</CardTitle>
          </CardHeader>
          <div className="space-y-2">
            {data.breakdown.map((row) => (
              <div key={row.guild.id} className="flex items-center justify-between rounded-icon bg-surface-sunken px-4 py-3">
                <span className="text-sm font-bold text-text-primary">{row.guild.name}</span>
                <span className="text-sm text-text-secondary">{formatDuration(row.talkSeconds)}</span>
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
