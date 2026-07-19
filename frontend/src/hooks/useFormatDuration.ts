import { useTranslation } from 'react-i18next'

export function useFormatDuration() {
  const { t } = useTranslation()
  return (totalSeconds: number): string => {
    const value = Math.max(0, Math.floor(totalSeconds))
    const hours = Math.floor(value / 3600)
    const minutes = Math.floor((value % 3600) / 60)
    const seconds = Math.floor(value % 60)
    if (hours) return t('duration.hoursMinutes', { hours, minutes })
    if (minutes) return t('duration.minutesSeconds', { minutes, seconds })
    return t('duration.seconds', { seconds })
  }
}
