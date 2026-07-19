import type { HTMLAttributes } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { cn } from '../lib/cn'

export function ListRow({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-3 rounded-icon border border-border bg-surface-panel px-4 py-3',
        className,
      )}
      {...props}
    />
  )
}

export function ClickableListRow({ className, ...props }: LinkProps) {
  return (
    <Link
      className={cn(
        'flex items-center justify-between gap-3 rounded-icon border border-border bg-surface-panel px-4 py-3 transition-colors hover:bg-surface-sunken',
        className,
      )}
      {...props}
    />
  )
}
