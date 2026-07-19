import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { useTheme, type ThemePreference } from '../../hooks/useTheme'

const OPTIONS: { value: ThemePreference; labelKey: string }[] = [
  { value: 'dark', labelKey: 'userSettings.themeDark' },
  { value: 'light', labelKey: 'userSettings.themeLight' },
  { value: 'system', labelKey: 'userSettings.themeSystem' },
]

export function UserSettingsPage() {
  const { t } = useTranslation()
  const { preference, setPreference } = useTheme()

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('userSettings.themeHeading')}</CardTitle>
      </CardHeader>
      <div className="space-y-2">
        {OPTIONS.map((option) => (
          <label
            key={option.value}
            className="flex items-center gap-3 rounded-icon border border-border bg-surface-panel px-4 py-3 transition-colors hover:bg-surface-sunken"
          >
            <input
              type="radio"
              name="theme"
              checked={preference === option.value}
              onChange={() => setPreference(option.value)}
            />
            <span className="text-sm font-bold text-text-primary">{t(option.labelKey)}</span>
          </label>
        ))}
      </div>
    </Card>
  )
}
