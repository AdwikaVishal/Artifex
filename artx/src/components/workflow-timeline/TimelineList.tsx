import { AnimatePresence } from 'framer-motion'
import type { TimelineEvent } from '@/types/workflow-timeline'
import TimelineStage from './TimelineStage'

interface TimelineListProps {
  events: TimelineEvent[]
  selectedId: string | null
  onSelect: (id: string) => void
  isReplay?: boolean
}

export default function TimelineList({ events, selectedId, onSelect, isReplay }: TimelineListProps) {
  if (events.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <div className="w-16 h-16 rounded-full bg-surface-alt border border-border flex items-center justify-center mb-4">
          <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </div>
        <p className="text-sm text-muted-foreground">No timeline events available</p>
        <p className="text-xs text-muted-foreground mt-1">Events will appear as the workflow progresses</p>
      </div>
    )
  }

  return (
    <div className="relative">
      <AnimatePresence mode="popLayout">
        {events.map((event, index) => (
          <TimelineStage
            key={event.id}
            event={event}
            index={index}
            total={events.length}
            isLast={index === events.length - 1}
            isSelected={selectedId === event.id}
            onClick={() => onSelect(event.id)}
            isReplay={isReplay}
          />
        ))}
      </AnimatePresence>
    </div>
  )
}
