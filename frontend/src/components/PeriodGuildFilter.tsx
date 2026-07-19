import { useTranslation } from 'react-i18next'
import { Select } from './Field'
import type { GuildIdentity } from '../features/voiceBoard/types'

export interface PeriodGuildFilterProps {
  period: string
  onPeriodChange: (value: string) => void
  guildId: string
  onGuildChange: (value: string) => void
  knownGuilds: GuildIdentity[]
}

export function PeriodGuildFilter({ period, onPeriodChange, guildId, onGuildChange, knownGuilds }: PeriodGuildFilterProps) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-wrap gap-3">
      <Select value={period} onChange={(event) => onPeriodChange(event.target.value)} className="max-w-[10rem]">
        <option value="day">{t('period.day')}</option>
        <option value="week">{t('period.week')}</option>
        <option value="month">{t('period.month')}</option>
        <option value="year">{t('period.year')}</option>
        <option value="all">{t('period.all')}</option>
      </Select>
      <Select value={guildId} onChange={(event) => onGuildChange(event.target.value)} className="max-w-[12rem]">
        <option value="">{t('period.allGuilds')}</option>
        {knownGuilds.map((guild) => (
          <option key={guild.id} value={guild.id}>
            {guild.name}
          </option>
        ))}
      </Select>
    </div>
  )
}
