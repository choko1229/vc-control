import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/Button'
import { FieldLabel, Input } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useUpdateSettings } from './useVoiceSession'
import type { VoiceSession } from './types'

export function SettingsForm({ guildId, channelId, session }: { guildId: string; channelId: string; session: VoiceSession }) {
  const { t } = useTranslation()
  const { show } = useToast()
  const updateSettings = useUpdateSettings(guildId, channelId)
  const [name, setName] = useState(session.root_channel.name)
  const [userLimit, setUserLimit] = useState(String(session.root_channel.user_limit))
  const [bitrate, setBitrate] = useState(String(session.root_channel.bitrate))

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateSettings.mutate(
      { name, user_limit: Number(userLimit), bitrate: Number(bitrate) },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit}>
      <div>
        <FieldLabel htmlFor="vc-name">{t('voice.settingsName')}</FieldLabel>
        <Input id="vc-name" value={name} onChange={(event) => setName(event.target.value)} />
      </div>
      <div>
        <FieldLabel htmlFor="vc-limit">{t('voice.settingsLimit')}</FieldLabel>
        <Input id="vc-limit" type="number" min={0} max={99} value={userLimit} onChange={(event) => setUserLimit(event.target.value)} />
        <p className="mt-1 text-xs text-text-muted">{t('voice.settingsLimitHelp')}</p>
      </div>
      <div>
        <FieldLabel htmlFor="vc-bitrate">{t('voice.settingsBitrate')}</FieldLabel>
        <Input id="vc-bitrate" type="number" min={8000} value={bitrate} onChange={(event) => setBitrate(event.target.value)} />
      </div>
      <Button type="submit" loading={updateSettings.isPending}>
        {t('common.save')}
      </Button>
    </form>
  )
}
