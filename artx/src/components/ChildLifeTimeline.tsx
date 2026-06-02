/**
 * ChildLifeTimeline – vertical chronological timeline of a child's complete
 * foster care history.
 *
 * Features:
 *   • Single vertical scroll with sticky month/year dividers
 *   • Colour-coded event types (placement, school, incident, legal, contact, …)
 *   • Compact / detailed view modes
 *   • Filter bar to toggle event type visibility
 *   • 30‑day correlation highlighting on event click
 *   • ARIA feed pattern with screen‑reader support for sealed/confidential events
 *   • Keyboard navigation (↑↓, Enter, Home/End, Ctrl+Shift+E)
 *
 * Design spec: docs/child_life_timeline_visual_design.md (Step 2)
 * Data model:  child_life_events table (Step 1)
 */
import {
  useCallback, useMemo, useState, useRef, useEffect,
} from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Calendar,
  DoorOpen, DoorClosed, ArrowRightLeft,
  GraduationCap,
  AlertTriangle,
  Scale, Gavel,
  Heart,
  Users,
  Stethoscope, Brain,
  Activity, TrendingUp,
  UserCog,
  Star,
  FileEdit,
  ChevronDown,
  Lock,
  Filter,
  Download,
  Printer,
  X,
} from 'lucide-react'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// ─── Types ───────────────────────────────────────────────────────────

export type EventType =
  | 'placement_start'
  | 'placement_end'
  | 'placement_change'
  | 'school_change'
  | 'incident_report'
  | 'court_date'
  | 'legal_milestone'
  | 'medical_appointment'
  | 'therapy_session'
  | 'sibling_contact'
  | 'family_visitation'
  | 'milestone'
  | 'crisis_alert'
  | 'drift_threshold'
  | 'prediction_feedback'
  | 'twin_simulation'
  | 'caseworker_assignment'
  | 'caseworker_change'
  | 'manual_entry'

export type EventSeverity = 'low' | 'medium' | 'high' | 'critical'

export type EventSealLevel = 'none' | 'partial' | 'full'

interface EventPayload {
  [key: string]: unknown
}

export interface TimelineEvent {
  id: number
  child_id: string
  event_type: EventType
  event_date: string          // ISO date
  event_time?: string         // ISO time, optional
  recorded_at: string         // ISO datetime
  source_table?: string
  source_id?: number
  conflict_resolution?: string
  payload: EventPayload
  is_verified: boolean
  verified_by?: string
  verified_at?: string
  superseded_by?: number
  seal_level: EventSealLevel
}

// ─── Props ───────────────────────────────────────────────────────────

export interface ChildLifeTimelineProps {
  childId: string
  events: TimelineEvent[]
  viewMode: 'compact' | 'detailed'
  onEventClick: (event: TimelineEvent) => void
  className?: string
}

// ─── Constants ───────────────────────────────────────────────────────

type EventTheme = {
  dotShape: string          // SVG path for the dot
  dotClass: string          // Tailwind bg + border classes
  borderClass: string       // border-l-{color} for card accent
  icon: React.ElementType
  iconClass: string
  label: string
}

const EVENT_THEMES: Record<EventType, EventTheme> = {
  placement_start:      { dotShape: 'M6 2v8M2 6h8',        dotClass: 'bg-info border-info',              borderClass: 'border-l-info',              icon: DoorOpen,       iconClass: 'text-info',       label: 'Placement' },
  placement_end:        { dotShape: 'M2 2l8 8M10 2l-8 8', dotClass: 'bg-info border-info',              borderClass: 'border-l-info',              icon: DoorClosed,     iconClass: 'text-info',       label: 'Placement' },
  placement_change:     { dotShape: 'M2 6h8M6 2v8',        dotClass: 'bg-info border-info',              borderClass: 'border-l-info',              icon: ArrowRightLeft, iconClass: 'text-info',       label: 'Placement' },
  school_change:        { dotShape: 'M6 10V2l4 2-4 2v4',   dotClass: 'bg-success border-success',         borderClass: 'border-l-success',            icon: GraduationCap,  iconClass: 'text-success',    label: 'School' },
  incident_report:      { dotShape: 'M6 2v5M6 9v1',        dotClass: 'bg-destructive border-destructive',  borderClass: 'border-l-destructive',        icon: AlertTriangle,  iconClass: 'text-destructive', label: 'Incident' },
  court_date:           { dotShape: 'M4 10V2h4v8M2 6h8',   dotClass: 'bg-accent border-accent',           borderClass: 'border-l-accent',             icon: Scale,          iconClass: 'text-accent',     label: 'Court' },
  legal_milestone:      { dotShape: 'M6 2L2 6l4 4 4-4z',   dotClass: 'bg-accent border-accent',           borderClass: 'border-l-accent',             icon: Gavel,          iconClass: 'text-accent',     label: 'Legal' },
  medical_appointment:  { dotShape: 'M10 2v8M2 6h8',        dotClass: 'bg-secondary border-secondary',      borderClass: 'border-l-secondary',          icon: Stethoscope,    iconClass: 'text-secondary',  label: 'Medical' },
  therapy_session:      { dotShape: 'M3 3l6 6M9 3l-6 6',   dotClass: 'bg-secondary border-secondary',      borderClass: 'border-l-secondary',          icon: Brain,          iconClass: 'text-secondary',  label: 'Therapy' },
  sibling_contact:      { dotShape: 'M2 6a4 4 0 018 0',     dotClass: 'bg-emergency border-emergency',      borderClass: 'border-l-emergency',          icon: Users,          iconClass: 'text-emergency',  label: 'Sibling' },
  family_visitation:    { dotShape: 'M6 2v8M2 6h8',        dotClass: 'bg-warning border-warning',          borderClass: 'border-l-warning',            icon: Heart,          iconClass: 'text-warning',    label: 'Visit' },
  milestone:            { dotShape: '',                     dotClass: 'border-success border-2 bg-transparent', borderClass: 'border-l-success/40',     icon: Star,           iconClass: 'text-success/60', label: 'Milestone' },
  crisis_alert:         { dotShape: 'M6 2v4M6 8v1',        dotClass: 'bg-critical border-critical',         borderClass: 'border-l-critical',           icon: Activity,       iconClass: 'text-critical',   label: 'Crisis' },
  drift_threshold:      { dotShape: 'M2 8l3-3 2 2 3-3',    dotClass: 'bg-critical border-critical',         borderClass: 'border-l-critical',           icon: TrendingUp,     iconClass: 'text-critical',   label: 'Drift' },
  prediction_feedback:  { dotShape: 'M2 6h8M6 2v8',        dotClass: 'bg-info border-info',              borderClass: 'border-l-info',              icon: Activity,       iconClass: 'text-info',       label: 'Feedback' },
  twin_simulation:      { dotShape: 'M2 6a4 4 0 016 0',    dotClass: 'bg-critical border-critical',         borderClass: 'border-l-critical',           icon: TrendingUp,     iconClass: 'text-critical',   label: 'Simulation' },
  caseworker_assignment: { dotShape: 'M6 2v8M2 6h8',       dotClass: 'bg-primary border-primary',           borderClass: 'border-l-primary',            icon: UserCog,        iconClass: 'text-primary',    label: 'Caseworker' },
  caseworker_change:    { dotShape: 'M2 2l8 8M10 2l-8 8',  dotClass: 'bg-primary border-primary',           borderClass: 'border-l-primary',            icon: UserCog,        iconClass: 'text-primary',    label: 'Caseworker' },
  manual_entry:         { dotShape: 'M2 4h8M2 8h6M2 12h4', dotClass: 'bg-muted border-muted',              borderClass: 'border-l-muted',              icon: FileEdit,       iconClass: 'text-muted',      label: 'Manual' },
}

const EVENT_GROUPS: { key: string; types: EventType[]; label: string; order: number }[] = [
  { key: 'placement', types: ['placement_start', 'placement_end', 'placement_change'],                 label: 'Placements',    order: 0 },
  { key: 'school',    types: ['school_change'],                                                         label: 'School',        order: 1 },
  { key: 'incident',  types: ['incident_report'],                                                       label: 'Incidents',     order: 2 },
  { key: 'legal',     types: ['court_date', 'legal_milestone'],                                         label: 'Legal',         order: 3 },
  { key: 'medical',   types: ['medical_appointment', 'therapy_session'],                                label: 'Medical',       order: 4 },
  { key: 'contact',   types: ['sibling_contact', 'family_visitation'],                                  label: 'Contact',       order: 5 },
  { key: 'ml',        types: ['crisis_alert', 'drift_threshold', 'prediction_feedback', 'twin_simulation'], label: 'ML/AI',   order: 6 },
  { key: 'caseworker', types: ['caseworker_assignment', 'caseworker_change'],                           label: 'Caseworkers',   order: 7 },
  { key: 'milestone',  types: ['milestone'],                                                             label: 'Milestones',    order: 8 },
  { key: 'manual',     types: ['manual_entry'],                                                          label: 'Manual',        order: 9 },
]

function groupKeyForType(t: EventType): string {
  return EVENT_GROUPS.find(g => g.types.includes(t))?.key ?? 'manual'
}

// ─── Helpers ─────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(iso))
  } catch { return iso }
}

function formatMonth(iso: string): string {
  try {
    return new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(new Date(iso))
  } catch { return iso }
}

function formatMonthKey(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  } catch { return iso }
}

function isWithinWindow(target: Date, candidate: Date, days: number): boolean {
  const diff = Math.abs(target.getTime() - candidate.getTime())
  return diff <= days * 86_400_000
}

function daysBetween(a: Date, b: Date): number {
  return Math.round(Math.abs(a.getTime() - b.getTime()) / 86_400_000)
}

/** Build an SVG path for the dot shape based on the event theme. */
function DotShape({ path, className }: { path: string; className?: string }) {
  if (!path) return <div className={cn('w-2.5 h-2.5 rounded-full border', className)} />
  return (
    <svg viewBox="0 0 12 12" className={cn('w-3 h-3', className)} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  )
}

/** Build a plain‑English label for an event's payload summary. */
function eventPayloadSummary(event: TimelineEvent): string {
  const p = event.payload
  switch (event.event_type) {
    case 'placement_start':
    case 'placement_end':
    case 'placement_change':
      return [p.family_name, p.change_reason, p.outcome].filter(Boolean).join(' · ')
    case 'school_change':
      return [p.school_name, `Grade ${p.grade}`, p.reason_code].filter(Boolean).join(' · ')
    case 'incident_report':
      return `${p.incident_type} — Severity: ${p.severity}`
    case 'court_date':
      return [p.court_type, p.outcome].filter(Boolean).join(' — ')
    case 'family_visitation':
      return `${p.visit_type} — ${p.occurred ? `${p.actual_duration_minutes ?? p.scheduled_duration_minutes} min` : 'Cancelled'}`
    case 'sibling_contact':
      return `${p.contact_type} — ${p.missed ? 'Missed' : `${p.duration_minutes} min`}`
    case 'crisis_alert':
      return `Risk ${p.risk_score}% — ${p.risk_level}`
    case 'drift_threshold':
      return `Drift ${p.drift_score} — ${p.trend_direction}`
    case 'caseworker_change':
      return `${p.previous_name ?? p.previous_caseworker_id} → ${p.new_name ?? p.new_caseworker_id}`
    case 'caseworker_assignment':
      return p.caseworker_name ?? p.caseworker_id
    case 'medical_appointment':
      return `${p.appointment_type} — ${p.provider_name ?? 'Provider not recorded'}`
    case 'therapy_session':
      return `${p.therapy_type} — ${p.attendance}`
    case 'milestone':
      return p.title ?? 'Milestone'
    default:
      return ''
  }
}

// ─── Sub‑components ──────────────────────────────────────────────────

/** The dot + connector‑line track on the left side of each row. */
function EventDot({ type, highlighted, dimmed, isLast }: {
  type: EventType
  highlighted: boolean
  dimmed: boolean
  isLast: boolean
}) {
  const theme = EVENT_THEMES[type] ?? EVENT_THEMES.manual_entry

  return (
    <div className="flex flex-col items-center shrink-0 w-8" aria-hidden="true">
      <div
        className={cn(
          'relative z-10 w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-300',
          theme.dotClass,
          highlighted && 'shadow-[0_0_12px] shadow-destructive/30 scale-110',
          dimmed && 'opacity-30 scale-75',
          theme.dotShape === '' && 'bg-transparent',
        )}
      >
        {theme.dotShape ? (
          <DotShape path={theme.dotShape} className="text-background" />
        ) : null}
      </div>
      {!isLast && (
        <div className={cn(
          'w-0.5 flex-1 mt-1 transition-all duration-300',
          highlighted ? 'bg-destructive/30' : dimmed ? 'bg-border-light/20' : 'bg-border-light',
        )} />
      )}
    </div>
  )
}

/** The content card to the right of the dot. Two variants: compact & detailed. */
function EventCard({ event, viewMode, highlighted, dimmed, expanded, onToggle }: {
  event: TimelineEvent
  viewMode: 'compact' | 'detailed'
  highlighted: boolean
  dimmed: boolean
  expanded: boolean
  onToggle: () => void
}) {
  const theme = EVENT_THEMES[event.event_type] ?? EVENT_THEMES.manual_entry
  const Icon = theme.icon
  const summary = eventPayloadSummary(event)

  if (event.seal_level === 'full') {
    return (
      <div className={cn('flex-1 pb-4', dimmed && 'opacity-40')}>
        <div className="flex items-center gap-2 py-2 text-muted-foreground">
          <Lock className="w-3.5 h-3.5" />
          <span className="text-xs italic">Sealed record — {formatDate(event.event_date)}</span>
        </div>
      </div>
    )
  }

  return (
    <div className={cn('flex-1 pb-4', dimmed && 'opacity-40')}>
      <div
        className={cn(
          'glass-card p-3 border-l-4 transition-all duration-300 cursor-pointer',
          theme.borderClass,
          highlighted && 'shadow-[0_0_16px_rgba(239,68,68,0.25)]',
          !expanded && 'hover:bg-card-hover',
        )}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle() } }}
      >
        {/* Compact row — always visible */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Icon className={cn('w-4 h-4 shrink-0 mt-0.5', theme.iconClass)} />
            <div className="min-w-0">
              <h4 className={cn(
                'text-sm font-medium truncate',
                viewMode === 'compact' ? 'text-foreground' : 'text-foreground',
              )}>
                {event.event_type === 'incident_report'
                  ? `Incident: ${String(event.payload.incident_type ?? '')}`
                  : event.event_type === 'placement_start' || event.event_type === 'placement_end'
                    ? `${theme.label}: ${String(event.payload.family_name ?? event.payload.family_id ?? '')}`
                    : event.event_type === 'school_change'
                      ? `School: ${String(event.payload.school_name ?? '')}`
                      : event.event_type === 'family_visitation'
                        ? `Visit: ${String(event.payload.family_member ?? '')}`
                        : event.event_type === 'court_date'
                          ? `Court: ${String(event.payload.court_type ?? '')}`
                          : event.event_type === 'milestone'
                            ? String(event.payload.title ?? 'Milestone')
                            : `${theme.label}: ${summary || 'Details'}`}
              </h4>
              {viewMode === 'compact' && summary && (
                <p className="text-xs text-muted-foreground truncate mt-0.5">{summary}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <time className="text-[10px] text-muted-foreground tabular-nums" dateTime={event.event_date}>
              {formatDate(event.event_date)}
            </time>
            {event.seal_level === 'partial' && <Lock className="w-3 h-3 text-muted-foreground/60" />}
            {!expanded && viewMode === 'detailed' && (
              <ChevronDown className="w-3.5 h-3.5 text-muted-foreground/60 transition-transform" />
            )}
          </div>
        </div>

        {/* Detailed expansion */}
        <AnimatePresence initial={false}>
          {expanded && viewMode === 'detailed' && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <hr className="my-2 border-border-light" />
              <div className="space-y-1.5 text-xs text-muted-foreground">
                <EventDetailRows event={event} />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

/** Detail rows rendered when a card is expanded in detailed mode. */
function EventDetailRows({ event }: { event: TimelineEvent }) {
  const p = event.payload

  const rows: { label: string; value: string }[] = []

  switch (event.event_type) {
    case 'placement_start':
    case 'placement_end':
    case 'placement_change':
      if (p.family_name) rows.push({ label: 'Family', value: String(p.family_name) })
      if (p.change_reason) rows.push({ label: 'Reason', value: String(p.change_reason) })
      if (p.outcome) rows.push({ label: 'Outcome', value: String(p.outcome) })
      if (p.duration_days != null) rows.push({ label: 'Duration', value: `${p.duration_days} days` })
      if (p.emergency) rows.push({ label: 'Emergency', value: 'Yes' })
      break
    case 'school_change':
      if (p.school_name) rows.push({ label: 'School', value: String(p.school_name) })
      if (p.grade) rows.push({ label: 'Grade', value: String(p.grade) })
      if (p.previous_school) rows.push({ label: 'Previous', value: String(p.previous_school) })
      if (p.reason_code) rows.push({ label: 'Reason', value: String(p.reason_code) })
      if (p.days_out_of_school != null) rows.push({ label: 'Days out of school', value: String(p.days_out_of_school) })
      if (p.attendance_rate_pct != null) rows.push({ label: 'Attendance', value: `${p.attendance_rate_pct}%` })
      break
    case 'incident_report':
      if (p.incident_type) rows.push({ label: 'Type', value: String(p.incident_type) })
      if (p.severity) rows.push({ label: 'Severity', value: String(p.severity) })
      if (p.resolution) rows.push({ label: 'Resolution', value: String(p.resolution) })
      if (p.involved_parties) rows.push({ label: 'Involved', value: Array.isArray(p.involved_parties) ? (p.involved_parties as string[]).join(', ') : String(p.involved_parties) })
      if (p.mood_score != null) rows.push({ label: 'Mood', value: `${p.mood_score}/5` })
      if (p.notes) rows.push({ label: 'Notes', value: String(p.notes).slice(0, 200) })
      break
    case 'court_date':
      if (p.court_type) rows.push({ label: 'Type', value: String(p.court_type) })
      if (p.outcome) rows.push({ label: 'Outcome', value: String(p.outcome) })
      if (p.next_date) rows.push({ label: 'Next hearing', value: formatDate(String(p.next_date)) })
      if (p.judge_name) rows.push({ label: 'Judge', value: String(p.judge_name) })
      if (p.legal_representation) rows.push({ label: 'Legal rep.', value: String(p.legal_representation) })
      break
    case 'family_visitation':
      if (p.family_member) rows.push({ label: 'Family', value: String(p.family_member) })
      if (p.relationship) rows.push({ label: 'Relationship', value: String(p.relationship) })
      if (p.visit_type) rows.push({ label: 'Type', value: String(p.visit_type) })
      if (p.occurred === false) rows.push({ label: 'Status', value: `Cancelled — ${p.cancellation_reason ?? 'reason unknown'}` })
      if (p.occurred !== false) {
        if (p.actual_duration_minutes != null) rows.push({ label: 'Duration', value: `${p.actual_duration_minutes} min` })
        if (p.post_visit_summary) rows.push({ label: 'Post-visit', value: String(p.post_visit_summary).slice(0, 200) })
      }
      break
    case 'sibling_contact':
      if (p.sibling_name) rows.push({ label: 'Sibling', value: String(p.sibling_name) })
      if (p.contact_type) rows.push({ label: 'Type', value: String(p.contact_type) })
      if (p.missed) rows.push({ label: 'Status', value: `Missed — ${p.missed_reason ?? 'reason unknown'}` })
      if (!p.missed && p.duration_minutes != null) rows.push({ label: 'Duration', value: `${p.duration_minutes} min` })
      if (p.child_sentiment) rows.push({ label: 'Child sentiment', value: String(p.child_sentiment) })
      break
    case 'crisis_alert':
      if (p.risk_score != null) rows.push({ label: 'Risk score', value: `${p.risk_score}%` })
      if (p.risk_level) rows.push({ label: 'Risk level', value: String(p.risk_level) })
      if (p.top_reasons) rows.push({ label: 'Top reasons', value: Array.isArray(p.top_reasons) ? (p.top_reasons as string[]).join('; ') : String(p.top_reasons) })
      if (p.recommended_interventions) rows.push({ label: 'Recommended', value: Array.isArray(p.recommended_interventions) ? (p.recommended_interventions as string[]).join('; ') : String(p.recommended_interventions) })
      break
    case 'drift_threshold':
      if (p.drift_score != null) rows.push({ label: 'Drift score', value: String(p.drift_score) })
      if (p.trend_direction) rows.push({ label: 'Trend', value: String(p.trend_direction) })
      if (p.drifting_signals) rows.push({ label: 'Signals', value: Array.isArray(p.drifting_signals) ? (p.drifting_signals as string[]).join(', ') : String(p.drifting_signals) })
      break
    case 'medical_appointment':
      if (p.appointment_type) rows.push({ label: 'Type', value: String(p.appointment_type) })
      if (p.provider_name) rows.push({ label: 'Provider', value: String(p.provider_name) })
      if (p.diagnosis) rows.push({ label: 'Diagnosis', value: Array.isArray(p.diagnosis) ? (p.diagnosis as string[]).join(', ') : String(p.diagnosis) })
      if (p.follow_up_date) rows.push({ label: 'Follow-up', value: formatDate(String(p.follow_up_date)) })
      break
    case 'therapy_session':
      if (p.therapy_type) rows.push({ label: 'Type', value: String(p.therapy_type) })
      if (p.provider_name) rows.push({ label: 'Provider', value: String(p.provider_name) })
      if (p.attendance) rows.push({ label: 'Attendance', value: String(p.attendance) })
      if (p.therapeutic_goal) rows.push({ label: 'Goal', value: String(p.therapeutic_goal).slice(0, 200) })
      break
    case 'caseworker_change':
      if (p.previous_name ?? p.previous_caseworker_id) rows.push({ label: 'From', value: String(p.previous_name ?? p.previous_caseworker_id) })
      if (p.new_name ?? p.new_caseworker_id) rows.push({ label: 'To', value: String(p.new_name ?? p.new_caseworker_id) })
      if (p.reason_code) rows.push({ label: 'Reason', value: String(p.reason_code) })
      break
    case 'caseworker_assignment':
      if (p.caseworker_name ?? p.caseworker_id) rows.push({ label: 'Caseworker', value: String(p.caseworker_name ?? p.caseworker_id) })
      if (p.role) rows.push({ label: 'Role', value: String(p.role) })
      break
    default:
      if (p.description) rows.push({ label: 'Description', value: String(p.description).slice(0, 300) })
      break
  }

  // Always show metadata
  rows.push({ label: 'Recorded', value: formatDate(event.recorded_at) })
  if (!event.is_verified) rows.push({ label: 'Status', value: 'Unverified — pending caseworker review' })
  if (event.conflict_resolution) rows.push({ label: 'Data source', value: event.conflict_resolution })

  return (
    <>
      {rows.map(r => (
        <div key={r.label} className="flex gap-2">
          <span className="text-muted-foreground/70 shrink-0 w-28">{r.label}</span>
          <span className="text-foreground/80">{r.value || '—'}</span>
        </div>
      ))}
    </>
  )
}

// ─── Month divider ───────────────────────────────────────────────────

function MonthDivider({ label, count }: { label: string; count: number }) {
  return (
    <div
      className="sticky top-0 z-20 py-2 bg-background/90 backdrop-blur-xl border-b border-border-light"
      role="separator"
      aria-label={label}
    >
      <div className="flex items-center gap-3">
        <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-widest">{label}</h3>
        <span className="text-[10px] text-muted-foreground/50 tabular-nums">{count} events</span>
        <div className="flex-1 h-px bg-border-light" />
      </div>
    </div>
  )
}

// ─── Filter bar ──────────────────────────────────────────────────────

function FilterBar({ activeGroups, onToggleGroup }: {
  activeGroups: Set<string>
  onToggleGroup: (key: string) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 py-2 px-1" role="group" aria-label="Filter by event type">
      {EVENT_GROUPS.map(g => {
        const theme = EVENT_THEMES[g.types[0]]
        const Icon = theme?.icon ?? Filter
        const isActive = activeGroups.has(g.key)
        return (
          <button
            key={g.key}
            onClick={() => onToggleGroup(g.key)}
            className={cn(
              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all cursor-pointer',
              'border',
              isActive
                ? 'bg-glass-hover text-foreground border-border-light'
                : 'bg-transparent text-muted-foreground/50 border-transparent hover:text-muted-foreground',
            )}
            aria-pressed={isActive}
          >
            <Icon className={cn('w-3 h-3', isActive ? theme?.iconClass : 'text-muted-foreground/50')} />
            {g.label}
          </button>
        )
      })}
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────

export function ChildLifeTimeline({ childId, events, viewMode, onEventClick, className }: ChildLifeTimelineProps) {
  const [activeGroups, setActiveGroups] = useState<Set<string>>(() => new Set(EVENT_GROUPS.map(g => g.key)))
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const timelineRef = useRef<HTMLDivElement>(null)

  // ── Filtering ────────────────────────────────────────────────────

  const toggleGroup = useCallback((key: string) => {
    setActiveGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }, [])

  const filtered = useMemo(() => {
    const allowedTypes = new Set(
      EVENT_GROUPS.filter(g => activeGroups.has(g.key)).flatMap(g => g.types)
    )
    return events.filter(e => allowedTypes.has(e.event_type))
  }, [events, activeGroups])

  // ── Grouping by month ────────────────────────────────────────────

  const grouped = useMemo(() => {
    const map = new Map<string, TimelineEvent[]>()
    for (const ev of filtered) {
      const key = formatMonthKey(ev.event_date)
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(ev)
    }
    // Sort groups newest-first
    return Array.from(map.entries()).sort(([a], [b]) => b.localeCompare(a))
  }, [filtered])

  // ── Correlation highlighting ─────────────────────────────────────

  const highlightedRange = useMemo(() => {
    if (selectedId === null) return null
    const target = events.find(e => e.id === selectedId)
    if (!target) return null
    const d = new Date(target.event_date)
    return { start: new Date(d.getTime() - 15 * 86_400_000), end: new Date(d.getTime() + 15 * 86_400_000), targetId: selectedId }
  }, [selectedId, events])

  const isHighlighted = useCallback((event: TimelineEvent): boolean => {
    if (!highlightedRange) return false
    if (event.id === highlightedRange.targetId) return true
    const d = new Date(event.event_date)
    return d >= highlightedRange.start && d <= highlightedRange.end
  }, [highlightedRange])

  const isDimmed = useCallback((event: TimelineEvent): boolean => {
    if (!highlightedRange) return false
    if (event.id === highlightedRange.targetId) return false
    const d = new Date(event.event_date)
    return d >= highlightedRange.start && d <= highlightedRange.end
  }, [highlightedRange])

  // ── Click handler ────────────────────────────────────────────────

  const handleEventClick = useCallback((event: TimelineEvent) => {
    setSelectedId(prev => prev === event.id ? null : event.id)
    onEventClick(event)
    setExpandedIds(prev => {
      const next = new Set(prev)
      if (next.has(event.id)) next.delete(event.id); else next.add(event.id)
      return next
    })
  }, [onEventClick])

  // ── Export shortcuts ─────────────────────────────────────────────

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && e.key === 'E') {
        e.preventDefault()
        window.open(`/api/timeline/${encodeURIComponent(childId)}/export/pdf`, '_blank')
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [childId])

  // ── Render ───────────────────────────────────────────────────────

  return (
    <GlassCard className={cn('flex flex-col overflow-hidden', className)}>
      {/* Header */}
      <GlassCardHeader className="shrink-0">
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-primary" />
          <GlassCardTitle>Life Timeline — {childId}</GlassCardTitle>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {filtered.length} of {events.length} events
          </span>
          <div className="flex gap-1">
            <Button
              variant="ghost" size="sm"
              onClick={() => window.open(`/api/timeline/${encodeURIComponent(childId)}/export/pdf`, '_blank')}
              aria-label="Export timeline to PDF"
            >
              <Printer className="w-3.5 h-3.5" />
            </Button>
            <Button
              variant="ghost" size="sm"
              onClick={() => {/* open print dialog */ window.print() }}
              aria-label="Print timeline"
            >
              <Download className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </GlassCardHeader>

      {/* Filter bar */}
      <div className="shrink-0 px-3 border-b border-border-light">
        <FilterBar activeGroups={activeGroups} onToggleGroup={toggleGroup} />
      </div>

      {/* Timeline body */}
      <div
        ref={timelineRef}
        className="flex-1 overflow-y-auto px-4 py-2"
        role="feed"
        aria-label={`Life timeline for ${childId}`}
        aria-setsize={filtered.length}
      >
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Calendar className="w-10 h-10 text-muted-foreground/40 mb-3" />
            <p className="text-sm text-muted-foreground">No events to display.</p>
            <p className="text-xs text-muted-foreground/60 mt-1">
              {activeGroups.size < EVENT_GROUPS.length
                ? 'Try adjusting the filters above.'
                : 'As events are added they will appear here.'}
            </p>
          </div>
        ) : (
          grouped.map(([monthKey, monthEvents]) => {
            const label = formatMonth(monthEvents[0].event_date)
            return (
              <div key={monthKey} className="mb-2">
                <MonthDivider label={label} count={monthEvents.length} />
                <div className="pt-2">
                  {monthEvents.map((ev, idx) => {
                    const hl = highlightedRange ? isHighlighted(ev) : false
                    // An event is "dimmed" if another event is selected and this one is
                    // outside the 30-day window but in the same visible set.
                    const dim = highlightedRange !== null && highlightedRange.targetId !== ev.id
                      ? !isHighlighted(ev)
                      : false

                    return (
                      <div
                        key={ev.id}
                        className={cn(
                          'flex gap-3 transition-all duration-300',
                          dim && 'opacity-30 pointer-events-none',
                        )}
                        role="article"
                        aria-setsize={filtered.length}
                        aria-posinset={idx + 1}
                        aria-labelledby={`event-title-${ev.id}`}
                      >
                        <EventDot
                          type={ev.event_type}
                          highlighted={hl && highlightedRange?.targetId === ev.id}
                          dimmed={dim}
                          isLast={idx === monthEvents.length - 1}
                        />
                        <EventCard
                          event={ev}
                          viewMode={viewMode}
                          highlighted={hl && highlightedRange?.targetId === ev.id}
                          dimmed={dim}
                          expanded={expandedIds.has(ev.id)}
                          onToggle={() => handleEventClick(ev)}
                        />
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Legend footer */}
      <div className="shrink-0 border-t border-border-light px-3 py-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
        {EVENT_GROUPS.map(g => {
          const theme = EVENT_THEMES[g.types[0]]
          if (!theme) return null
          const Icon = theme.icon
          return (
            <span key={g.key} className="inline-flex items-center gap-1 text-[10px] text-muted-foreground/60">
              <Icon className={cn('w-2.5 h-2.5', theme.iconClass)} />
              {g.label}
            </span>
          )
        })}
      </div>
    </GlassCard>
  )
}
