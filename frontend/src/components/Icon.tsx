import { cn } from '../lib/cn'

export interface IconProps {
  name: string
  className?: string
  size?: number
  filled?: boolean
}

export function Icon({ name, className, size = 22, filled = false }: IconProps) {
  return (
    <span
      className={cn('material-symbols-outlined select-none leading-none', className)}
      style={{
        fontSize: size,
        fontVariationSettings: `'FILL' ${filled ? 1 : 0}, 'wght' 500, 'GRAD' 0, 'opsz' 24`,
      }}
      aria-hidden="true"
    >
      {name}
    </span>
  )
}
