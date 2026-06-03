import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import {
  Gauge,
  ListChecks,
  Timer,
  Bot,
  MessageSquare,
  ShieldAlert,
} from 'lucide-react'
import type { ExecutionMetrics } from '@/types/workflow-timeline'

interface ExecutionMetricsBarProps {
  metrics: ExecutionMetrics
  loading?: boolean
}

function MetricCard({
  icon: Icon,
  label,
  value,
  valueClassName,
  sublabel,
}: {
  icon: React.ElementType
  label: string
  value: string | number
  valueClassName?: string
  sublabel?: string
}) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-glass-border bg-glass hover:bg-glass-hover transition-colors">
      <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
        <Icon size={16} className="text-primary" />
      </div>
      <div className="min-w-0">
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
        <motion.p
          key={String(value)}
          initial={{ scale: 1.2, opacity: 0.5 }}
          animate={{ scale: 1, opacity: 1 }}
          className={cn('text-lg font-bold font-mono', valueClassName || 'text-foreground')}
        >
          {value}
        </motion.p>
        {sublabel && (
          <p className="text-[10px] text-muted-foreground">{sublabel}</p>
        )}
      </div>
    </div>
  )
}

export default function ExecutionMetricsBar({ metrics, loading }: ExecutionMetricsBarProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-[68px] rounded-lg bg-surface-alt border border-border animate-pulse" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      <MetricCard
        icon={Gauge}
        label="Workflow Progress"
        value={`${Math.round(metrics.progress)}%`}
        valueClassName={
          metrics.progress >= 80 ? 'text-success' :
          metrics.progress >= 40 ? 'text-warning' :
          'text-muted-foreground'
        }
        sublabel={`${metrics.completedStages}/${metrics.totalStages} stages`}
      />
      <MetricCard
        icon={ListChecks}
        label="Completed Stages"
        value={`${metrics.completedStages}/${metrics.totalStages}`}
        valueClassName={
          metrics.completedStages === metrics.totalStages ? 'text-success' : 'text-info'
        }
      />
      <MetricCard
        icon={Timer}
        label="Execution Time"
        value={`${metrics.executionTime.toFixed(1)}s`}
        valueClassName="text-secondary"
      />
      <MetricCard
        icon={Bot}
        label="Active Agents"
        value={metrics.activeAgents}
      />
      <MetricCard
        icon={MessageSquare}
        label="Messages"
        value={metrics.messagesExchanged}
      />
      <MetricCard
        icon={ShieldAlert}
        label="Risk Score"
        value={metrics.riskScore}
        valueClassName={
          metrics.riskScore <= 30 ? 'text-success' :
          metrics.riskScore <= 60 ? 'text-warning' :
          'text-destructive'
        }
        sublabel={`Match: ${metrics.matchScore}%`}
      />
    </div>
  )
}
