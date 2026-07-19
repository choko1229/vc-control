import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../lib/cn'

type Tone = 'success' | 'warning' | 'danger' | 'info'

interface ToastItem {
  id: number
  tone: Tone
  title: string
  message: string
}

interface ToastContextValue {
  show: (tone: Tone, title: string, message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const toneStyles: Record<Tone, string> = {
  success: 'border-success/40 bg-success/10 text-success',
  warning: 'border-warning/40 bg-warning/10 text-warning',
  danger: 'border-danger/40 bg-danger/10 text-danger',
  info: 'border-brand/40 bg-brand-tint text-brand-dark',
}

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const show = useCallback((tone: Tone, title: string, message: string) => {
    const id = nextId++
    setToasts((current) => [...current, { id, tone, title, message }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, tone === 'danger' ? 4600 : 3600)
  }, [])

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      {createPortal(
        <div className="fixed right-4 top-4 z-50 flex w-full max-w-xs flex-col gap-2" aria-live="polite">
          {toasts.map((toast) => (
            <div
              key={toast.id}
              className={cn('rounded-icon border px-4 py-3 shadow-soft', toneStyles[toast.tone])}
            >
              <p className="font-heading text-sm font-bold">{toast.title}</p>
              <p className="text-sm">{toast.message}</p>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within a ToastProvider')
  return ctx
}
