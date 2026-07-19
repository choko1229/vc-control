import { useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { Button } from '../../components/Button'
import { FieldLabel, Input, Select, Textarea } from '../../components/Field'
import { EmptyState } from '../../components/EmptyState'
import { Skeleton } from '../../components/Skeleton'
import { useToast } from '../../components/Toast'
import {
  useCreateReservation,
  useCreateVoiceChannel,
  useDeleteReservation,
  useGuildConfigSummary,
  useMyAdminGuilds,
  useReservationChannels,
  useReservationMembers,
  useReservationsList,
} from './useReservations'

const WEEKDAY_KEYS = [
  'reservations.weekdayMon',
  'reservations.weekdayTue',
  'reservations.weekdayWed',
  'reservations.weekdayThu',
  'reservations.weekdayFri',
  'reservations.weekdaySat',
  'reservations.weekdaySun',
]

export function ReservationsPage() {
  const { t } = useTranslation()
  const { show } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const guildId = searchParams.get('guild_id') ?? ''

  const guilds = useMyAdminGuilds()
  const configSummary = useGuildConfigSummary(guildId)
  const channels = useReservationChannels(guildId)
  const members = useReservationMembers(guildId)
  const reservations = useReservationsList(guildId)
  const createVc = useCreateVoiceChannel(guildId)
  const createReservation = useCreateReservation(guildId)
  const deleteReservation = useDeleteReservation(guildId)

  const [vcType, setVcType] = useState('personal')
  const [repeatMode, setRepeatMode] = useState('none')
  const [repeatWeekdays, setRepeatWeekdays] = useState<number[]>([])
  const [mentionType, setMentionType] = useState('none')

  if (guilds.isLoading) return <Skeleton className="h-40" />

  if (!guilds.data || guilds.data.guilds.length === 0) {
    return <EmptyState title={t('reservations.noManageableServers')} />
  }

  if (!guildId) {
    setSearchParams({ guild_id: guilds.data.guilds[0].id })
    return null
  }

  function handleCreateVc(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createVc.mutate(
      {
        vc_type: vcType,
        owner_user_id: String(form.get('owner_user_id') ?? ''),
        vc_name: String(form.get('vc_name') ?? ''),
        user_limit: Number(form.get('user_limit') ?? 0),
        bitrate: Number(form.get('bitrate') ?? 0) || undefined,
        end_at: String(form.get('end_at') ?? '') || undefined,
        description: String(form.get('description') ?? ''),
      },
      {
        onSuccess: () => show('success', t('reservations.createSuccess'), t('reservations.createSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  function handleCreateReservation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    createReservation.mutate(
      {
        vc_name: String(form.get('vc_name') ?? ''),
        category_id: String(form.get('category_id') ?? '') || undefined,
        user_limit: Number(form.get('user_limit') ?? 0),
        bitrate: Number(form.get('bitrate') ?? 0) || undefined,
        description: String(form.get('description') ?? ''),
        start_at: String(form.get('start_at') ?? ''),
        end_at: String(form.get('end_at') ?? '') || undefined,
        repeat_mode: repeatMode,
        repeat_weekdays: repeatWeekdays,
        mention_type: mentionType,
        mention_targets: String(form.get('mention_targets') ?? '')
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => {
          show('success', t('reservations.createSuccess'), t('reservations.createSuccess'))
          event.currentTarget.reset()
        },
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  return (
    <div className="space-y-6">
      <Select value={guildId} onChange={(event) => setSearchParams({ guild_id: event.target.value })} className="max-w-xs">
        {guilds.data.guilds.map((guild) => (
          <option key={guild.id} value={guild.id}>
            {guild.name}
          </option>
        ))}
      </Select>

      {configSummary.data?.managedCategoryId ? (
        <Card>
          <CardHeader>
            <CardTitle>{t('reservations.createNowHeading')}</CardTitle>
          </CardHeader>
          <p className="mb-3 text-sm text-text-secondary">{t('reservations.createNowDesc')}</p>
          <form className="space-y-3" onSubmit={handleCreateVc}>
            <div>
              <FieldLabel htmlFor="vc_type">{t('reservations.vcType')}</FieldLabel>
              <Select id="vc_type" value={vcType} onChange={(event) => setVcType(event.target.value)}>
                <option value="personal">{t('reservations.vcTypePersonal')}</option>
                <option value="event">{t('reservations.vcTypeEvent')}</option>
              </Select>
            </div>
            {vcType === 'personal' ? (
              <div>
                <FieldLabel htmlFor="owner_user_id">{t('reservations.owner')}</FieldLabel>
                <Select id="owner_user_id" name="owner_user_id" defaultValue="">
                  <option value="">{t('reservations.selectUser')}</option>
                  {members.data?.members.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.name}
                    </option>
                  ))}
                </Select>
              </div>
            ) : null}
            <div>
              <FieldLabel htmlFor="vc_name_create">{t('reservations.vcName')}</FieldLabel>
              <Input id="vc_name_create" name="vc_name" placeholder={t('reservations.vcNamePlaceholder')} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <FieldLabel htmlFor="user_limit_create">{t('reservations.userLimit')}</FieldLabel>
                <Input id="user_limit_create" name="user_limit" type="number" min={0} max={99} />
              </div>
              <div>
                <FieldLabel htmlFor="bitrate_create">{t('reservations.bitrate')}</FieldLabel>
                <Input id="bitrate_create" name="bitrate" type="number" min={8000} />
              </div>
            </div>
            {vcType === 'event' ? (
              <div>
                <FieldLabel htmlFor="end_at_create">{t('reservations.endAt')}</FieldLabel>
                <Input id="end_at_create" name="end_at" type="datetime-local" required />
              </div>
            ) : null}
            <div>
              <FieldLabel htmlFor="description_create">{t('reservations.description')}</FieldLabel>
              <Textarea id="description_create" name="description" rows={3} />
            </div>
            <Button type="submit" loading={createVc.isPending}>
              {t('reservations.createVc')}
            </Button>
          </form>
        </Card>
      ) : (
        <EmptyState title={t('reservations.noCategoryConfigured')} description={t('reservations.noCategoryConfiguredDesc')} />
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t('reservations.newReservationHeading')}</CardTitle>
        </CardHeader>
        <p className="mb-3 text-sm text-text-secondary">{t('reservations.newReservationDesc')}</p>
        <form className="space-y-3" onSubmit={handleCreateReservation}>
          <div>
            <FieldLabel htmlFor="vc_name_res">{t('reservations.vcName')}</FieldLabel>
            <Input id="vc_name_res" name="vc_name" required />
          </div>
          <div>
            <FieldLabel htmlFor="category_id">{t('reservations.category')}</FieldLabel>
            <Select id="category_id" name="category_id" defaultValue="">
              <option value="">{t('reservations.noCategory')}</option>
              {channels.data?.categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="user_limit_res">{t('reservations.userLimit')}</FieldLabel>
              <Input id="user_limit_res" name="user_limit" type="number" min={0} max={99} />
            </div>
            <div>
              <FieldLabel htmlFor="bitrate_res">{t('reservations.bitrate')}</FieldLabel>
              <Input id="bitrate_res" name="bitrate" type="number" min={8000} />
            </div>
          </div>
          <div>
            <FieldLabel htmlFor="description_res">{t('reservations.description')}</FieldLabel>
            <Textarea id="description_res" name="description" rows={3} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <FieldLabel htmlFor="start_at">{t('reservations.startAt')}</FieldLabel>
              <Input id="start_at" name="start_at" type="datetime-local" required />
            </div>
            <div>
              <FieldLabel htmlFor="end_at_res">{t('reservations.endAt')}</FieldLabel>
              <Input id="end_at_res" name="end_at" type="datetime-local" />
            </div>
          </div>
          <div>
            <FieldLabel htmlFor="repeat_mode">{t('reservations.repeatMode')}</FieldLabel>
            <Select id="repeat_mode" value={repeatMode} onChange={(event) => setRepeatMode(event.target.value)}>
              <option value="none">{t('reservations.repeatNone')}</option>
              <option value="daily">{t('reservations.repeatDaily')}</option>
              <option value="weekly">{t('reservations.repeatWeekly')}</option>
              <option value="monthly">{t('reservations.repeatMonthly')}</option>
              <option value="weekdays">{t('reservations.repeatWeekdays')}</option>
            </Select>
            {repeatMode === 'weekdays' ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {WEEKDAY_KEYS.map((labelKey, index) => (
                  <label key={index} className="flex items-center gap-1 text-xs text-text-secondary">
                    <input
                      type="checkbox"
                      checked={repeatWeekdays.includes(index)}
                      onChange={(event) =>
                        setRepeatWeekdays((current) =>
                          event.target.checked ? [...current, index] : current.filter((day) => day !== index),
                        )
                      }
                    />
                    {t(labelKey)}
                  </label>
                ))}
              </div>
            ) : null}
          </div>
          <div>
            <FieldLabel htmlFor="mention_type">{t('reservations.mention')}</FieldLabel>
            <Select id="mention_type" value={mentionType} onChange={(event) => setMentionType(event.target.value)}>
              <option value="none">{t('reservations.mentionNone')}</option>
              <option value="user">{t('reservations.mentionUser')}</option>
              <option value="role">{t('reservations.mentionRole')}</option>
              <option value="everyone">{t('reservations.mentionEveryone')}</option>
              <option value="here">{t('reservations.mentionHere')}</option>
            </Select>
            {mentionType === 'user' || mentionType === 'role' ? (
              <Input name="mention_targets" placeholder={t('reservations.mentionTargetsPlaceholder')} className="mt-2" />
            ) : null}
          </div>
          <Button type="submit" loading={createReservation.isPending}>
            {t('reservations.createReservation')}
          </Button>
        </form>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t('reservations.listHeading')}</CardTitle>
        </CardHeader>
        {!reservations.data || reservations.data.reservations.length === 0 ? (
          <EmptyState title={t('reservations.listEmpty')} />
        ) : (
          <div className="space-y-2">
            {reservations.data.reservations.map((reservation) => (
              <ReservationRow
                key={reservation.id}
                reservation={reservation}
                onDelete={() =>
                  deleteReservation.mutate(reservation.id, {
                    onSuccess: () => show('success', t('reservations.deleteSuccess'), t('reservations.deleteSuccess')),
                    onError: (error) => show('danger', t('voice.saveError'), error.message),
                  })
                }
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

function ReservationRow({ reservation, onDelete }: { reservation: import('./useReservations').Reservation; onDelete: () => void }) {
  const { t } = useTranslation()
  const statusLabelKey: Record<string, string> = {
    pending: 'reservations.statusPending',
    active: 'reservations.statusActive',
    completed: 'reservations.statusCompleted',
  }
  return (
    <div className="flex items-center justify-between gap-3 rounded-icon bg-surface-sunken px-4 py-3">
      <div>
        <p className="text-sm font-bold text-text-primary">{reservation.vcName}</p>
        <p className="text-xs text-text-secondary">
          {t(statusLabelKey[reservation.status] ?? reservation.status)} / {reservation.repeatMode}
        </p>
      </div>
      <div className="text-right text-xs text-text-secondary">
        <p>{new Date(reservation.startAt).toLocaleString()}</p>
        <p>{reservation.endAt ? new Date(reservation.endAt).toLocaleString() : t('reservations.noEnd')}</p>
      </div>
      <Button variant="secondary" onClick={onDelete}>
        {t('common.delete')}
      </Button>
    </div>
  )
}
