import { motion } from 'framer-motion'
import { Check, X, Home, Percent, Lightbulb } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { DecisionData } from '@/types/orchestration'

interface DecisionExplainabilityProps {
  data: DecisionData | null
  visible: boolean
}

export default function DecisionExplainability({ data, visible }: DecisionExplainabilityProps) {
  if (!visible || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-xs text-muted-foreground">Awaiting decision...</p>
      </div>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="space-y-4"
    >
      <div className="flex items-center gap-3 p-3 rounded-lg bg-success/5 border border-success/20">
        <div className="w-10 h-10 rounded-lg bg-success/15 flex items-center justify-center">
          <Home size={20} className="text-success" />
        </div>
        <div className="flex-1">
          <p className="text-xs text-muted-foreground">Recommended Family</p>
          <p className="text-sm font-bold text-success">{data.recommendedFamily}</p>
        </div>
        <div className="text-right">
          <div className="flex items-center gap-1">
            <Percent size={12} className="text-success" />
            <span className="text-lg font-bold text-success">{data.matchScore}</span>
          </div>
          <p className="text-[10px] text-muted-foreground">Match Score</p>
        </div>
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5 mb-2">
          <Lightbulb size={12} className="text-warning" />
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Reasoning</span>
        </div>
        {data.reasons.map((reason, i) => (
          <motion.div
            key={reason.label}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.1 }}
            className={cn(
              'flex items-center gap-2.5 p-2 rounded-lg border transition-all',
              reason.satisfied
                ? 'border-success/15 bg-success/5'
                : 'border-destructive/15 bg-destructive/5 opacity-60'
            )}
          >
            <div
              className={cn(
                'w-5 h-5 rounded-full flex items-center justify-center',
                reason.satisfied ? 'bg-success/20' : 'bg-destructive/20'
              )}
            >
              {reason.satisfied ? (
                <Check size={10} className="text-success" />
              ) : (
                <X size={10} className="text-destructive" />
              )}
            </div>
            <span className={cn(
              'text-xs',
              reason.satisfied ? 'text-foreground' : 'text-muted-foreground'
            )}>
              {reason.label}
            </span>
          </motion.div>
        ))}
      </div>

      <div className="p-3 rounded-lg bg-primary/5 border border-primary/20">
        <p className="text-xs text-muted-foreground leading-relaxed">
          {data.explanation}
        </p>
      </div>
    </motion.div>
  )
}
