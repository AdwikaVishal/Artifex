import { motion, AnimatePresence } from 'framer-motion'
import { X, Bot, Zap, Sparkles, BarChart3, Clock, ArrowRight, FileText, Terminal } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { TimelineEvent } from '@/types/workflow-timeline'

interface TimelineDetailDrawerProps {
  event: TimelineEvent | null
  onClose: () => void
}

export default function TimelineDetailDrawer({ event, onClose }: TimelineDetailDrawerProps) {
  return (
    <AnimatePresence>
      {event && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-50 flex justify-end"
        >
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={onClose}
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 250 }}
            className="relative w-full max-w-lg bg-background border-l border-glass-border overflow-y-auto"
          >
            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between p-4 border-b border-glass-border bg-background/80 backdrop-blur-xl">
              <div className="flex items-center gap-2">
                <div className={cn(
                  'w-8 h-8 rounded-lg flex items-center justify-center',
                  event.status === 'completed' ? 'bg-success/15' :
                  event.status === 'in_progress' ? 'bg-info/15' :
                  'bg-primary/10'
                )}>
                  <Bot size={16} className={
                    event.status === 'completed' ? 'text-success' :
                    event.status === 'in_progress' ? 'text-info' :
                    'text-primary'
                  } />
                </div>
                <div>
                  <p className="text-sm font-semibold text-foreground">{event.label}</p>
                  <p className="text-[10px] text-muted-foreground">{event.agentName}</p>
                </div>
              </div>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-lg flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-glass-hover transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Content */}
            <div className="p-4 space-y-5">
              {/* Stage info */}
              <Section icon={FileText} title="Stage Information">
                <div className="grid grid-cols-2 gap-3">
                  <InfoItem label="Stage" value={event.stage.replace(/_/g, ' ')} />
                  <InfoItem label="Status" value={event.status} />
                  <InfoItem label="Agent" value={event.agentName} />
                  <InfoItem label="Latency" value={`${event.latency.toFixed(2)}s`} />
                  <InfoItem label="Confidence" value={`${event.confidenceScore}%`} />
                  {event.timestamp && <InfoItem label="Timestamp" value={new Date(event.timestamp).toLocaleString()} />}
                  {event.startedAt && <InfoItem label="Started" value={new Date(event.startedAt).toLocaleTimeString()} />}
                  {event.completedAt && <InfoItem label="Completed" value={new Date(event.completedAt).toLocaleTimeString()} />}
                </div>
              </Section>

              {/* Agent Reasoning */}
              {event.reasoning.length > 0 && (
                <Section icon={ArrowRight} title="Agent Reasoning">
                  <ul className="space-y-2">
                    {event.reasoning.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
                        <span className="w-4 h-4 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                          <ArrowRight size={6} className="text-primary" />
                        </span>
                        {r}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              {/* Input / Output */}
              <div className="grid grid-cols-2 gap-3">
                {event.inputData && (
                  <Section icon={Zap} title="Input Data" compact>
                    <p className="text-xs text-muted-foreground">{event.inputData}</p>
                  </Section>
                )}
                {event.outputData && (
                  <Section icon={Sparkles} title="Output Data" compact>
                    <p className="text-xs text-muted-foreground">{event.outputData}</p>
                  </Section>
                )}
              </div>

              {/* Decision Explanation */}
              {event.decisionExplanation && (
                <Section icon={BarChart3} title="Decision Explanation">
                  <p className="text-xs text-muted-foreground leading-relaxed">{event.decisionExplanation}</p>
                </Section>
              )}

              {/* Logs */}
              {event.logs && event.logs.length > 0 && (
                <Section icon={Terminal} title="Logs">
                  <div className="space-y-1">
                    {event.logs.map((log, i) => (
                      <p key={i} className="text-[10px] font-mono text-muted-foreground bg-surface-alt px-2 py-1 rounded">
                        {log}
                      </p>
                    ))}
                  </div>
                </Section>
              )}

              {/* Details */}
              {event.details && (
                <Section icon={FileText} title="Additional Details">
                  <p className="text-xs text-muted-foreground">{event.details}</p>
                </Section>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function Section({
  icon: Icon,
  title,
  children,
  compact,
}: {
  icon: React.ElementType
  title: string
  children: React.ReactNode
  compact?: boolean
}) {
  return (
    <div className={cn(compact ? '' : 'p-4 rounded-xl border border-glass-border')}>
      <div className="flex items-center gap-1.5 mb-2">
        <Icon size={11} className="text-primary" />
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">{title}</p>
      </div>
      {children}
    </div>
  )
}

function InfoItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-2 rounded-lg bg-surface-alt border border-border">
      <p className="text-[10px] text-muted-foreground">{label}</p>
      <p className="text-xs font-medium text-foreground truncate capitalize">{value}</p>
    </div>
  )
}
