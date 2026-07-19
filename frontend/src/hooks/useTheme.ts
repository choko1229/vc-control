import { useCallback, useEffect, useState } from 'react'

export type ThemePreference = 'dark' | 'light' | 'system'

const STORAGE_KEY = 'vc-control-theme-preference'

function resolveTheme(preference: ThemePreference): 'dark' | 'light' {
  if (preference === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return preference
}

function applyTheme(preference: ThemePreference) {
  document.documentElement.dataset.theme = resolveTheme(preference)
}

export function useTheme() {
  const [preference, setPreferenceState] = useState<ThemePreference>(() => {
    try {
      return (localStorage.getItem(STORAGE_KEY) as ThemePreference | null) ?? 'dark'
    } catch {
      return 'dark'
    }
  })

  useEffect(() => {
    applyTheme(preference)
    if (preference !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme(preference)
    media.addEventListener('change', handler)
    return () => media.removeEventListener('change', handler)
  }, [preference])

  const setPreference = useCallback((next: ThemePreference) => {
    setPreferenceState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* localStorage unavailable, ignore */
    }
  }, [])

  return { preference, resolvedTheme: resolveTheme(preference), setPreference }
}
