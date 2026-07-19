import { cn } from '../lib/cn'

export interface AvatarProps {
  name: string
  imageUrl?: string | null
  size?: 'xs' | 'sm' | 'md'
  className?: string
}

const sizeStyles = {
  xs: 'size-6 text-[10px]',
  sm: 'size-9 text-xs',
  md: 'size-11 text-sm',
}

function initialsOf(name: string): string {
  const trimmed = name.trim()
  if (!trimmed) return '?'
  const parts = trimmed.split(/\s+/)
  if (parts.length === 1) return trimmed.slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function Avatar({ name, imageUrl, size = 'sm', className }: AvatarProps) {
  if (imageUrl) {
    return (
      <img
        src={imageUrl}
        alt={name}
        className={cn('shrink-0 rounded-icon object-cover', sizeStyles[size], className)}
      />
    )
  }
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center rounded-icon bg-brand font-heading font-bold text-white',
        sizeStyles[size],
        className,
      )}
      aria-hidden="true"
    >
      {initialsOf(name)}
    </span>
  )
}
