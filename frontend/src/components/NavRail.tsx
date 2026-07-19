import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { cn } from '../lib/cn'

export interface NavRailItem {
  to: string
  label: string
  icon: ReactNode
}

export interface NavRailProps {
  items: NavRailItem[]
  footer?: ReactNode
}

export function NavRail({ items, footer }: NavRailProps) {
  return (
    <nav className="flex h-full w-[72px] flex-col items-center gap-1 border-r border-border bg-surface-panel py-4">
      <div className="mb-4 flex size-10 items-center justify-center rounded-icon bg-brand font-heading text-sm font-bold text-white">
        VC
      </div>
      <div className="flex flex-1 flex-col items-center gap-1">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              cn(
                'flex size-11 flex-col items-center justify-center rounded-icon text-lg transition-colors',
                isActive ? 'bg-brand-tint text-brand-dark' : 'text-text-secondary hover:bg-surface-sunken',
              )
            }
            title={item.label}
          >
            {item.icon}
          </NavLink>
        ))}
      </div>
      {footer}
    </nav>
  )
}
