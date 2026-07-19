import { cn } from '../lib/cn'

export interface TabItem {
  id: string
  label: string
}

export interface TabsProps {
  items: TabItem[]
  activeId: string
  onChange: (id: string) => void
  className?: string
}

export function Tabs({ items, activeId, onChange, className }: TabsProps) {
  return (
    <div className={cn('flex flex-wrap gap-1 rounded-pill bg-surface-sunken p-1', className)} role="tablist">
      {items.map((item) => {
        const active = item.id === activeId
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.id)}
            className={cn(
              'rounded-pill px-4 py-1.5 text-sm font-bold transition-colors',
              active ? 'bg-brand text-white shadow-soft' : 'text-text-secondary hover:text-text-primary',
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
