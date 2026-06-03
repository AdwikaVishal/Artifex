import { useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { AgentMessage } from '@/types/orchestration'
import { Bot, ArrowRight, AlertCircle, CheckCircle2, Info, AlertTriangle } from 'lucide-react'

interface LiveEventPanelProps {
  messages: AgentMessage[]
}

const TYPE_CONFIG = {
  info: { icon: Info, color: 'text-info border-info/20 bg-info/5' },
  success: { icon: CheckCircle2, color: 'text-success border-success/20 bg-success/5' },
  error: { icon: AlertCircle, color: 'text-destructive border-destructive/20 bg-destructive/5' },
  warning: { icon: AlertTriangle, color: 'text-warning border-warning/20 bg-warning/5' },
}

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export default function LiveEventPanel({ messages }: LiveEventPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages.length])

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto space-y-1.5 pr-1 scroll-smooth"
    >
      <AnimatePresence initial={false}>
        {messages.length === 0 && (
          <div className="flex items-center justify-center h-full">
            <p className="text-xs text-muted-foreground">Waiting for agent events...</p>
          </div>
        )}
        {messages.map((msg) => {
          const config = TYPE_CONFIG[msg.type]
          const Icon = config.icon

          return (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: -10, height: 0 }}
              animate={{ opacity: 1, y: 0, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className={cn(
                'rounded-lg border p-2.5 transition-colors',
                config.color
              )}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span className="text-[10px] text-muted-foreground font-mono">
                  [{formatTime(msg.timestamp)}]
                </span>
              </div>
              <div className="flex items-start gap-2">
                <div className="flex items-center gap-1.5 mt-0.5 shrink-0">
                  <Bot size={12} className="text-muted-foreground" />
                  <span className="text-xs font-semibold text-foreground">{msg.from}</span>
                  <ArrowRight size={10} className="text-muted-foreground" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-muted-foreground leading-relaxed">{msg.content}</p>
                </div>
                <Icon size={12} className="shrink-0 mt-0.5 opacity-70" />
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
