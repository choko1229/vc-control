import { cn } from '../lib/cn'

export interface MetricTileProps {
  label: string
  value: string
  className?: string
}

export function MetricTile({ label, value, className }: MetricTileProps) {
  return (
    <div className={cn('rounded-card bg-surface-sunken p-4', className)}>
      <div className="text-xs font-bold text-text-secondary">{label}</div>
      <div className="mt-1 font-heading text-2xl font-bold text-text-primary">{value}</div>
    </div>
  )
}
