import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, School, Stethoscope, AlertTriangle, Heart, Scale, Home, FileEdit } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { GlassCard } from '@/components/ui/glass-card'
import { cn } from '@/lib/utils'
import type { TimelineEventType, EventSeverity } from '@/services/foster'

interface AddEventModalProps {
  open: boolean
  onClose: () => void
  onSave: (data: {
    event_type: TimelineEventType
    title: string
    description: string
    severity: EventSeverity
  }) => void
  initialType?: TimelineEventType
}

const EVENT_TYPES: { type: TimelineEventType; label: string; icon: React.ElementType; color: string }[] = [
  { type: 'school', label: 'School', icon: School, color: 'text-success' },
  { type: 'medical', label: 'Medical', icon: Stethoscope, color: 'text-secondary' },
  { type: 'incident', label: 'Incident', icon: AlertTriangle, color: 'text-destructive' },
  { type: 'visit', label: 'Visit', icon: Heart, color: 'text-warning' },
  { type: 'legal', label: 'Legal', icon: Scale, color: 'text-accent' },
  { type: 'placement', label: 'Placement', icon: Home, color: 'text-info' },
  { type: 'note', label: 'Note', icon: FileEdit, color: 'text-muted-foreground' },
]

const SEVERITIES: { value: EventSeverity; label: string; color: string }[] = [
  { value: 'low', label: 'Low', color: 'bg-success/10 text-success border-success/30' },
  { value: 'medium', label: 'Medium', color: 'bg-warning/10 text-warning border-warning/30' },
  { value: 'high', label: 'High', color: 'bg-destructive/10 text-destructive border-destructive/30' },
]

export function AddEventModal({ open, onClose, onSave, initialType }: AddEventModalProps) {
  const [eventType, setEventType] = useState<TimelineEventType>(initialType || 'note')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [severity, setSeverity] = useState<EventSeverity>('low')

  const selectedType = EVENT_TYPES.find(t => t.type === eventType)
  const Icon = selectedType?.icon || FileEdit

  const handleSave = () => {
    onSave({ event_type: eventType, title: title.trim(), description: description.trim(), severity })
    setTitle('')
    setDescription('')
    setSeverity('low')
    onClose()
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
          >
            <GlassCard className="w-full max-w-lg max-h-[90vh] overflow-y-auto">
              <div className="flex items-center justify-between p-4 border-b border-border-light">
                <div className="flex items-center gap-2">
                  <Icon className={cn('w-5 h-5', selectedType?.color)} />
                  <h2 className="text-lg font-semibold text-foreground">Add Event</h2>
                </div>
                <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
                  <X className="w-4 h-4" />
                </Button>
              </div>

              <div className="p-4 space-y-4">
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-2 block">Type</label>
                  <div className="grid grid-cols-4 gap-2">
                    {EVENT_TYPES.map(t => {
                      const IconComp = t.icon
                      const isActive = eventType === t.type
                      return (
                        <button
                          key={t.type}
                          onClick={() => setEventType(t.type)}
                          className={cn(
                            'flex flex-col items-center gap-1 p-2 rounded-lg border text-xs transition-all',
                            isActive
                              ? 'border-primary/50 bg-primary/5 text-foreground'
                              : 'border-border-light text-muted-foreground hover:border-border hover:text-foreground',
                          )}
                        >
                          <IconComp className={cn('w-4 h-4', isActive ? t.color : '')} />
                          {t.label}
                        </button>
                      )
                    })}
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">Title</label>
                  <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="e.g. School attendance dropped below 80%"
                    className="w-full bg-transparent border border-border-light rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50"
                  />
                </div>

                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1 block">Description</label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Add details about this event..."
                    rows={3}
                    className="w-full bg-transparent border border-border-light rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:border-primary/50 resize-none"
                  />
                </div>

                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-2 block">Severity</label>
                  <div className="flex gap-2">
                    {SEVERITIES.map(s => (
                      <button
                        key={s.value}
                        onClick={() => setSeverity(s.value)}
                        className={cn(
                          'px-3 py-1.5 rounded-full text-xs font-medium border transition-all',
                          severity === s.value ? s.color : 'border-border-light text-muted-foreground',
                        )}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 p-4 border-t border-border-light">
                <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
                <Button size="sm" onClick={handleSave} disabled={!title.trim()}>
                  Save Event
                </Button>
              </div>
            </GlassCard>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
