import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import {
  Users, Search, ChevronRight, Plus, X,
  School, Stethoscope, AlertTriangle, Heart, Scale, Home, FileEdit,
  Clock, Activity, TrendingUp, Shield, Calendar,
} from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import {
  getTimelineEvents, subscribeChildEventStream, quickAddEvent,
  getChildEventStats,
} from '@/services/foster'
import type { TimelineEventV2, EventSeverity, QuickAddRequest } from '@/services/foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { DataLoader } from '@/components/data-loader'
import { EmergencyBadge } from '@/components/ui/badge'
import { ChildLifeTimeline } from '@/components/ChildLifeTimeline'
import type { TimelineEvent } from '@/components/ChildLifeTimeline'
import { AddEventModal } from '@/components/AddEventModal'
import { cn } from '@/lib/utils'

interface Child {
  child_id: string
  first_name: string
  last_name: string
  age: number
  gender: string
  emergency_level: string
  special_needs: boolean
  location: string
  created_at: string | null
}

interface ChildStats {
  child_id: string
  child_name: string
  age: number | null
  emergency_level: string
  special_needs: boolean
  location: string
  total_events: number
  by_type: Record<string, number>
  by_severity: Record<string, number>
  last_activity: string | null
  placement: {
    family_id?: string
    status?: string
    since?: string
  }
}

const QUICK_ADD_TYPES: { type: QuickAddRequest['event_type']; icon: React.ElementType; label: string; color: string }[] = [
  { type: 'school', icon: School, label: '+ School Note', color: 'text-success' },
  { type: 'incident', icon: AlertTriangle, label: '+ Incident', color: 'text-destructive' },
  { type: 'medical', icon: Stethoscope, label: '+ Medical', color: 'text-secondary' },
  { type: 'visit', icon: Heart, label: '+ Visit', color: 'text-warning' },
  { type: 'legal', icon: Scale, label: '+ Legal', color: 'text-accent' },
  { type: 'placement', icon: Home, label: '+ Placement', color: 'text-info' },
  { type: 'note', icon: FileEdit, label: '+ Note', color: 'text-muted-foreground' },
]

const CATEGORY_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'note', label: 'Notes' },
  { key: 'incident', label: 'Incidents' },
  { key: 'school', label: 'School' },
  { key: 'medical', label: 'Medical' },
  { key: 'placement', label: 'Placement' },
]

function useChildren() {
  return useQuery({
    queryKey: ['children'],
    queryFn: async (): Promise<Child[]> => {
      const res = await api.get<{ children: Child[]; count: number }>('/children')
      return res.data?.children ?? []
    },
    refetchInterval: 30000,
    retry: 2,
  })
}

const SEVERITY_ICONS: Record<string, React.ElementType> = {
  medium: Shield,
  high: AlertTriangle,
  critical: TrendingUp,
}

export default function ChildrenPage() {
  const { data: children, isLoading, error } = useChildren()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [filterCategory, setFilterCategory] = useState('all')
  const timelineRef = useRef<HTMLDivElement>(null)

  // Fetch timeline events for the selected child
  const { data: timelineData, isLoading: timelineLoading } = useQuery({
    queryKey: ['child-life-events', selectedId],
    queryFn: () => getTimelineEvents(selectedId!, { per_page: 200 }),
    enabled: !!selectedId,
    staleTime: 1000 * 30,
    retry: 1,
  })

  // Fetch child stats for header
  const { data: stats } = useQuery({
    queryKey: ['child-stats', selectedId],
    queryFn: () => getChildEventStats(selectedId!),
    enabled: !!selectedId,
    staleTime: 1000 * 30,
  })

  const [liveEvents, setLiveEvents] = useState<TimelineEventV2[]>([])

  // WS subscription for live events
  useEffect(() => {
    if (!selectedId) return
    setLiveEvents([])
    const sub = subscribeChildEventStream(selectedId, (event) => {
      setLiveEvents(prev => [event, ...prev])
      queryClient.invalidateQueries({ queryKey: ['child-life-events', selectedId] })
      queryClient.invalidateQueries({ queryKey: ['child-stats', selectedId] })
    })
    return () => sub.close()
  }, [selectedId, queryClient])

  // Merge live events into timeline events
  const allEvents: TimelineEvent[] = useMemo(() => {
    const apiEvents: TimelineEvent[] = (timelineData?.events ?? []).map(ev => ev as TimelineEvent)
    const liveIds = new Set(liveEvents.map(e => `live-${e.id}`))
    const merged = [...liveEvents as TimelineEvent[]]
    for (const ev of apiEvents) {
      if (!liveIds.has(`live-${ev.id}`)) {
        merged.push(ev)
      }
    }
    merged.sort((a, b) => new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime())
    return merged
  }, [timelineData, liveEvents])

  // Filter events by category
  const filteredEvents = useMemo(() => {
    if (filterCategory === 'all') return allEvents
    return allEvents.filter(ev => ev.event_type === filterCategory)
  }, [allEvents, filterCategory])

  const quickAddMutation = useMutation({
    mutationFn: (data: QuickAddRequest) => quickAddEvent(selectedId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['child-life-events', selectedId] })
      queryClient.invalidateQueries({ queryKey: ['child-stats', selectedId] })
    },
  })

  const handleSaveEvent = useCallback((data: {
    event_type: TimelineEventV2['event_type']
    title: string
    description: string
    severity: EventSeverity
  }) => {
    const payload = {
      ...data,
      event_type:
        data.event_type === 'placement_start' ||
        data.event_type === 'placement_end'
          ? 'placement'
          : data.event_type,
    }
    quickAddMutation.mutate(payload as QuickAddRequest)
  }, [quickAddMutation])

  const filtered = useMemo(() => {
    if (!children) return []
    const q = search.toLowerCase()
    if (!q) return children
    return children.filter(
      (c) =>
        c.child_id.toLowerCase().includes(q) ||
        `${c.first_name} ${c.last_name}`.toLowerCase().includes(q) ||
        (c.location || '').toLowerCase().includes(q)
    )
  }, [children, search])

  const selectedChild = useMemo(
    () => children?.find(c => c.child_id === selectedId),
    [children, selectedId],
  )

  const childName = selectedChild
    ? [selectedChild.first_name, selectedChild.last_name].filter(Boolean).join(' ') || selectedChild.child_id
    : ''

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="flex items-center gap-3">
        <Users className="w-6 h-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">Children</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Real-time child event stream
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left: child list */}
        <div className="lg:col-span-1 space-y-3">
          <GlassCard>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search children..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9"
              />
            </div>
          </GlassCard>

          <DataLoader isLoading={isLoading} error={error} type="card" rows={5}>
            <div className="space-y-2 max-h-[600px] overflow-y-auto">
              {filtered.length === 0 && (
                <GlassCard>
                  <p className="text-sm text-muted-foreground text-center py-6">
                    {search ? 'No children match your search' : 'No children in the system'}
                  </p>
                </GlassCard>
              )}
              {filtered.map((child) => (
                <button
                  key={child.child_id}
                  onClick={() => setSelectedId(child.child_id)}
                  className={cn(
                    'w-full text-left rounded-xl border p-3 transition-all',
                    selectedId === child.child_id
                      ? 'border-primary/50 bg-primary/5'
                      : 'border-border bg-glass hover:bg-glass-hover',
                  )}
                >
                  <div className="flex items-center justify-between">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">
                        {child.first_name || child.last_name
                          ? `${child.first_name} ${child.last_name}`.trim()
                          : child.child_id}
                      </p>
                      <p className="text-xs text-muted-foreground font-mono">
                        {child.child_id}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-muted-foreground">
                          Age {child.age ?? '?'}
                        </span>
                        {child.special_needs && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-blue-500/10 text-blue-400 rounded">
                            Special Needs
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <EmergencyBadge level={child.emergency_level} />
                      <ChevronRight className="w-4 h-4 text-muted-foreground" />
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </DataLoader>
        </div>

        {/* Center: event stream */}
        <div className="lg:col-span-2 space-y-3">
          {selectedId ? (
            <>
              {/* Child Header */}
              <GlassCard>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center text-lg">
                      {selectedChild?.gender === 'Male' ? '👦' : selectedChild?.gender === 'Female' ? '👧' : '🧒'}
                    </div>
                    <div>
                      <h2 className="text-lg font-semibold text-foreground">{childName}</h2>
                      <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
                        <span>#{selectedChild?.child_id}</span>
                        <span>Age {selectedChild?.age ?? '?'}</span>
                        <span>{selectedChild?.location}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-1.5">
                        <EmergencyBadge level={stats?.emergency_level || selectedChild?.emergency_level || 'normal'} />
                        {stats?.placement?.status === 'active' && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-success/10 text-success rounded-full border border-success/30">
                            Placement Active
                          </span>
                        )}
                        {selectedChild?.special_needs && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-blue-500/10 text-blue-400 rounded-full border border-blue-500/30">
                            Special Needs
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="text-right text-xs text-muted-foreground space-y-1">
                    <div className="flex items-center gap-2">
                      <Activity className="w-3 h-3" />
                      <span className="tabular-nums">{stats?.total_events ?? 0} events</span>
                    </div>
                    {stats?.last_activity && (
                      <div className="flex items-center gap-2">
                        <Clock className="w-3 h-3" />
                        <span>
                          {(() => {
                            const mins = Math.floor((Date.now() - new Date(stats.last_activity!).getTime()) / 60000)
                            return mins < 1 ? 'Just now' : mins < 60 ? `${mins}m ago` : `${Math.floor(mins / 60)}h ago`
                          })()}
                        </span>
                      </div>
                    )}
                  </div>
                </div>

                {/* Quick Add row */}
                <div className="flex items-center gap-2 mt-4 pt-3 border-t border-border-light">
                  <Button
                    size="sm"
                    onClick={() => setShowAddModal(true)}
                    className="shrink-0"
                  >
                    <Plus className="w-4 h-4 mr-1" />
                    Add Event
                  </Button>
                  <div className="flex gap-1 overflow-x-auto">
                    {QUICK_ADD_TYPES.map(qa => {
                      const IconComp = qa.icon
                      return (
                        <button
                          key={qa.type}
                          onClick={() => quickAddMutation.mutate({ event_type: qa.type })}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg border border-border-light text-[10px] text-muted-foreground hover:text-foreground hover:border-border transition-all whitespace-nowrap"
                        >
                          <IconComp className={cn('w-3 h-3', qa.color)} />
                          {qa.label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              </GlassCard>

              {/* Category filter */}
              <div className="flex items-center gap-1.5">
                {CATEGORY_FILTERS.map(f => (
                  <button
                    key={f.key}
                    onClick={() => setFilterCategory(f.key)}
                    className={cn(
                      'px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all',
                      filterCategory === f.key
                        ? 'bg-primary/10 text-primary border-primary/30'
                        : 'text-muted-foreground border-border-light hover:text-foreground',
                    )}
                  >
                    {f.label}
                  </button>
                ))}
                <span className="text-[10px] text-muted-foreground/60 ml-auto tabular-nums">
                  {filteredEvents.length} events
                </span>
              </div>

              {/* Live Timeline Feed */}
              <GlassCard className="overflow-hidden">
                <div ref={timelineRef} className="max-h-[600px] overflow-y-auto px-4 py-2">
                  <ChildLifeTimeline
                    childId={selectedId}
                    events={filteredEvents}
                  />
                </div>
              </GlassCard>
            </>
          ) : (
            <GlassCard>
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <Users className="w-10 h-10 text-muted-foreground mb-3" />
                <h3 className="text-base font-semibold text-foreground mb-1">
                  Select a child
                </h3>
                <p className="text-sm text-muted-foreground">
                  Choose a child from the list to view their live event stream
                </p>
              </div>
            </GlassCard>
          )}
        </div>

        {/* Right: stats panel */}
        <div className="lg:col-span-1 space-y-3">
          {stats && (
            <>
              <GlassCard>
                <GlassCardHeader>
                  <Activity className="w-4 h-4 text-primary" />
                  <GlassCardTitle>Statistics</GlassCardTitle>
                </GlassCardHeader>
                <div className="px-3 pb-3 space-y-2">
                  <div className="flex justify-between text-xs">
                    <span className="text-muted-foreground">Events this month</span>
                    <span className="text-foreground font-medium tabular-nums">{stats.total_events}</span>
                  </div>
                  {Object.entries(stats.by_type || {}).slice(0, 5).map(([type, count]) => {
                    const theme = QUICK_ADD_TYPES.find(q => q.type === type)
                    const IconComp = theme?.icon || Activity
                    return (
                      <div key={type} className="flex justify-between text-xs">
                        <span className="flex items-center gap-1.5 text-muted-foreground">
                          <IconComp className={cn('w-3 h-3', theme?.color)} />
                          {type.charAt(0).toUpperCase() + type.slice(1)}
                        </span>
                        <span className="text-foreground font-medium tabular-nums">{count}</span>
                      </div>
                    )
                  })}
                  {Object.entries(stats.by_severity || {}).length > 0 && (
                    <>
                      <div className="border-t border-border-light pt-2 mt-2" />
                      {Object.entries(stats.by_severity).map(([sev, count]) => {
                        const SevIcon = SEVERITY_ICONS[sev] || Shield
                        const colorMap: Record<string, string> = {
                          low: 'text-muted-foreground',
                          medium: 'text-warning',
                          high: 'text-destructive',
                          critical: 'text-critical',
                        }
                        return (
                          <div key={sev} className="flex justify-between text-xs">
                            <span className="flex items-center gap-1.5 text-muted-foreground">
                              <SevIcon className={cn('w-3 h-3', colorMap[sev] || '')} />
                              {sev.charAt(0).toUpperCase() + sev.slice(1)}
                            </span>
                            <span className="text-foreground font-medium tabular-nums">{count}</span>
                          </div>
                        )
                      })}
                    </>
                  )}
                </div>
              </GlassCard>

              {stats.placement?.status && (
                <GlassCard>
                  <GlassCardHeader>
                    <Home className="w-4 h-4 text-primary" />
                    <GlassCardTitle>Placement</GlassCardTitle>
                  </GlassCardHeader>
                  <div className="px-3 pb-3 space-y-1.5 text-xs">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Status</span>
                      <span className={cn(
                        'font-medium',
                        stats.placement.status === 'active' ? 'text-success' : 'text-muted-foreground',
                      )}>
                        {stats.placement.status}
                      </span>
                    </div>
                    {stats.placement.family_id && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Family</span>
                        <span className="text-foreground font-medium">{stats.placement.family_id}</span>
                      </div>
                    )}
                    {stats.placement.since && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Since</span>
                        <span className="text-foreground font-medium">
                          {new Date(stats.placement.since).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                        </span>
                      </div>
                    )}
                  </div>
                </GlassCard>
              )}

              <GlassCard>
                <GlassCardHeader>
                  <Calendar className="w-4 h-4 text-primary" />
                  <GlassCardTitle>Upcoming</GlassCardTitle>
                </GlassCardHeader>
                <div className="px-3 pb-3">
                  <p className="text-xs text-muted-foreground">No upcoming events scheduled.</p>
                </div>
              </GlassCard>
            </>
          )}
        </div>
      </div>

      {/* Add Event Modal */}
      <AddEventModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
        onSave={handleSaveEvent}
      />
    </motion.div>
  )
}
