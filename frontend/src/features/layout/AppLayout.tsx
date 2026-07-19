import { Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../../hooks/useAuth'
import { NavRail } from '../../components/NavRail'
import { Skeleton } from '../../components/Skeleton'

export function AppLayout() {
  const { t } = useTranslation()
  const { isLoading, isUnauthorized, isOwner } = useAuth()

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
    { to: '/dashboard/me', label: t('nav.dashboard'), icon: <span aria-hidden="true">⌂</span> },
    { to: '/dashboard/stats/me', label: t('nav.stats'), icon: <span aria-hidden="true">▤</span> },
    { to: '/dashboard/rankings', label: t('nav.rankings'), icon: <span aria-hidden="true">#</span> },
    { to: '/dashboard/reservations', label: t('nav.reservations'), icon: <span aria-hidden="true">📅</span> },
    { to: '/dashboard/settings', label: t('nav.settings'), icon: <span aria-hidden="true">⚙</span> },
    ...(isOwner ? [{ to: '/admin', label: t('nav.admin'), icon: <span aria-hidden="true">◇</span> }] : []),
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
