import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { AgentType, AgentMetrics } from '@/types/orchestration'
import {
  FilePlus,
  GitBranch,
  ShieldAlert,
  Users,
  Scale,
  CheckCheck,
  Activity,
  type LucideIcon,
} from 'lucide-react'

interface AgentPerformancePanelProps {
  metrics: Record<AgentType, AgentMetrics>
  visible: boolean
}

const AGENT_ICONS: Record<string, LucideIcon> = {
  intake: FilePlus,
  planner: GitBranch,
  risk: ShieldAlert,
  matching: Users,
  fairness: Scale,
  approval: CheckCheck,
  monitoring: Activity,
}

const AGENT_LABELS: Record<AgentType, string> = {
  intake: 'Intake Agent',
  planner: 'Planner Agent',
  risk: 'Risk Agent',
  matching: 'Matching Agent',
  fairness: 'Fairness Agent',
  approval: 'Approval Agent',
  monitoring: 'Monitoring Agent',
}

function MetricBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-muted-foreground w-20 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-surface-alt overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(pct, 100)}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className={cn(
            'h-full rounded-full',
            pct >= 80 ? 'bg-success' : pct >= 50 ? 'bg-warning' : 'bg-info'
          )}
        />
      </div>
      <span className="text-[10px] font-mono text-foreground w-12 text-right">{value}</span>
    </div>
  )
}

export default function AgentPerformancePanel({ metrics, visible }: AgentPerformancePanelProps) {
  if (!visible) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-xs text-muted-foreground">Waiting for agent metrics...</p>
      </div>
    )
  }

  const agentTypes = Object.keys(metrics) as AgentType[]

  return (
    <div className="space-y-1">
      {agentTypes.map((type, idx) => {
        const m = metrics[type]
        const Icon = AGENT_ICONS[type]
        if (!m || m.tasksCompleted === 0 && m.messagesProcessed === 0) return null

        return (
          <motion.div
            key={type}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.05 }}
            className="p-2.5 rounded-lg border border-glass-border bg-glass hover:bg-glass-hover transition-colors"
          >
            <div className="flex items-center gap-2 mb-2">
              <div className="w-6 h-6 rounded-md bg-primary/10 flex items-center justify-center">
                <Icon size={12} className="text-primary" />
              </div>
              <span className="text-xs font-semibold text-foreground">{AGENT_LABELS[type]}</span>
            </div>
            <div className="space-y-1">
              <MetricBar label="Success Rate" value={m.successRate} max={100} />
              <MetricBar label="Confidence" value={m.confidenceScore} max={100} />
              <MetricBar label="Tasks" value={m.tasksCompleted} max={Math.max(m.tasksCompleted, 10)} />
            </div>
            <div className="flex items-center justify-between mt-1.5 pt-1.5 border-t border-glass-border">
              <span className="text-[10px] text-muted-foreground">
                Avg: <span className="text-foreground font-mono">{m.avgResponseTime.toFixed(1)}s</span>
              </span>
              <span className="text-[10px] text-muted-foreground">
                Messages: <span className="text-foreground font-mono">{m.messagesProcessed}</span>
              </span>
            </div>
          </motion.div>
        )
      })}
      {agentTypes.every(t => !metrics[t] || (metrics[t].tasksCompleted === 0 && metrics[t].messagesProcessed === 0)) && (
        <div className="flex items-center justify-center h-full">
          <p className="text-xs text-muted-foreground">No agent activity yet</p>
        </div>
      )}
    </div>
  )
}
