import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { PeriodGuildFilter } from '../../components/PeriodGuildFilter'
import { Avatar } from '../../components/Avatar'
import { Badge } from '../../components/Badge'
import { EmptyState } from '../../components/EmptyState'
import { Skeleton } from '../../components/Skeleton'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { useRankings, type RankingRow } from './useRankings'

function RankingRowView({ row }: { row: RankingRow }) {
  const formatDuration = useFormatDuration()
  return (
    <div className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-4 py-3">
      <div className="flex items-center gap-3">
        <Badge tone="brand">#{row.rank}</Badge>
        <Avatar name={row.user.display_name} imageUrl={row.user.avatar_url} size="xs" />
        <div>
          <p className="text-sm font-bold text-text-primary">{row.user.display_name}</p>
          <p className="text-xs text-text-secondary">{row.guild.name}</p>
        </div>
      </div>
      <span className="text-sm text-text-secondary">{formatDuration(row.talkSeconds)}</span>
    </div>
  )
}

export function RankingsPage() {
  const { t } = useTranslation()
  const [period, setPeriod] = useState('all')
  const [guildId, setGuildId] = useState('')
  const { data, isLoading } = useRankings(period, guildId)

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64" />
      </div>
    )
  }

  const allRows = [...data.topRankings, ...data.otherRankings]

  return (
    <div className="space-y-6">
      <PeriodGuildFilter period={period} onPeriodChange={setPeriod} guildId={guildId} onGuildChange={setGuildId} knownGuilds={data.knownGuilds} />
      <Card>
        <CardHeader>
          <CardTitle>{t('rankings.heading')}</CardTitle>
        </CardHeader>
        {allRows.length === 0 ? (
          <EmptyState title={t('rankings.empty')} />
        ) : (
          <div className="space-y-2">
            {allRows.map((row) => (
              <RankingRowView key={`${row.guild.id}-${row.user.id}`} row={row} />
            ))}
          </div>
        )}
        <p className="mt-3 text-xs text-text-muted">{t('rankings.excludeNote')}</p>
      </Card>
    </div>
  )
}
