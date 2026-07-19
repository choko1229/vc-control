import { Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../hooks/useAuth'
import { useRealtimeSocket } from '../../hooks/useRealtimeSocket'
import { NavRail } from '../../components/NavRail'
import { Skeleton } from '../../components/Skeleton'
import { Icon } from '../../components/Icon'

export function AppLayout() {
  const { t } = useTranslation()
  const { isLoading, isUnauthorized, isOwner, user } = useAuth()

  useRealtimeSocket(user ? ['global', `user:${user.id}`] : [])

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Skeleton className="h-10 w-40" />
      </div>
    )
  }

  if (isUnauthorized) {
    return <Navigate to="/login" replace />
  }

  const items = [
    { to: '/dashboard/me', label: t('nav.dashboard'), icon: <Icon name="home" /> },
    { to: '/dashboard/stats/me', label: t('nav.stats'), icon: <Icon name="bar_chart" /> },
    { to: '/dashboard/rankings', label: t('nav.rankings'), icon: <Icon name="emoji_events" /> },
    { to: '/dashboard/reservations', label: t('nav.reservations'), icon: <Icon name="event" /> },
    { to: '/dashboard/settings', label: t('nav.settings'), icon: <Icon name="settings" /> },
    ...(isOwner ? [{ to: '/admin', label: t('nav.admin'), icon: <Icon name="shield_person" /> }] : []),
  ]

  return (
    <div className="flex h-screen">
      <NavRail items={items} />
      <main className="flex-1 overflow-auto bg-surface-app p-6">
        <Outlet />
      </main>
    </div>
  )
}
