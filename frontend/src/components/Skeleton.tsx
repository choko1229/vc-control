import { cn } from '../lib/cn'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn('animate-pulse rounded-card bg-surface-sunken', className)}
      aria-hidden="true"
    />
  )
}
