import { motion } from 'framer-motion'
import { Play, Square, RotateCcw, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ReplayButtonProps {
  isReplaying: boolean
  hasReplayed: boolean
  onToggle: () => void
  disabled?: boolean
}

export default function ReplayButton({ isReplaying, hasReplayed, onToggle, disabled }: ReplayButtonProps) {
  return (
    <motion.button
      onClick={onToggle}
      disabled={disabled}
      whileHover={!disabled ? { scale: 1.03 } : {}}
      whileTap={!disabled ? { scale: 0.97 } : {}}
      className={cn(
        'relative group flex items-center gap-2.5 px-4 py-2 rounded-xl font-semibold text-xs transition-all duration-300 border overflow-hidden',
        isReplaying
          ? 'bg-destructive/10 border-destructive/30 text-destructive hover:bg-destructive/20'
          : hasReplayed
            ? 'bg-warning/10 border-warning/30 text-warning hover:bg-warning/20'
            : 'bg-gradient-to-r from-primary/20 to-accent/20 border-primary/30 text-primary hover:from-primary/30 hover:to-accent/30 hover:shadow-[0_0_24px_rgba(99,102,241,0.15)]',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      {!isReplaying && !hasReplayed && (
        <motion.div
          className="absolute inset-0 bg-gradient-to-r from-primary/10 via-accent/10 to-primary/10"
          animate={{ x: ['-100%', '100%'] }}
          transition={{ duration: 2.5, repeat: Infinity, ease: 'linear' }}
        />
      )}

      <div className="relative flex items-center gap-2">
        {isReplaying ? (
          <>
            <div className="flex items-center gap-0.5">
              <motion.span
                className="w-1 h-1 rounded-full bg-destructive"
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ duration: 1, repeat: Infinity }}
              />
              <motion.span
                className="w-1 h-1 rounded-full bg-destructive"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.33 }}
              />
              <motion.span
                className="w-1 h-1 rounded-full bg-destructive"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.66 }}
              />
            </div>
            <Square size={12} fill="currentColor" />
            <span>Stop Replay</span>
          </>
        ) : hasReplayed ? (
          <>
            <RotateCcw size={12} />
            <span>Replay Workflow</span>
          </>
        ) : (
          <>
            <Sparkles size={12} className="text-warning" />
            <Play size={10} fill="currentColor" />
            <span>Replay Workflow</span>
          </>
        )}
      </div>
    </motion.button>
  )
}
