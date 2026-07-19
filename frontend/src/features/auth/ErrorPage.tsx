import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'

export function ErrorPage() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const message = params.get('message') ?? ''

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-app px-4">
      <Card className="w-full max-w-sm text-center">
        <h1 className="font-heading text-xl font-bold text-danger">{t('auth.errorTitle')}</h1>
        {message ? <p className="mt-2 text-sm text-text-secondary">{message}</p> : null}
        <Button className="mt-6 w-full" onClick={() => (window.location.href = '/login')}>
          {t('nav.dashboard')}
        </Button>
      </Card>
    </div>
  )
}
