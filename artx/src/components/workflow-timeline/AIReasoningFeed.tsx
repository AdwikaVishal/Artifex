import { motion, AnimatePresence } from 'framer-motion'
import type { ReasoningEntry } from '@/types/workflow-timeline'
import { Bot, ArrowRight, Clock } from 'lucide-react'

interface AIReasoningFeedProps {
  entries: ReasoningEntry[]
  maxVisible?: number
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch {
    return ''
  }
}

export default function AIReasoningFeed({ entries, maxVisible = 50 }: AIReasoningFeedProps) {
  const visible = entries.slice(-maxVisible)

  if (visible.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-12 text-center">
        <Bot size={28} className="text-muted mb-2" />
        <p className="text-xs text-muted-foreground">No AI reasoning available yet</p>
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <AnimatePresence mode="popLayout">
        {visible.map((entry, i) => (
          <motion.div
            key={entry.id}
            initial={{ opacity: 0, y: -8, height: 0 }}
            animate={{ opacity: 1, y: 0, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="p-2.5 rounded-lg border border-glass-border bg-glass hover:bg-glass-hover transition-colors"
          >
            <div className="flex items-center gap-1.5 mb-1">
              <Clock size={10} className="text-muted-foreground" />
              <span className="text-[10px] font-mono text-muted-foreground">{formatTime(entry.timestamp)}</span>
              <span className="text-muted">·</span>
              <Bot size={10} className="text-primary" />
              <span className="text-[10px] font-semibold text-foreground">{entry.agentName}</span>
              <ArrowRight size={8} className="text-muted-foreground" />
            </div>
            <p className="text-xs text-muted-foreground ml-0.5 leading-relaxed">{entry.content}</p>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
