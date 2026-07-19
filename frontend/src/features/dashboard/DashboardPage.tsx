import { useTranslation } from 'react-i18next'
import { useAuth } from '../../hooks/useAuth'
import { Card, CardHeader, CardTitle } from '../../components/Card'

export function DashboardPage() {
  const { t } = useTranslation()
  const { user } = useAuth()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('nav.dashboard')}</CardTitle>
      </CardHeader>
      <p className="text-sm text-text-secondary">
        {user ? `${user.displayName} でログイン中です。` : t('common.loading')}
      </p>
    </Card>
  )
}
