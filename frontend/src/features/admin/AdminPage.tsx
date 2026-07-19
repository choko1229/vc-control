import { useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Tabs } from '../../components/Tabs'
import { Select } from '../../components/Field'
import { Skeleton } from '../../components/Skeleton'
import { useAuth } from '../../hooks/useAuth'
import { useAdminGuilds } from './useAdmin'
import { GlobalSettingsTab } from './GlobalSettingsTab'
import { VcSettingsTab } from './VcSettingsTab'
import { TeamNotifyTab } from './TeamNotifyTab'
import { RankingTab } from './RankingTab'
import { DiagnosticsTab } from './DiagnosticsTab'

export function AdminPage() {
  const { t } = useTranslation()
  const { isOwner } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const guildId = searchParams.get('guild_id') ?? ''
  const [activeTab, setActiveTab] = useState('global')
  const { data: guilds, isLoading } = useAdminGuilds()

  if (!isOwner) return <Navigate to="/dashboard/me" replace />
  if (isLoading) return <Skeleton className="h-40" />

  const tabs = [
    { id: 'global', label: t('admin.tabGlobal') },
    { id: 'vc', label: t('admin.tabVc') },
    { id: 'team-notify', label: t('admin.tabTeamNotify') },
    { id: 'ranking', label: t('admin.tabRanking') },
    { id: 'diagnostics', label: t('admin.tabDiagnostics') },
  ]

  const effectiveGuildId = guildId || guilds?.guilds[0]?.id || ''

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Select
          value={effectiveGuildId}
          onChange={(event) => setSearchParams({ guild_id: event.target.value })}
          className="max-w-xs"
        >
          {guilds?.guilds.map((guild) => (
            <option key={guild.id} value={guild.id}>
              {guild.name}
            </option>
          ))}
        </Select>
        <Tabs items={tabs} activeId={activeTab} onChange={setActiveTab} />
      </div>

      {activeTab === 'global' ? <GlobalSettingsTab /> : null}
      {activeTab === 'vc' && effectiveGuildId ? <VcSettingsTab guildId={effectiveGuildId} /> : null}
      {activeTab === 'team-notify' && effectiveGuildId ? <TeamNotifyTab guildId={effectiveGuildId} /> : null}
      {activeTab === 'ranking' && effectiveGuildId ? <RankingTab guildId={effectiveGuildId} /> : null}
      {activeTab === 'diagnostics' && effectiveGuildId ? <DiagnosticsTab guildId={effectiveGuildId} /> : null}
    </div>
  )
}
