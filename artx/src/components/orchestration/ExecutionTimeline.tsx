import { motion, AnimatePresence } from 'framer-motion'
import { Check, Loader2, X, Circle } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ExecutionStep } from '@/types/orchestration'

interface ExecutionTimelineProps {
  steps: ExecutionStep[]
  horizontal?: boolean
}

const STATUS_ICONS = {
  pending: Circle,
  active: Loader2,
  completed: Check,
  error: X,
}

const STATUS_COLORS = {
  pending: 'text-muted border-muted/30',
  active: 'text-info border-info/30 bg-info/10',
  completed: 'text-success border-success/30 bg-success/10',
  error: 'text-destructive border-destructive/30 bg-destructive/10',
}

function VerticalTimeline({ steps }: { steps: ExecutionStep[] }) {
  return (
    <div className="space-y-0">
      <AnimatePresence mode="popLayout">
        {steps.map((step, i) => {
          const Icon = STATUS_ICONS[step.status]
          const isActive = step.status === 'active'
          const isLast = i === steps.length - 1
          return (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.3, delay: i * 0.05 }}
              className="relative flex gap-4 pb-2"
            >
              {!isLast && (
                <div
                  className={cn(
                    'absolute left-[15px] top-8 w-px h-[calc(100%-8px)] transition-colors duration-500',
                    step.status === 'completed'
                      ? 'bg-success'
                      : step.status === 'active'
                        ? 'bg-info'
                        : step.status === 'error'
                          ? 'bg-destructive'
                          : 'bg-border'
                  )}
                />
              )}
              <div className="relative flex flex-col items-center">
                <div
                  className={cn(
                    'relative w-8 h-8 rounded-full border-2 flex items-center justify-center transition-all duration-500',
                    STATUS_COLORS[step.status]
                  )}
                >
                  <Icon size={14} className={cn(isActive && 'animate-spin')} />
                </div>
              </div>
              <div className="flex-1 pb-4">
                <p
                  className={cn(
                    'text-sm font-medium transition-colors duration-300',
                    step.status === 'completed'
                      ? 'text-success'
                      : step.status === 'active'
                        ? 'text-info'
                        : step.status === 'error'
                          ? 'text-destructive'
                          : 'text-muted-foreground'
                  )}
                >
                  {step.label}
                </p>
                <p className="text-xs text-muted-foreground mt-0.5">{step.agentName}</p>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

function HorizontalTimeline({ steps }: { steps: ExecutionStep[] }) {
  return (
    <div className="w-full overflow-x-auto">
      <div className="flex items-start gap-0 min-w-max px-2 py-3">
        {steps.map((step, i) => {
          const Icon = STATUS_ICONS[step.status]
          const isActive = step.status === 'active'
          const isLast = i === steps.length - 1
          return (
            <motion.div
              key={step.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: i * 0.04 }}
              className="flex items-center"
            >
              <div className="flex flex-col items-center min-w-[100px]">
                <div
                  className={cn(
                    'relative w-9 h-9 rounded-full border-2 flex items-center justify-center transition-all duration-500 shrink-0',
                    STATUS_COLORS[step.status]
                  )}
                >
                  <Icon size={15} className={cn(isActive && 'animate-spin')} />
                </div>
                <p
                  className={cn(
                    'text-[11px] font-medium mt-1.5 text-center leading-tight transition-colors duration-300 max-w-[100px]',
                    step.status === 'completed'
                      ? 'text-success'
                      : step.status === 'active'
                        ? 'text-info'
                        : step.status === 'error'
                          ? 'text-destructive'
                          : 'text-muted-foreground'
                  )}
                >
                  {step.label}
                </p>
                {step.agentName && (
                  <p className="text-[10px] text-muted-foreground mt-0.5 text-center">
                    {step.agentName}
                  </p>
                )}
              </div>
              {!isLast && (
                <div
                  className={cn(
                    'h-px w-10 mx-1 transition-colors duration-500',
                    step.status === 'completed'
                      ? 'bg-success'
                      : step.status === 'active'
                        ? 'bg-info'
                        : step.status === 'error'
                          ? 'bg-destructive'
                          : 'bg-border'
                  )}
                />
              )}
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

export default function ExecutionTimeline({ steps, horizontal = false }: ExecutionTimelineProps) {
  if (horizontal) {
    return <HorizontalTimeline steps={steps} />
  }
  return <VerticalTimeline steps={steps} />
}
