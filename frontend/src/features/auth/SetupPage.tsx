import { useState, type FormEvent, type InputHTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/Button'
import { Card } from '../../components/Card'
import { Input, FieldLabel } from '../../components/Field'
import { useToast } from '../../components/Toast'

function LabeledInput({ label, name, ...props }: { label: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <div>
      <FieldLabel htmlFor={name}>{label}</FieldLabel>
      <Input id={name} name={name} {...props} />
    </div>
  )
}

export function SetupPage() {
  const { t } = useTranslation()
  const { show } = useToast()
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    try {
      const formData = new FormData(event.currentTarget)
      const response = await fetch('/setup', { method: 'POST', body: formData })
      if (!response.ok) {
        const detail = await response.text()
        throw new Error(detail || response.statusText)
      }
      window.location.href = '/login?setup=1'
    } catch (error) {
      show('danger', t('auth.errorTitle'), error instanceof Error ? error.message : String(error))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-app px-4 py-10">
      <Card className="w-full max-w-lg">
        <h1 className="font-heading text-xl font-bold text-text-primary">{t('auth.setupTitle')}</h1>
        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <LabeledInput name="setup_password" label={t('auth.setupPassword')} type="password" required />
          <LabeledInput name="bot_token" label={t('auth.setupBotToken')} type="password" required />
          <LabeledInput name="client_id" label={t('auth.setupClientId')} required />
          <LabeledInput name="client_secret" label={t('auth.setupClientSecret')} type="password" required />
          <LabeledInput name="redirect_uri" label={t('auth.setupRedirectUri')} type="url" required />
          <LabeledInput name="base_url" label={t('auth.setupBaseUrl')} type="url" required />
          <LabeledInput name="owner_user_id" label={t('auth.setupOwnerUserId')} required />
          <LabeledInput name="dashboard_host" label={t('auth.setupDashboardHost')} defaultValue="0.0.0.0" required />
          <LabeledInput name="dashboard_port" label={t('auth.setupDashboardPort')} type="number" defaultValue="49162" required />
          <Button type="submit" loading={submitting} className="w-full">
            {t('common.save')}
          </Button>
        </form>
      </Card>
    </div>
  )
}
