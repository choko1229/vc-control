import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../components/Button'
import { FieldLabel, Select } from '../../components/Field'
import { useToast } from '../../components/Toast'
import { useGuildMembers, useGuildRoles, useUpdateAccess } from './useVoiceSession'
import type { AccessMode, VoiceSession } from './types'

export function AccessForm({ guildId, channelId, session }: { guildId: string; channelId: string; session: VoiceSession }) {
  const { t } = useTranslation()
  const { show } = useToast()
  const updateAccess = useUpdateAccess(guildId, channelId)
  const [mode, setMode] = useState<AccessMode>(session.access_mode)
  const [invitedUserIds, setInvitedUserIds] = useState<string[]>(session.invited_user_ids)
  const [accessRoleIds, setAccessRoleIds] = useState<string[]>(session.access_role_ids)

  const members = useGuildMembers(guildId, mode === 'invite')
  const roles = useGuildRoles(guildId, mode === 'role')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updateAccess.mutate(
      { access_mode: mode, invited_user_ids: invitedUserIds, access_role_ids: accessRoleIds },
      {
        onSuccess: () => show('success', t('common.save'), t('voice.saveSuccess')),
        onError: (error) => show('danger', t('voice.saveError'), error.message),
      },
    )
  }

  function selectedOptions(select: HTMLSelectElement): string[] {
    return Array.from(select.selectedOptions).map((option) => option.value)
  }

  return (
    <form className="space-y-3" onSubmit={handleSubmit}>
      <div>
        <FieldLabel htmlFor="access-mode">{t('voice.accessMode')}</FieldLabel>
        <Select id="access-mode" value={mode} onChange={(event) => setMode(event.target.value as AccessMode)}>
          <option value="public">{t('voice.accessPublic')}</option>
          <option value="invite">{t('voice.accessInvite')}</option>
          <option value="role">{t('voice.accessRole')}</option>
        </Select>
      </div>
      {mode === 'invite' ? (
        <div>
          <FieldLabel htmlFor="access-users">{t('voice.accessInvitedUsers')}</FieldLabel>
          <Select
            id="access-users"
            multiple
            size={6}
            value={invitedUserIds}
            onChange={(event) => setInvitedUserIds(selectedOptions(event.target))}
          >
            {members.data?.members.map((member) => (
              <option key={member.id} value={member.id}>
                {member.name}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      {mode === 'role' ? (
        <div>
          <FieldLabel htmlFor="access-roles">{t('voice.accessAllowedRoles')}</FieldLabel>
          <Select
            id="access-roles"
            multiple
            size={6}
            value={accessRoleIds}
            onChange={(event) => setAccessRoleIds(selectedOptions(event.target))}
          >
            {roles.data?.roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
      <Button type="submit" loading={updateAccess.isPending}>
        {t('common.save')}
      </Button>
    </form>
  )
}
