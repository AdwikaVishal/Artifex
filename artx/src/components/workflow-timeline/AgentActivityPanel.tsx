import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '@/types/workflow-timeline'
import { Bot, Zap, Sparkles, BarChart3, Clock, ArrowRight } from 'lucide-react'

interface AgentActivityPanelProps {
  event: TimelineEvent | null
}

export default function AgentActivityPanel({ event }: AgentActivityPanelProps) {
  if (!event) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-12 text-center">
        <Bot size={32} className="text-muted mb-3" />
        <p className="text-sm text-muted-foreground">Select a stage to view agent activity</p>
        <p className="text-xs text-muted-foreground mt-1">Click any timeline event for details</p>
      </div>
    )
  }

  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={event.id}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.2 }}
        className="space-y-4"
      >
        {/* Agent header */}
        <div className={cn(
          'p-4 rounded-xl border',
          event.status === 'completed' ? 'border-success/20 bg-success/[0.02]' :
          event.status === 'in_progress' ? 'border-info/20 bg-info/[0.02]' :
          event.status === 'failed' ? 'border-destructive/20 bg-destructive/[0.02]' :
          'border-glass-border'
        )}>
          <div className="flex items-center gap-3 mb-3">
            <div className={cn(
              'w-10 h-10 rounded-lg flex items-center justify-center',
              event.status === 'completed' ? 'bg-success/15' :
              event.status === 'in_progress' ? 'bg-info/15' :
              'bg-primary/10'
            )}>
              <Bot size={20} className={
                event.status === 'completed' ? 'text-success' :
                event.status === 'in_progress' ? 'text-info' :
                'text-primary'
              } />
            </div>
            <div>
              <p className="text-sm font-semibold text-foreground">{event.agentName}</p>
              <p className="text-[10px] text-muted-foreground font-mono">{event.stage.replace(/_/g, ' ')}</p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center gap-2 p-2 rounded-lg bg-surface-alt border border-border">
              <Zap size={12} className="text-warning" />
              <div>
                <p className="text-[10px] text-muted-foreground">Action</p>
                <p className="text-xs text-foreground">{event.agentAction}</p>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-surface-alt border border-border">
              <Sparkles size={12} className="text-primary" />
              <div>
                <p className="text-[10px] text-muted-foreground">Output</p>
                <p className="text-xs text-foreground truncate">{event.agentOutput}</p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mt-3">
            <div className="flex items-center gap-2 p-2 rounded-lg bg-surface-alt border border-border">
              <Clock size={12} className="text-secondary" />
              <div>
                <p className="text-[10px] text-muted-foreground">Latency</p>
                <p className="text-xs font-mono text-foreground">{event.latency.toFixed(2)}s</p>
              </div>
            </div>
            <div className="flex items-center gap-2 p-2 rounded-lg bg-surface-alt border border-border">
              <BarChart3 size={12} className={
                event.confidenceScore >= 80 ? 'text-success' :
                event.confidenceScore >= 50 ? 'text-warning' : 'text-destructive'
              } />
              <div>
                <p className="text-[10px] text-muted-foreground">Confidence</p>
                <p className="text-xs font-mono text-foreground">{event.confidenceScore}%</p>
              </div>
            </div>
          </div>
        </div>

        {/* Reasoning */}
        {event.reasoning.length > 0 && (
          <div className="p-4 rounded-xl border border-glass-border">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-2">Agent Reasoning</p>
            <ul className="space-y-2">
              {event.reasoning.map((r, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                  <span className="w-5 h-5 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                    <ArrowRight size={8} className="text-primary" />
                  </span>
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Input/Output */}
        {(event.inputData || event.outputData) && (
          <div className="grid grid-cols-2 gap-3">
            {event.inputData && (
              <div className="p-3 rounded-xl border border-glass-border">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Input</p>
                <p className="text-xs text-muted-foreground">{event.inputData}</p>
              </div>
            )}
            {event.outputData && (
              <div className="p-3 rounded-xl border border-glass-border">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Output</p>
                <p className="text-xs text-muted-foreground">{event.outputData}</p>
              </div>
            )}
          </div>
        )}

        {/* Decision explanation */}
        {event.decisionExplanation && (
          <div className="p-4 rounded-xl border border-primary/20 bg-primary/[0.02]">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5 flex items-center gap-1.5">
              <Sparkles size={10} className="text-primary" />
              Decision Explanation
            </p>
            <p className="text-xs text-muted-foreground leading-relaxed">{event.decisionExplanation}</p>
          </div>
        )}

        {/* Logs */}
        {event.logs && event.logs.length > 0 && (
          <div className="p-4 rounded-xl border border-glass-border">
            <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-2">Execution Logs</p>
            <div className="space-y-1">
              {event.logs.map((log, i) => (
                <p key={i} className="text-[10px] font-mono text-muted-foreground bg-surface-alt px-2 py-1 rounded leading-relaxed">
                  {log}
                </p>
              ))}
            </div>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  )
}
