import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Button } from '../../components/Button'
import { FieldLabel, Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAdminGuildDetail, useUpdateAdminGuildSettings } from './useAdmin'

export function VcSettingsTab({ guildId }: { guildId: string }) {
  const { t } = useTranslation()
  const { show } = useToast()
  const { data } = useAdminGuildDetail(guildId)
  const updateGuildSettings = useUpdateAdminGuildSettings(guildId)

  const [enabled, setEnabled] = useState(false)
  const [managedCategoryId, setManagedCategoryId] = useState('')
  const [baseVoiceChannelId, setBaseVoiceChannelId] = useState('')
  const [firstEmptyNoticeSec, setFirstEmptyNoticeSec] = useState('30')
  const [finalDeleteSec, setFinalDeleteSec] = useState('90')
  const [soloMode, setSoloMode] = useState('notify_only')
  const [soloNoticeAfterSec, setSoloNoticeAfterSec] = useState('3600')
  const [soloDeleteWarningAfterSec, setSoloDeleteWarningAfterSec] = useState('1800')
  const [soloRepeatNoticeSec, setSoloRepeatNoticeSec] = useState('3600')

  useEffect(() => {
    if (!data) return
    setEnabled(data.config.enabled)
    setManagedCategoryId(data.config.managed_category_id ? String(data.config.managed_category_id) : '')
    setBaseVoiceChannelId(data.config.base_voice_channel_id ? String(data.config.base_voice_channel_id) : '')
    setFirstEmptyNoticeSec(String(data.config.first_empty_notice_sec))
    setFinalDeleteSec(String(data.config.final_delete_sec))
    setSoloMode(data.config.solo_cleanup_mode)
    setSoloNoticeAfterSec(String(data.config.solo_notice_after_sec))
    setSoloDeleteWarningAfterSec(String(data.config.solo_delete_warning_after_sec))
    setSoloRepeatNoticeSec(String(data.config.solo_repeat_notice_sec))
  }, [data])

  if (!data) return null

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateGuildSettings.mutate(
      {
        enabled,
        managed_category_id: managedCategoryId || null,
        base_voice_channel_id: baseVoiceChannelId || null,
        first_empty_notice_sec: Number(firstEmptyNoticeSec),
        final_delete_sec: Number(finalDeleteSec),
        solo_cleanup_mode: soloMode,
        solo_notice_after_sec: Number(soloNoticeAfterSec),
        solo_delete_warning_after_sec: Number(soloDeleteWarningAfterSec),
        solo_repeat_notice_sec: Number(soloRepeatNoticeSec),
      },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('admin.basicStateHeading')}</CardTitle>
      </CardHeader>
      <form className="space-y-3" onSubmit={handleSubmit}>
        <label className="flex items-center gap-2 text-sm font-bold text-text-primary">
          <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          {t('admin.enabledLabel')}
        </label>
        <div>
          <FieldLabel htmlFor="managed_category_id">{t('admin.managedCategory')}</FieldLabel>
          <Select id="managed_category_id" value={managedCategoryId} onChange={(event) => setManagedCategoryId(event.target.value)}>
            <option value="">{t('admin.selectChannel')}</option>
            {data.channels.categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <FieldLabel htmlFor="base_voice_channel_id">{t('admin.baseVoiceChannel')}</FieldLabel>
          <Select id="base_voice_channel_id" value={baseVoiceChannelId} onChange={(event) => setBaseVoiceChannelId(event.target.value)}>
            <option value="">{t('admin.selectChannel')}</option>
            {data.channels.voice_channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <FieldLabel htmlFor="first_empty_notice_sec">{t('admin.firstEmptyNoticeSec')}</FieldLabel>
            <Input id="first_empty_notice_sec" type="number" value={firstEmptyNoticeSec} onChange={(event) => setFirstEmptyNoticeSec(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="final_delete_sec">{t('admin.finalDeleteSec')}</FieldLabel>
            <Input id="final_delete_sec" type="number" value={finalDeleteSec} onChange={(event) => setFinalDeleteSec(event.target.value)} />
          </div>
        </div>
        <div>
          <FieldLabel htmlFor="solo_cleanup_mode">{t('admin.soloCleanupMode')}</FieldLabel>
          <Select id="solo_cleanup_mode" value={soloMode} onChange={(event) => setSoloMode(event.target.value)}>
            <option value="notify_only">{t('admin.soloModeNotifyOnly')}</option>
            <option value="delete_warning">{t('admin.soloModeDeleteWarning')}</option>
            <option value="repeat_notice">{t('admin.soloModeRepeatNotice')}</option>
            <option value="disabled">{t('admin.soloModeDisabled')}</option>
          </Select>
        </div>
        <div>
          <FieldLabel htmlFor="solo_notice_after_sec">{t('admin.soloNoticeAfterSec')}</FieldLabel>
          <Input id="solo_notice_after_sec" type="number" min={60} value={soloNoticeAfterSec} onChange={(event) => setSoloNoticeAfterSec(event.target.value)} />
        </div>
        {soloMode === 'delete_warning' ? (
          <div>
            <FieldLabel htmlFor="solo_delete_warning_after_sec">{t('admin.soloDeleteWarningAfterSec')}</FieldLabel>
            <Input
              id="solo_delete_warning_after_sec"
              type="number"
              min={60}
              value={soloDeleteWarningAfterSec}
              onChange={(event) => setSoloDeleteWarningAfterSec(event.target.value)}
            />
          </div>
        ) : null}
        {soloMode === 'repeat_notice' ? (
          <div>
            <FieldLabel htmlFor="solo_repeat_notice_sec">{t('admin.soloRepeatNoticeSec')}</FieldLabel>
            <Input
              id="solo_repeat_notice_sec"
              type="number"
              min={300}
              value={soloRepeatNoticeSec}
              onChange={(event) => setSoloRepeatNoticeSec(event.target.value)}
            />
          </div>
        ) : null}
        <Button type="submit" loading={updateGuildSettings.isPending}>
          {t('common.save')}
        </Button>
      </form>
    </Card>
  )
}
