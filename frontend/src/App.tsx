import { Navigate, Route, Routes } from 'react-router-dom'
import { LoginPage } from './features/auth/LoginPage'
import { SetupPage } from './features/auth/SetupPage'
import { ErrorPage } from './features/auth/ErrorPage'
import { AppLayout } from './features/layout/AppLayout'
import { DashboardPage } from './features/dashboard/DashboardPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/error" element={<ErrorPage />} />
      <Route element={<AppLayout />}>
        <Route path="/dashboard/me" element={<DashboardPage />} />
      </Route>
      <Route path="/" element={<Navigate to="/dashboard/me" replace />} />
      <Route path="*" element={<Navigate to="/dashboard/me" replace />} />
    </Routes>
  )
}
