import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Button } from '../../components/Button'
import { FieldLabel, Input } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAdminSettings, useUpdateAdminSettings } from './useAdmin'

export function GlobalSettingsTab() {
  const { t } = useTranslation()
  const { show } = useToast()
  const { data } = useAdminSettings()
  const updateSettings = useUpdateAdminSettings()

  const [clientId, setClientId] = useState('')
  const [redirectUri, setRedirectUri] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [ownerUserId, setOwnerUserId] = useState('')
  const [dashboardHost, setDashboardHost] = useState('')
  const [dashboardPort, setDashboardPort] = useState('')
  const [retentionDays, setRetentionDays] = useState('90')

  useEffect(() => {
    if (!data) return
    setClientId(data.settings.client_id)
    setRedirectUri(data.settings.redirect_uri)
    setBaseUrl(data.settings.base_url)
    setOwnerUserId(data.settings.owner_user_id)
    setDashboardHost(data.settings.dashboard_host)
    setDashboardPort(data.settings.dashboard_port)
    setRetentionDays(data.settings.timeline_retention_days)
  }, [data])

  function handleCredentialsSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const body: Record<string, unknown> = {}
    const botToken = String(form.get('bot_token') ?? '')
    const clientSecret = String(form.get('client_secret') ?? '')
    if (botToken) body.bot_token = botToken
    if (clientSecret) body.client_secret = clientSecret
    updateSettings.mutate(body, {
      onSuccess: () => {
        show('success', t('common.save'), t('voice.saveSuccess'))
        event.currentTarget.reset()
      },
      onError: (error) => show('danger', t('voice.saveError'), error.message),
    })
  }

  function handleOAuthSubmit(event: FormEvent) {
    event.preventDefault()
    updateSettings.mutate(
      { client_id: clientId, redirect_uri: redirectUri, base_url: baseUrl },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  function handleRuntimeSubmit(event: FormEvent) {
    event.preventDefault()
    updateSettings.mutate(
      {
        owner_user_id: ownerUserId,
        dashboard_host: dashboardHost,
        dashboard_port: Number(dashboardPort),
        timeline_retention_days: Number(retentionDays),
      },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('admin.botCredentials')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleCredentialsSubmit}>
          <div>
            <FieldLabel htmlFor="bot_token">{t('admin.botToken')}</FieldLabel>
            <Input id="bot_token" name="bot_token" type="password" placeholder={t('admin.botTokenPlaceholder')} />
          </div>
          <div>
            <FieldLabel htmlFor="client_secret">{t('admin.clientSecret')}</FieldLabel>
            <Input id="client_secret" name="client_secret" type="password" placeholder={t('admin.botTokenPlaceholder')} />
          </div>
          <Button type="submit" loading={updateSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('admin.oauthHeading')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleOAuthSubmit}>
          <div>
            <FieldLabel htmlFor="client_id">{t('admin.clientId')}</FieldLabel>
            <Input id="client_id" value={clientId} onChange={(event) => setClientId(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="redirect_uri">{t('admin.redirectUri')}</FieldLabel>
            <Input id="redirect_uri" type="url" value={redirectUri} onChange={(event) => setRedirectUri(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="base_url">{t('admin.baseUrl')}</FieldLabel>
            <Input id="base_url" type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
          </div>
          <Button type="submit" loading={updateSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('admin.runtimeHeading')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleRuntimeSubmit}>
          <div>
            <FieldLabel htmlFor="owner_user_id">{t('admin.ownerUserId')}</FieldLabel>
            <Input id="owner_user_id" value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="dashboard_host">{t('admin.dashboardHost')}</FieldLabel>
            <Input id="dashboard_host" value={dashboardHost} onChange={(event) => setDashboardHost(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="dashboard_port">{t('admin.dashboardPort')}</FieldLabel>
            <Input id="dashboard_port" type="number" value={dashboardPort} onChange={(event) => setDashboardPort(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="retention_days">{t('admin.retentionDays')}</FieldLabel>
            <Input id="retention_days" type="number" min={1} value={retentionDays} onChange={(event) => setRetentionDays(event.target.value)} />
          </div>
          <Button type="submit" loading={updateSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>
    </div>
  )
}
