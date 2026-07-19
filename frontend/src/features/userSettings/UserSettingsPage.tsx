import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle } from '../../components/Card'
import { useTheme, type ThemePreference } from '../../hooks/useTheme'

const THEME_OPTIONS: { value: ThemePreference; labelKey: string }[] = [
  { value: 'dark', labelKey: 'userSettings.themeDark' },
  { value: 'light', labelKey: 'userSettings.themeLight' },
  { value: 'system', labelKey: 'userSettings.themeSystem' },
]

const LANGUAGE_OPTIONS: { value: string; labelKey: string }[] = [
  { value: 'ja', labelKey: 'userSettings.languageJa' },
  { value: 'en', labelKey: 'userSettings.languageEn' },
]

export function UserSettingsPage() {
  const { t, i18n } = useTranslation()
  const { preference, setPreference } = useTheme()

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t('userSettings.themeHeading')}</CardTitle>
        </CardHeader>
        <div className="space-y-2">
          {THEME_OPTIONS.map((option) => (
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

      <Card>
        <CardHeader>
          <CardTitle>{t('userSettings.languageHeading')}</CardTitle>
        </CardHeader>
        <div className="space-y-2">
          {LANGUAGE_OPTIONS.map((option) => (
            <label
              key={option.value}
              className="flex items-center gap-3 rounded-icon border border-border bg-surface-panel px-4 py-3 transition-colors hover:bg-surface-sunken"
            >
              <input
                type="radio"
                name="language"
                checked={i18n.resolvedLanguage === option.value}
                onChange={() => void i18n.changeLanguage(option.value)}
              />
              <span className="text-sm font-bold text-text-primary">{t(option.labelKey)}</span>
            </label>
          ))}
        </div>
      </Card>
    </div>
  )
}
