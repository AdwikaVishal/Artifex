/**
 * ChildrenPage – lists all children and shows the Child Life Timeline
 * for a selected child.
 */
import { useState, useMemo, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Users, Search, ChevronRight, List, LayoutGrid } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { getTimelineEvents } from '@/services/foster'
import type { TimelineEventV2 } from '@/services/foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { DataLoader } from '@/components/data-loader'
import { EmergencyBadge } from '@/components/ui/badge'
import { ChildLifeTimeline } from '@/components/ChildLifeTimeline'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '@/components/ChildLifeTimeline'

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

export default function ChildrenPage() {
  const { data: children, isLoading, error } = useChildren()
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'compact' | 'detailed'>('detailed')

  // Fetch timeline events for the selected child
  const { data: timelineData, isLoading: timelineLoading } = useQuery({
    queryKey: ['child-life-events', selectedId],
    queryFn: () => getTimelineEvents(selectedId!, { per_page: 200 }),
    enabled: !!selectedId,
    staleTime: 1000 * 60 * 2,
    retry: 1,
  })

  // Map API events to component TimelineEvent type
  const timelineEvents: TimelineEvent[] = useMemo(() => {
    if (!timelineData?.events) return []
    return timelineData.events.map((ev: TimelineEventV2) => ({
      id: ev.id,
      child_id: ev.child_id,
      event_type: ev.event_type as TimelineEvent['event_type'],
      event_date: ev.event_date,
      event_time: ev.event_time ?? undefined,
      recorded_at: ev.recorded_at,
      source_table: ev.source_table ?? undefined,
      source_id: ev.source_id ?? undefined,
      conflict_resolution: ev.conflict_resolution ?? undefined,
      payload: ev.payload,
      is_verified: ev.is_verified,
      verified_by: ev.verified_by ?? undefined,
      verified_at: ev.verified_at ?? undefined,
      superseded_by: ev.superseded_by ?? undefined,
      seal_level: (ev.seal_level || 'none') as TimelineEvent['seal_level'],
    }))
  }, [timelineData])

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

  const handleEventClick = useCallback((event: TimelineEvent) => {
    // Handled internally by ChildLifeTimeline
  }, [])

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
            View child profiles and life timelines
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
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
                      : 'border-border bg-glass hover:bg-glass-hover'
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

        {/* Right: timeline */}
        <div className="lg:col-span-2">
          {selectedId ? (
            <div className="space-y-3">
              {/* View mode toggle */}
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {timelineLoading ? 'Loading...' : `${timelineEvents.length} events`}
                </span>
                <div className="flex gap-1 bg-glass rounded-lg p-0.5 border border-border-light">
                  <button
                    onClick={() => setViewMode('compact')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      viewMode === 'compact' ? 'bg-glass-hover text-foreground' : 'text-muted-foreground hover:text-foreground',
                    )}
                    aria-label="Compact view"
                  >
                    <List className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setViewMode('detailed')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      viewMode === 'detailed' ? 'bg-glass-hover text-foreground' : 'text-muted-foreground hover:text-foreground',
                    )}
                    aria-label="Detailed view"
                  >
                    <LayoutGrid className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <ChildLifeTimeline
                childId={selectedId}
                events={timelineEvents}
                viewMode={viewMode}
                onEventClick={handleEventClick}
              />
            </div>
          ) : (
            <GlassCard>
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <Users className="w-10 h-10 text-muted-foreground mb-3" />
                <h3 className="text-base font-semibold text-foreground mb-1">
                  Select a child
                </h3>
                <p className="text-sm text-muted-foreground">
                  Choose a child from the list to view their life timeline
                </p>
              </div>
            </GlassCard>
          )}
        </div>
      </div>
    </motion.div>
  )
}
