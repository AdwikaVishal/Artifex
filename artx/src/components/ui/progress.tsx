import { cn } from '@/lib/utils'

interface ProgressProps {
  value: number
  className?: string
  variant?: 'default' | 'success' | 'warning' | 'error'
  size?: 'sm' | 'md' | 'lg'
  showLabel?: boolean
}

export function Progress({ value, className, variant = 'default', size = 'md', showLabel }: ProgressProps) {
  const colors = {
    default: 'bg-primary',
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-destructive',
  }

  const heights = { sm: 'h-1', md: 'h-1.5', lg: 'h-2' }

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className={cn('flex-1 rounded-full bg-surface-alt overflow-hidden', heights[size])}>
        <div
          className={cn('h-full rounded-full transition-all duration-500 ease-out', colors[variant])}
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs text-muted-foreground font-mono">{Math.round(value)}%</span>
      )}
    </div>
  )
}

interface AnimatedProgressStepProps {
  stages: { name: string; label: string; status: 'pending' | 'in_progress' | 'completed' | 'failed' }[]
  currentStage?: string
}

export function AnimatedProgressSteps({ stages, currentStage }: AnimatedProgressStepProps) {
  return (
    <div className="relative">
      <div className="absolute top-4 left-6 right-6 h-0.5 bg-surface-alt">
        <div
          className="h-full bg-gradient-to-r from-primary to-secondary transition-all duration-700"
          style={{
            width: `${(stages.filter((s) => s.status === 'completed').length / Math.max(stages.length - 1, 1)) * 100}%`,
          }}
        />
      </div>
      <div className="relative flex justify-between">
        {stages.map((stage, i) => {
          const isCompleted = stage.status === 'completed'
          const isActive = stage.status === 'in_progress' || stage.name === currentStage
          const isFailed = stage.status === 'failed'

          return (
            <div key={stage.name} className="flex flex-col items-center gap-2">
              <div
                className={cn(
                  'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all duration-300',
                  isCompleted && 'bg-primary border-primary text-white',
                  isActive && !isCompleted && 'border-primary text-primary bg-primary/10',
                  isFailed && 'border-destructive text-destructive bg-destructive/10',
                  !isCompleted && !isActive && !isFailed && 'border-border-light text-muted bg-surface-alt'
                )}
              >
                {isCompleted ? '✓' : isFailed ? '✕' : i + 1}
              </div>
              <span
                className={cn(
                  'text-xs text-center max-w-24 leading-tight transition-colors',
                  isCompleted && 'text-primary',
                  isActive && !isCompleted && 'text-foreground',
                  isFailed && 'text-destructive',
                  !isCompleted && !isActive && !isFailed && 'text-muted'
                )}
              >
                {stage.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
