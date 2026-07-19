import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Button } from '../../components/Button'
import { FieldLabel, Input, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useAdminGuildDetail, usePostRankingNow, useUpdateAdminGuildSettings } from './useAdmin'

const FREQUENCIES = [
  { value: 'daily', labelKey: 'reservations.repeatDaily' },
  { value: 'weekly', labelKey: 'reservations.repeatWeekly' },
  { value: 'monthly', labelKey: 'reservations.repeatMonthly' },
]

const TARGETS = [
  { value: 'top_talkers', labelKey: 'admin.targetTopTalkers' },
  { value: 'top_hosts', labelKey: 'admin.targetTopHosts' },
  { value: 'team_splits', labelKey: 'admin.targetTeamSplits' },
  { value: 'night_owls', labelKey: 'admin.targetNightOwls' },
]

export function RankingTab({ guildId }: { guildId: string }) {
  const { t } = useTranslation()
  const { show } = useToast()
  const { data } = useAdminGuildDetail(guildId)
  const updateGuildSettings = useUpdateAdminGuildSettings(guildId)
  const postNow = usePostRankingNow(guildId)

  const [enabled, setEnabled] = useState(false)
  const [channelId, setChannelId] = useState('')
  const [frequencies, setFrequencies] = useState<string[]>([])
  const [postTime, setPostTime] = useState('21:00')
  const [targets, setTargets] = useState<string[]>([])

  useEffect(() => {
    if (!data) return
    setEnabled(data.config.ranking_post_enabled)
    setChannelId(data.config.ranking_post_channel_id ? String(data.config.ranking_post_channel_id) : '')
    setFrequencies(data.config.ranking_post_frequencies)
    setPostTime(data.config.ranking_post_time)
    setTargets(data.config.ranking_post_targets)
  }, [data])

  if (!data) return null

  function toggle(list: string[], value: string, checked: boolean): string[] {
    return checked ? [...list, value] : list.filter((item) => item !== value)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateGuildSettings.mutate(
      {
        ranking_post_enabled: enabled,
        ranking_post_channel_id: channelId || null,
        ranking_post_frequencies: frequencies,
        ranking_post_time: postTime,
        ranking_post_targets: targets,
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
          <CardTitle>{t('admin.rankingPostHeading')}</CardTitle>
        </CardHeader>
        <form className="space-y-3" onSubmit={handleSubmit}>
          <label className="flex items-center gap-2 text-sm font-bold text-text-primary">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            {t('admin.rankingPostEnabled')}
          </label>
          <div>
            <FieldLabel htmlFor="ranking_channel">{t('admin.rankingPostChannel')}</FieldLabel>
            <Select id="ranking_channel" value={channelId} onChange={(event) => setChannelId(event.target.value)}>
              <option value="">{t('admin.selectChannel')}</option>
              {data.channels.text_channels.map((channel) => (
                <option key={channel.id} value={channel.id}>
                  {channel.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <FieldLabel htmlFor="ranking_frequency">{t('admin.rankingPostFrequency')}</FieldLabel>
            <div className="flex flex-wrap gap-3">
              {FREQUENCIES.map((freq) => (
                <label key={freq.value} className="flex items-center gap-1.5 text-sm text-text-secondary">
                  <input
                    type="checkbox"
                    checked={frequencies.includes(freq.value)}
                    onChange={(event) => setFrequencies((current) => toggle(current, freq.value, event.target.checked))}
                  />
                  {t(freq.labelKey)}
                </label>
              ))}
            </div>
          </div>
          <div>
            <FieldLabel htmlFor="ranking_time">{t('admin.rankingPostTime')}</FieldLabel>
            <Input id="ranking_time" type="time" value={postTime} onChange={(event) => setPostTime(event.target.value)} />
          </div>
          <div>
            <FieldLabel htmlFor="ranking_targets">{t('admin.rankingPostTargets')}</FieldLabel>
            <div className="flex flex-col gap-1.5">
              {TARGETS.map((target) => (
                <label key={target.value} className="flex items-center gap-1.5 text-sm text-text-secondary">
                  <input
                    type="checkbox"
                    checked={targets.includes(target.value)}
                    onChange={(event) => setTargets((current) => toggle(current, target.value, event.target.checked))}
                  />
                  {t(target.labelKey)}
                </label>
              ))}
            </div>
          </div>
          <Button type="submit" loading={updateGuildSettings.isPending}>
            {t('common.save')}
          </Button>
        </form>
      </Card>

      <Card>
        <Button
          variant="secondary"
          loading={postNow.isPending}
          onClick={() =>
            postNow.mutate(undefined, {
              onSuccess: (result) => show('success', t('common.save'), t(result.messageKey as never)),
              onError: (error) => show('danger', t('voice.saveError'), error.message),
            })
          }
        >
          {t('admin.postNow')}
        </Button>
      </Card>
    </div>
  )
}
