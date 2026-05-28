import { cn } from '@/lib/utils'
import { getStatusColor } from '@/lib/utils'

interface BadgeProps {
  children: React.ReactNode
  className?: string
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'emergency'
  dot?: boolean
}

export function Badge({ children, className, variant, dot }: BadgeProps) {
  const colorMap: Record<string, string> = {
    default: 'bg-muted/20 text-muted-foreground border-border-light',
    success: 'bg-success/15 text-success border-success/25',
    warning: 'bg-warning/15 text-warning border-warning/25',
    error: 'bg-destructive/15 text-destructive border-destructive/25',
    info: 'bg-info/15 text-info border-info/25',
    emergency: 'bg-emergency/15 text-emergency border-emergency/25',
  }

  const dotMap: Record<string, string> = {
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-destructive',
    info: 'bg-info',
    emergency: 'bg-emergency',
    default: 'bg-muted',
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        variant ? colorMap[variant] : getStatusColor(String(children)),
        className
      )}
    >
      {dot && (
        <span className={cn('w-1.5 h-1.5 rounded-full', variant ? dotMap[variant] : 'bg-current')} />
      )}
      {children}
    </span>
  )
}

function safeString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && 'status' in value && typeof (value as Record<string, unknown>).status === 'string') {
    return (value as Record<string, unknown>).status as string
  }
  if (value && typeof value === 'object' && 'level' in value && typeof (value as Record<string, unknown>).level === 'string') {
    return (value as Record<string, unknown>).level as string
  }
  return fallback
}

export function EmergencyBadge({ level }: { level: unknown }) {
  const map: Record<string, { variant: 'emergency' | 'warning' | 'error' | 'success'; label: string }> = {
    critical: { variant: 'error', label: 'CRITICAL' },
    high: { variant: 'emergency', label: 'HIGH' },
    medium: { variant: 'warning', label: 'MEDIUM' },
    low: { variant: 'success', label: 'LOW' },
  }
  const s = safeString(level, '').toLowerCase()
  if (!s) return <Badge variant="default">Unknown</Badge>
  const { variant, label } = map[s] || { variant: 'default' as const, label: String(level) }
  return <Badge variant={variant} dot>{label}</Badge>
}

export function StatusBadge({ status }: { status: unknown }) {
  const map: Record<string, { variant: 'success' | 'warning' | 'error' | 'info'; label: string }> = {
    active: { variant: 'success', label: 'Active' },
    completed: { variant: 'success', label: 'Completed' },
    pending: { variant: 'warning', label: 'Pending' },
    processing: { variant: 'info', label: 'Processing' },
    failed: { variant: 'error', label: 'Failed' },
    approved: { variant: 'success', label: 'Approved' },
    rejected: { variant: 'error', label: 'Rejected' },
    matching: { variant: 'info', label: 'Matching' },
    submitted: { variant: 'info', label: 'Submitted' },
    healthy: { variant: 'success', label: 'Healthy' },
    busy: { variant: 'warning', label: 'Busy' },
    inactive: { variant: 'error', label: 'Inactive' },
    error: { variant: 'error', label: 'Error' },
  }
  const s = safeString(status, '').toLowerCase()
  if (!s) return <Badge variant="default">Unknown</Badge>
  const { variant, label } = map[s] || { variant: 'default' as const, label: String(status) }
  return <Badge variant={variant} dot>{label}</Badge>
}
