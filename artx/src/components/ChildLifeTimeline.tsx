/**
 * ChildLifeTimeline – renders a vertical chronological timeline for a child.
 *
 * Aggregates placements, workflow stages, check-ins, and incidents into a
 * single scrollable timeline with colour-coded event types.
 */
import { Calendar, Home, Heart, AlertTriangle, MessageSquare, Settings } from 'lucide-react'
import { useChildTimeline } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { DataLoader } from '@/components/data-loader'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '@/services/foster'

interface ChildLifeTimelineProps {
  childId: string
}

function EventIcon({ type }: { type: TimelineEvent['type'] }) {
  const base = 'w-4 h-4'
  switch (type) {
    case 'entry':
      return <Home className={cn(base, 'text-blue-400')} />
    case 'placement':
      return <Heart className={cn(base, 'text-purple-400')} />
    case 'incident':
      return <AlertTriangle className={cn(base, 'text-red-400')} />
    case 'workflow':
      return <Settings className={cn(base, 'text-gray-400')} />
    default:
      return <MessageSquare className={cn(base, 'text-green-400')} />
  }
}

const EVENT_DOT_COLOR: Record<TimelineEvent['type'], string> = {
  entry: 'bg-blue-500 border-blue-400',
  placement: 'bg-purple-500 border-purple-400',
  incident: 'bg-red-500 border-red-400',
  workflow: 'bg-gray-500 border-gray-400',
  checkin: 'bg-green-500 border-green-400',
}

function TimelineItem({ event, isLast }: { event: TimelineEvent; isLast: boolean }) {
  const dotColor = EVENT_DOT_COLOR[event.type] ?? EVENT_DOT_COLOR.checkin

  return (
    <div className="relative flex gap-4">
      {/* Dot + connector line */}
      <div className="flex flex-col items-center">
        <div
          className={cn(
            'relative z-10 w-9 h-9 rounded-full border-2 flex items-center justify-center bg-gray-900 shrink-0',
            dotColor
          )}
        >
          <EventIcon type={event.type} />
        </div>
        {!isLast && (
          <div className="w-px flex-1 bg-gray-700 mt-1" />
        )}
      </div>

      {/* Content card */}
      <div className={cn('flex-1 pb-6', isLast && 'pb-0')}>
        <div className="bg-gray-800/60 rounded-lg p-3 border border-gray-700/50">
          <div className="flex items-start justify-between gap-2 mb-1">
            <h4 className="text-sm font-medium text-gray-100">{event.title}</h4>
            {event.date && (
              <span className="text-[10px] text-gray-500 shrink-0 tabular-nums">
                {new Date(event.date).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}
              </span>
            )}
          </div>
          {event.description && (
            <p className="text-xs text-gray-400">{event.description}</p>
          )}
          {event.risk_score !== undefined && (
            <div
              className={cn(
                'mt-1.5 text-[10px] font-medium',
                event.risk_score > 70
                  ? 'text-red-400'
                  : event.risk_score > 40
                  ? 'text-yellow-400'
                  : 'text-green-400'
              )}
            >
              Risk: {event.risk_score.toFixed(0)}%
            </div>
          )}
          {event.mood_score !== undefined && (
            <div className="mt-1.5 text-[10px] text-gray-500">
              Mood: {event.mood_score}/5
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export function ChildLifeTimeline({ childId }: ChildLifeTimelineProps) {
  const { data, isLoading, error } = useChildTimeline(childId)

  return (
    <GlassCard>
      <GlassCardHeader>
        <div className="flex items-center gap-2">
          <Calendar className="w-5 h-5 text-purple-400" />
          <GlassCardTitle>
            {data ? `${data.child_name} – Life Timeline` : 'Child Life Timeline'}
          </GlassCardTitle>
        </div>
        {data && (
          <div className="flex items-center gap-3 text-xs text-gray-400">
            {data.age != null && <span>Age {data.age}</span>}
            {data.special_needs && (
              <span className="px-1.5 py-0.5 bg-blue-500/15 text-blue-400 rounded">
                Special Needs
              </span>
            )}
            {data.emergency_level === 'emergency' && (
              <span className="px-1.5 py-0.5 bg-red-500/15 text-red-400 rounded">
                Emergency
              </span>
            )}
          </div>
        )}
      </GlassCardHeader>

      <div className="px-4 pb-4">
        <DataLoader isLoading={isLoading} error={error} type="card" rows={4}>
          {data && (
            <>
              {data.timeline.length === 0 ? (
                <p className="text-sm text-gray-500 text-center py-8">
                  No timeline events yet
                </p>
              ) : (
                <div className="mt-2 max-h-[520px] overflow-y-auto pr-1">
                  {data.timeline.map((event, idx) => (
                    <TimelineItem
                      key={`${event.type}-${idx}`}
                      event={event}
                      isLast={idx === data.timeline.length - 1}
                    />
                  ))}
                </div>
              )}

              {/* Milestones */}
              {data.milestones && data.milestones.length > 0 && (
                <div className="mt-4 pt-4 border-t border-gray-800">
                  <p className="text-xs text-gray-400 mb-2">Milestones</p>
                  <div className="flex flex-wrap gap-2">
                    {(data.milestones as Array<{ title?: string; date?: string }>).map(
                      (m, i) => (
                        <span
                          key={i}
                          className="text-xs px-2 py-1 bg-purple-500/10 text-purple-400 rounded-full border border-purple-500/20"
                        >
                          {m.title || 'Milestone'}
                        </span>
                      )
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </DataLoader>
      </div>
    </GlassCard>
  )
}
