import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  School, Users, Stethoscope, Phone, UserPlus, UserCog, HeartPulse, Pill,
  Plus, X, Play,
} from 'lucide-react'
import { GlassCard } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface Intervention {
  id: string
  domain: 'school' | 'placement' | 'therapy' | 'visits' | 'mentor' | 'caseworker' | 'sibling' | 'medication'
  action: string
  value: string
}

const INTERVENTION_TYPES: { domain: Intervention['domain']; label: string; icon: React.ElementType; color: string }[] = [
  { domain: 'school',     label: 'School change',     icon: School,      color: 'border-l-orange-500' },
  { domain: 'placement',  label: 'Placement change',  icon: Users,       color: 'border-l-purple-500' },
  { domain: 'therapy',    label: 'Therapy increase',  icon: Stethoscope, color: 'border-l-emerald-500' },
  { domain: 'visits',     label: 'Visits increase',   icon: Phone,       color: 'border-l-blue-500' },
  { domain: 'mentor',     label: 'Mentor assign',     icon: UserPlus,    color: 'border-l-yellow-500' },
  { domain: 'caseworker', label: 'Change caseworker', icon: UserCog,     color: 'border-l-gray-400' },
  { domain: 'sibling',    label: 'Sibling visit inc.', icon: HeartPulse, color: 'border-l-pink-400' },
  { domain: 'medication', label: 'Medication plan',   icon: Pill,        color: 'border-l-red-500' },
]

const DOMAIN_VALUES: Record<Intervention['domain'], { action: string; options: string[]; placeholder: string }> = {
  school:     { action: 'change',     options: ['Washington Elementary', 'Lincoln Elementary', 'Roosevelt Elementary', 'Jefferson Elementary'], placeholder: 'Select school…' },
  placement:  { action: 'change',     options: [], placeholder: 'Select family…' },
  therapy:    { action: 'increase',   options: ['Weekly', 'Twice weekly'], placeholder: 'Select frequency…' },
  visits:     { action: 'increase',   options: ['Weekly', 'Twice weekly'], placeholder: 'Select frequency…' },
  mentor:     { action: 'assign',     options: ['Yes'], placeholder: 'Assign mentor' },
  caseworker: { action: 'change',     options: [], placeholder: 'Select caseworker…' },
  sibling:    { action: 'increase',   options: ['Weekly', 'Biweekly'], placeholder: 'Select frequency…' },
  medication: { action: 'create',     options: ['Review plan', 'New plan'], placeholder: 'Select plan type…' },
}

interface InterventionBuilderProps {
  onSimulate: (interventions: Intervention[]) => void
  loading?: boolean
}

export function InterventionBuilder({ onSimulate, loading }: InterventionBuilderProps) {
  const [workbench, setWorkbench] = useState<Intervention[]>([])
  const [expandedCard, setExpandedCard] = useState<string | null>(null)

  const addIntervention = useCallback((domain: Intervention['domain']) => {
    if (workbench.length >= 3) return
    const cfg = DOMAIN_VALUES[domain]
    const newIv: Intervention = {
      id: `${domain}-${Date.now()}`,
      domain,
      action: cfg.action,
      value: '',
    }
    setWorkbench(prev => [...prev, newIv])
    setExpandedCard(newIv.id)
  }, [workbench.length])

  const removeIntervention = useCallback((id: string) => {
    setWorkbench(prev => prev.filter(iv => iv.id !== id))
    setExpandedCard(prev => prev === id ? null : prev)
  }, [])

  const updateValue = useCallback((id: string, value: string) => {
    setWorkbench(prev => prev.map(iv => iv.id === id ? { ...iv, value } : iv))
  }, [])

  const canAdd = workbench.length < 3

  return (
    <div className="space-y-6">
      <GlassCard className="border-dashed">
        <div className="text-center mb-6">
          <h2 className="text-lg font-semibold text-foreground">What would you like to try?</h2>
          <p className="text-sm text-muted-foreground mt-1">
            You can change up to 3 things at once. Click options from the tray below to add them to the workbench.
          </p>
        </div>

        <AnimatePresence mode="popLayout">
          {workbench.length === 0 ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="border-2 border-dashed border-border-light rounded-xl py-12 text-center"
            >
              <p className="text-muted-foreground text-sm">Click interventions below to begin.</p>
            </motion.div>
          ) : (
            <motion.div layout className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              {workbench.map((iv) => {
                const type = INTERVENTION_TYPES.find(t => t.domain === iv.domain)!
                const cfg = DOMAIN_VALUES[iv.domain]
                const Icon = type.icon
                return (
                  <motion.div
                    key={iv.id}
                    layout
                    initial={{ opacity: 0, y: -12, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className={cn(
                      'bg-glass rounded-xl p-4 border border-border-light border-l-4',
                      type.color,
                    )}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Icon className="w-4 h-4 text-foreground" />
                        <span className="text-sm font-medium text-foreground">{type.label}</span>
                      </div>
                      <button
                        onClick={() => removeIntervention(iv.id)}
                        className="text-muted-foreground hover:text-destructive transition-colors cursor-pointer"
                        aria-label="Remove"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                    {cfg.options.length > 0 ? (
                      <div className="space-y-1.5">
                        {cfg.options.map((opt) => (
                          <button
                            key={opt}
                            onClick={() => updateValue(iv.id, opt)}
                            className={cn(
                              'block w-full text-left px-3 py-2 rounded-lg text-xs transition-all cursor-pointer',
                              iv.value === opt
                                ? 'bg-primary/20 text-primary border border-primary/30'
                                : 'bg-glass-hover text-muted-foreground hover:text-foreground border border-transparent',
                            )}
                          >
                            {opt}
                          </button>
                        ))}
                      </div>
                    ) : (
                      <input
                        className="w-full px-3 py-2 rounded-lg text-xs bg-glass-hover text-foreground border border-border-light outline-none focus:border-primary/40"
                        placeholder={cfg.placeholder}
                        value={iv.value}
                        onChange={(e) => updateValue(iv.id, e.target.value)}
                      />
                    )}
                  </motion.div>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            {workbench.length} of 3 selected
          </span>
          <Button
            onClick={() => onSimulate(workbench)}
            disabled={workbench.length === 0 || loading}
            loading={loading}
          >
            <Play className="w-4 h-4" />
            Run simulation
          </Button>
        </div>
      </GlassCard>

      <div>
        <p className="text-xs text-muted-foreground mb-3 uppercase tracking-wider font-semibold">
          Intervention tray
        </p>
        <div className="grid grid-cols-4 sm:grid-cols-8 gap-2">
          {INTERVENTION_TYPES.map((type) => {
            const Icon = type.icon
            const isOnBench = workbench.some(iv => iv.domain === type.domain)
            return (
              <button
                key={type.domain}
                onClick={() => addIntervention(type.domain)}
                disabled={!canAdd || isOnBench}
                title={!canAdd ? 'Maximum 3 changes at a time' : isOnBench ? 'Already added' : type.label}
                className={cn(
                  'flex flex-col items-center gap-1.5 p-3 rounded-xl text-xs transition-all cursor-pointer',
                  'border border-border-light',
                  isOnBench
                    ? 'bg-primary/10 border-primary/30 text-primary'
                    : canAdd
                      ? 'bg-glass hover:bg-glass-hover text-muted-foreground hover:text-foreground'
                      : 'bg-glass/50 text-muted-foreground/40 cursor-not-allowed border-border-light/50',
                )}
              >
                <Icon className="w-5 h-5" />
                <span className="leading-tight text-center">{type.label.split(' ')[0]}</span>
              </button>
            )
          })}
        </div>
      </div>

      <p className="text-xs text-muted-foreground/60 text-center">
        This tool helps you explore possible outcomes. It does not make decisions.
        Always discuss intervention plans with your supervisor before acting.
      </p>
    </div>
  )
}
