import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { AgentNodeData, AgentStatus } from '@/types/orchestration'
import {
  FilePlus,
  GitBranch,
  ShieldAlert,
  Users,
  Scale,
  CheckCheck,
  Activity,
  Check,
  type LucideIcon,
} from 'lucide-react'

const AGENT_ICONS: Record<string, LucideIcon> = {
  intake: FilePlus,
  planner: GitBranch,
  risk: ShieldAlert,
  matching: Users,
  fairness: Scale,
  approval: CheckCheck,
  monitoring: Activity,
}

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: 'bg-muted',
  active: 'bg-info shadow-[0_0_12px_rgba(59,130,246,0.6)]',
  completed: 'bg-success shadow-[0_0_12px_rgba(16,185,129,0.6)]',
  error: 'bg-destructive shadow-[0_0_12px_rgba(239,68,68,0.6)]',
}

const STATUS_GLOW: Record<AgentStatus, string> = {
  idle: '',
  active: 'shadow-[0_0_30px_rgba(59,130,246,0.15)] border-info/40',
  completed: 'shadow-[0_0_30px_rgba(16,185,129,0.15)] border-success/40',
  error: 'shadow-[0_0_30px_rgba(239,68,68,0.15)] border-destructive/40',
}

function AgentNode({ data }: NodeProps<any>) {
  const nodeData = (data ?? {}) as AgentNodeData
  const Icon = AGENT_ICONS[nodeData.type] || Activity
  const isActive = nodeData.status === 'active'
  const isCompleted = nodeData.status === 'completed'

  return (
    <motion.div
      animate={
        isActive
          ? { scale: [1, 1.15, 1], rotateZ: [0, 0.2, 0] }
          : isCompleted
            ? { scale: 1.02 }
            : { scale: 1 }
      }
      transition={
        isActive
          ? { duration: 1.35, repeat: Infinity, ease: 'easeInOut' }
          : { duration: 0.35, ease: 'easeOut' }
      }
      className={cn(
        'relative min-w-[260px] w-[260px] min-h-[140px] rounded-[24px] border px-4 py-4 backdrop-blur-2xl shadow-[0_16px_40px_rgba(15,23,42,0.35)] transition-all duration-500',
        'bg-[linear-gradient(145deg,rgba(15,23,42,0.95),rgba(17,24,39,0.86))]',
        STATUS_GLOW[nodeData.status],
        isActive ? 'border-info/60 shadow-[0_18px_50px_rgba(56,189,248,0.18)]' : isCompleted ? 'border-success/60 shadow-[0_18px_50px_rgba(16,185,129,0.18)]' : 'border-white/10'
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-primary/50 !w-3 !h-3 !border-2 !border-background" />
      <Handle type="source" position={Position.Bottom} className="!bg-primary/50 !w-3 !h-3 !border-2 !border-background" />

      {isCompleted && (
        <span className="absolute -right-2 -top-2 flex h-8 w-8 items-center justify-center rounded-full border border-success/40 bg-success/15 text-success shadow-[0_0_18px_rgba(16,185,129,0.25)]">
          <Check size={14} />
        </span>
      )}

      <div className="flex items-center gap-3">
        <div
          className={cn(
            'relative h-12 w-12 rounded-2xl flex items-center justify-center shrink-0 border border-white/8',
            isActive ? 'bg-info/20' : isCompleted ? 'bg-success/20' : 'bg-glass'
          )}
        >
          <Icon
            size={20}
            className={cn(
              isActive ? 'text-info' : isCompleted ? 'text-success' : 'text-muted-foreground'
            )}
          />
          {isActive && (
            <motion.div
              className="absolute inset-0 rounded-lg border-2 border-info/40"
              animate={{ opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 1.5, repeat: Infinity, ease: 'easeInOut' }}
            />
          )}
        </div>

        <div className="flex-1 min-w-0">
          <p className={cn(
            'text-[13px] font-semibold tracking-wide truncate',
            isActive ? 'text-info' : isCompleted ? 'text-success' : 'text-foreground'
          )}>
            {nodeData.name}
          </p>
          <p className="text-[11px] uppercase tracking-[0.24em] text-muted-foreground">{nodeData.type} agent</p>
        </div>

        <div className="flex flex-col items-center gap-1">
          <div className={cn(
            'h-3 w-3 rounded-full ring-2 ring-black/30 transition-all duration-500',
            STATUS_COLORS[nodeData.status]
          )} />
          <span className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground">{nodeData.status}</span>
        </div>
      </div>

      {nodeData.confidence !== undefined && (
        <div className="mt-3 pt-3 border-t border-glass-border">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Confidence</span>
            <span className={cn(
              'font-mono font-medium',
              nodeData.confidence >= 80 ? 'text-success' : nodeData.confidence >= 50 ? 'text-warning' : 'text-destructive'
            )}>
              {nodeData.confidence}%
            </span>
          </div>
          <div className="mt-1.5 h-1 rounded-full bg-surface-alt overflow-hidden">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${nodeData.confidence}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
              className={cn(
                'h-full rounded-full',
                nodeData.confidence >= 80 ? 'bg-success' : nodeData.confidence >= 50 ? 'bg-warning' : 'bg-destructive'
              )}
            />
          </div>
        </div>
      )}
    </motion.div>
  )
}

export default memo(AgentNode)
