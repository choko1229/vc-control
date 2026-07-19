import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Button } from '../../components/Button'
import { FieldLabel, Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAdminGuildDetail, useUpdateAdminGuildSettings } from './useAdmin'

export function TeamNotifyTab({ guildId }: { guildId: string }) {
  const { t } = useTranslation()
  const { show } = useToast()
  const { data } = useAdminGuildDetail(guildId)
  const updateGuildSettings = useUpdateAdminGuildSettings(guildId)

  const [teamMode, setTeamMode] = useState('custom')
  const [teamNames, setTeamNames] = useState('')
  const [notificationChannelId, setNotificationChannelId] = useState('')

  useEffect(() => {
    if (!data) return
    setTeamMode(data.config.team_mode)
    setTeamNames(data.config.team_names.join(','))
    setNotificationChannelId(data.config.notification_channel_id ? String(data.config.notification_channel_id) : '')
  }, [data])

  if (!data) return null

  function handleTeamSubmit(event: FormEvent) {
    event.preventDefault()
    updateGuildSettings.mutate(
      { team_mode: teamMode, team_names: teamNames },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  function handleNotifySubmit(event: FormEvent) {
    event.preventDefault()
    updateGuildSettings.mutate(
      { notification_channel_id: notificationChannelId || null },
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
          <CardTitle>{t('admin.teamHeading')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleTeamSubmit}>
          <div>
            <FieldLabel htmlFor="team_mode">{t('admin.teamMode')}</FieldLabel>
            <Select id="team_mode" value={teamMode} onChange={(event) => setTeamMode(event.target.value)}>
              <option value="custom">{t('admin.teamModeCustom')}</option>
              <option value="fruit_random">{t('admin.teamModeFruit')}</option>
              <option value="cent">{t('admin.teamModeCent')}</option>
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="team_names">{t('admin.teamNames')}</FieldLabel>
            <Input id="team_names" value={teamNames} onChange={(event) => setTeamNames(event.target.value)} placeholder="A,B,C,D" />
          </div>
          <Button type="submit" loading={updateGuildSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('admin.notifyHeading')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleNotifySubmit}>
          <div>
            <FieldLabel htmlFor="notification_channel_id">{t('admin.notificationChannel')}</FieldLabel>
            <Select id="notification_channel_id" value={notificationChannelId} onChange={(event) => setNotificationChannelId(event.target.value)}>
              <option value="">{t('admin.selectChannel')}</option>
              {data.channels.text_channels.map((channel) => (
                <option key={channel.id} value={channel.id}>
                  {channel.name}
                </option>
              ))}
            </Select>
          </div>
          <Button type="submit" loading={updateGuildSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>
    </div>
  )
}
