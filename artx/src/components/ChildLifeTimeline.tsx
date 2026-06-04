import { useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  School, Stethoscope, AlertTriangle, Heart, Scale, Home, FileEdit,
  Clock, Shield, ShieldAlert, ShieldCheck,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TimelineEventV2 } from '@/services/foster'

export type EventType = TimelineEventV2['event_type']

export interface TimelineEvent extends TimelineEventV2 {}

export interface ChildLifeTimelineProps {
  childId: string
  events: TimelineEvent[]
  onEventClick?: (event: TimelineEvent) => void
  className?: string
}

const EVENT_ICONS: Record<string, { icon: React.ElementType; color: string; bg: string }> = {
  school:         { icon: School,         color: 'text-success',         bg: 'bg-success/10 border-success/30' },
  medical:        { icon: Stethoscope,    color: 'text-secondary',       bg: 'bg-secondary/10 border-secondary/30' },
  incident:       { icon: AlertTriangle,  color: 'text-destructive',     bg: 'bg-destructive/10 border-destructive/30' },
  visit:          { icon: Heart,          color: 'text-warning',         bg: 'bg-warning/10 border-warning/30' },
  legal:          { icon: Scale,          color: 'text-accent',          bg: 'bg-accent/10 border-accent/30' },
  placement:      { icon: Home,           color: 'text-info',            bg: 'bg-info/10 border-info/30' },
  note:           { icon: FileEdit,       color: 'text-muted-foreground', bg: 'bg-muted/10 border-muted/30' },
}

function getTheme(eventType: string) {
  const base = EVENT_ICONS[eventType]
  if (base) return base
  if (eventType.startsWith('placement') || eventType === 'placement_change') return EVENT_ICONS.placement
  if (eventType.startsWith('school')) return EVENT_ICONS.school
  if (eventType.startsWith('incident') || eventType === 'crisis_alert') return EVENT_ICONS.incident
  if (eventType.startsWith('medical') || eventType.startsWith('therapy')) return EVENT_ICONS.medical
  if (eventType.startsWith('visit') || eventType === 'family_visitation') return EVENT_ICONS.visit
  if (eventType.startsWith('legal') || eventType === 'court_date') return EVENT_ICONS.legal
  return EVENT_ICONS.note
}

function SeverityBadge({ severity }: { severity?: string | null }) {
  if (!severity || severity === 'low') return null
  const colors: Record<string, string> = {
    medium: 'bg-warning/10 text-warning border-warning/30',
    high: 'bg-destructive/10 text-destructive border-destructive/30',
    critical: 'bg-critical/10 text-critical border-critical/30',
  }
  const Icon = severity === 'medium' ? Shield : severity === 'high' ? ShieldAlert : ShieldCheck
  return (
    <span className={cn('inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-medium border', colors[severity] || '')}>
      <Icon className="w-2.5 h-2.5" />
      {severity}
    </span>
  )
}

function formatTimeAgo(iso: string): string {
  try {
    const ms = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(ms / 60000)
    if (mins < 1) return 'Just now'
    if (mins < 60) return `${mins}m ago`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h ago`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}d ago`
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true })
  } catch {
    return ''
  }
}

function formatDayLabel(iso: string): string {
  try {
    const d = new Date(iso)
    const today = new Date()
    const yesterday = new Date(today)
    yesterday.setDate(yesterday.getDate() - 1)

    if (d.toDateString() === today.toDateString()) return 'Today'
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'

    const diff = Math.floor((today.getTime() - d.getTime()) / 86400000)
    if (diff < 7) return `${diff} days ago`

    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return ''
  }
}

function groupByDay(events: TimelineEvent[]): [string, TimelineEvent[]][] {
  const map = new Map<string, TimelineEvent[]>()
  for (const ev of events) {
    const key = ev.event_date
    if (!map.has(key)) map.set(key, [])
    map.get(key)!.push(ev)
  }
  return Array.from(map.entries()).sort(([a], [b]) => b.localeCompare(a))
}

export function ChildLifeTimeline({ childId, events, onEventClick, className }: ChildLifeTimelineProps) {
  const grouped = useMemo(() => groupByDay(events), [events])

  return (
    <div className={cn('space-y-0', className)}>
      {grouped.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Clock className="w-10 h-10 text-muted-foreground/40 mb-3" />
          <p className="text-sm text-muted-foreground">No events to display.</p>
          <p className="text-xs text-muted-foreground/60 mt-1">
            Events will appear here as they are added.
          </p>
        </div>
      ) : (
        grouped.map(([day, dayEvents]) => (
          <div key={day} className="mb-4">
            <div className="sticky top-0 z-10 py-2 bg-background/90 backdrop-blur-xl">
              <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
                {formatDayLabel(day)}
              </h3>
            </div>
            <div className="space-y-1.5">
              {dayEvents.map((ev) => {
                const theme = getTheme(ev.event_type)
                const Icon = theme.icon
                return (
                  <motion.div
                    key={ev.id}
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={cn(
                      'flex items-start gap-3 p-3 rounded-xl border transition-colors cursor-pointer',
                      'border-border-light bg-glass hover:bg-glass-hover',
                    )}
                    onClick={() => onEventClick?.(ev)}
                  >
                    <div className={cn('flex items-center justify-center w-8 h-8 rounded-lg border shrink-0 mt-0.5', theme.bg)}>
                      <Icon className={cn('w-4 h-4', theme.color)} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-foreground truncate">
                          {ev.title || ev.event_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                        </span>
                        <SeverityBadge severity={ev.severity} />
                      </div>
                      {ev.description && (
                        <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{ev.description}</p>
                      )}
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="text-[10px] text-muted-foreground/60">
                          {formatTime(ev.recorded_at)}
                        </span>
                        <span className="text-[10px] text-muted-foreground/40">·</span>
                        <span className="text-[10px] text-muted-foreground/60">
                          {formatTimeAgo(ev.recorded_at)}
                        </span>
                      </div>
                    </div>
                  </motion.div>
                )
              })}
            </div>
          </div>
        ))
      )}
    </div>
  )
}
