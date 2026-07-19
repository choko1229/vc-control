import type { HTMLAttributes } from 'react'
import { cn } from '../lib/cn'

type Tone = 'neutral' | 'brand' | 'accent' | 'success' | 'warning' | 'danger'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
}

const toneStyles: Record<Tone, string> = {
  neutral: 'bg-surface-sunken text-text-secondary',
  brand: 'bg-brand-tint text-brand-dark',
  accent: 'bg-accent-tint text-accent-dark',
  success: 'bg-success/15 text-success',
  warning: 'bg-warning/15 text-warning',
  danger: 'bg-danger/15 text-danger',
}

export function Badge({ className, tone = 'neutral', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-pill px-3 py-1 text-xs font-bold',
        toneStyles[tone],
        className,
      )}
      {...props}
    />
  )
}
