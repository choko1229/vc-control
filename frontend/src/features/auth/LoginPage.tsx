import { useTranslation } from 'react-i18next'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'

export function LoginPage() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-app px-4">
      <Card className="w-full max-w-sm text-center">
        <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-icon bg-brand font-heading text-lg font-bold text-white">
          VC
        </div>
        <h1 className="font-heading text-xl font-bold text-text-primary">{t('auth.loginTitle')}</h1>
        <p className="mt-2 text-sm text-text-secondary">{t('auth.loginSubtitle')}</p>
        <Button className="mt-6 w-full" onClick={() => (window.location.href = '/auth/login')}>
          {t('auth.loginButton')}
        </Button>
      </Card>
    </div>
  )
}
