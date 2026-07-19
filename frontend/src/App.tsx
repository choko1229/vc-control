import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from './features/auth/LoginPage'
import { SetupPage } from './features/auth/SetupPage'
import { ErrorPage } from './features/auth/ErrorPage'
import { AppLayout } from './features/layout/AppLayout'
import { DashboardPage } from './features/dashboard/DashboardPage'
import { VoiceBoardPage } from './features/voiceBoard/VoiceBoardPage'
import { StatsPage } from './features/stats/StatsPage'
import { RankingsPage } from './features/rankings/RankingsPage'
import { ReservationsPage } from './features/reservations/ReservationsPage'
import { SessionDetailPage } from './features/sessionDetail/SessionDetailPage'
import { UserSettingsPage } from './features/userSettings/UserSettingsPage'
import { AdminPage } from './features/admin/AdminPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/error" element={<ErrorPage />} />
      <Route element={<AppLayout />}>
        <Route path="/dashboard/me" element={<DashboardPage />} />
        <Route path="/dashboard/voice/:guildId/:channelId" element={<VoiceBoardPage />} />
        <Route path="/dashboard/stats/me" element={<StatsPage />} />
        <Route path="/dashboard/rankings" element={<RankingsPage />} />
        <Route path="/dashboard/reservations" element={<ReservationsPage />} />
        <Route path="/dashboard/sessions/:sessionId" element={<SessionDetailPage />} />
        <Route path="/dashboard/settings" element={<UserSettingsPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="/" element={<Navigate to="/dashboard/me" replace />} />
      <Route path="*" element={<Navigate to="/dashboard/me" replace />} />
    </Routes>
  )
}
