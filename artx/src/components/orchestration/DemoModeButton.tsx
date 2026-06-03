import { motion } from 'framer-motion'
import { Play, Square, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

interface DemoModeButtonProps {
  isRunning: boolean
  onToggle: () => void
}

export default function DemoModeButton({ isRunning, onToggle }: DemoModeButtonProps) {
  return (
    <motion.button
      onClick={onToggle}
      whileHover={{ scale: 1.03 }}
      whileTap={{ scale: 0.97 }}
      className={cn(
        'relative group flex items-center gap-2.5 px-5 py-2.5 rounded-xl font-semibold text-sm transition-all duration-300 border overflow-hidden',
        isRunning
          ? 'bg-destructive/10 border-destructive/30 text-destructive hover:bg-destructive/20'
          : 'bg-gradient-to-r from-primary/20 to-accent/20 border-primary/30 text-primary hover:from-primary/30 hover:to-accent/30 hover:shadow-[0_0_30px_rgba(99,102,241,0.2)]'
      )}
    >
      {!isRunning && (
        <motion.div
          className="absolute inset-0 bg-gradient-to-r from-primary/10 via-accent/10 to-primary/10"
          animate={{ x: ['-100%', '100%'] }}
          transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
        />
      )}

      <div className="relative flex items-center gap-2.5">
        {isRunning ? (
          <>
            <div className="flex items-center gap-1">
              <motion.div
                className="w-1.5 h-1.5 rounded-full bg-destructive"
                animate={{ opacity: [1, 0.3, 1] }}
                transition={{ duration: 1, repeat: Infinity }}
              />
              <motion.div
                className="w-1.5 h-1.5 rounded-full bg-destructive"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.33 }}
              />
              <motion.div
                className="w-1.5 h-1.5 rounded-full bg-destructive"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.66 }}
              />
            </div>
            <Square size={14} fill="currentColor" />
            <span>Stop Demo</span>
          </>
        ) : (
          <>
            <Sparkles size={16} className="text-warning" />
            <Play size={14} fill="currentColor" />
            <span>Demo Mode</span>
          </>
        )}
      </div>
    </motion.button>
  )
}
