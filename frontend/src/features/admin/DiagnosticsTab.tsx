import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Badge } from '../../components/Badge'
import { EmptyState } from '../../components/EmptyState'
import { useFormatDuration } from '../../hooks/useFormatDuration'
import { useAdminErrorLogs, useAdminGuildDetail, useAdminRecentSessions } from './useAdmin'

const LEVEL_TONE: Record<string, 'success' | 'warning' | 'danger' | 'neutral'> = {
  success: 'success',
  warning: 'warning',
  danger: 'danger',
  info: 'neutral',
}

export function DiagnosticsTab({ guildId }: { guildId: string }) {
  const { t } = useTranslation()
  const formatDuration = useFormatDuration()
  const { data: guildDetail } = useAdminGuildDetail(guildId)
  const { data: recentSessions } = useAdminRecentSessions()
  const { data: errorLogs } = useAdminErrorLogs(1)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('admin.diagnosticsHeading')}</CardTitle>
        </CardHeader>
        {!guildDetail || guildDetail.diagnostics.length === 0 ? (
          <EmptyState title={t('admin.diagnosticsEmpty')} />
        ) : (
          <div className="space-y-2">
            {guildDetail.diagnostics.map((item, index) => (
              <div key={index} className="flex items-start gap-3 rounded-icon bg-surface-sunken px-4 py-3">
                <Badge tone={LEVEL_TONE[item.level] ?? 'neutral'}>{item.level}</Badge>
                <div>
                  <p className="text-sm font-bold text-text-primary">{t(`admin.diag_${item.code}_title`)}</p>
                  <p className="text-xs text-text-secondary">{t(`admin.diag_${item.code}_message`)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('admin.recentSessionsHeading')}</CardTitle>
        </CardHeader>
        {!recentSessions || recentSessions.sessions.length === 0 ? (
          <EmptyState title={t('admin.recentSessionsEmpty')} />
        ) : (
          <div className="space-y-2">
            {recentSessions.sessions.map((session) => (
              <Link
                key={session.sessionId}
                to={`/dashboard/sessions/${session.sessionId}`}
                className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-4 py-3 transition-colors hover:bg-brand-tint"
              >
                <div>
                  <p className="text-sm font-bold text-text-primary">{session.guild.name}</p>
                  <p className="text-xs text-text-secondary">{session.rootChannelName}</p>
                </div>
                <span className="text-xs text-text-secondary">{formatDuration(session.totalTalkSeconds)}</span>
              </Link>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('nav.admin')}</CardTitle>
        </CardHeader>
        {!errorLogs || errorLogs.errorLogs.length === 0 ? (
          <EmptyState title={t('admin.errorLogsEmpty')} />
        ) : (
          <div className="space-y-2">
            {errorLogs.errorLogs.map((log, index) => (
              <div key={index} className="rounded-icon bg-surface-sunken px-4 py-3">
                <p className="text-sm font-bold text-text-primary">{log.source}</p>
                <p className="text-xs text-text-secondary">{log.message}</p>
                <p className="text-xs text-text-muted">{new Date(log.created_at).toLocaleString()}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
