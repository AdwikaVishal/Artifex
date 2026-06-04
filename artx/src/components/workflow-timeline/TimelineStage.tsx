import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { TimelineEvent, StageStatus } from '@/types/workflow-timeline'
import {
  Check,
  Loader2,
  X,
  Circle,
  ChevronDown,
  Clock,
  Bot,
  Zap,
  BarChart3,
  Sparkles,
} from 'lucide-react'

interface TimelineStageProps {
  event: TimelineEvent
  index: number
  total: number
  isLast: boolean
  isSelected: boolean
  onClick: () => void
  isReplay?: boolean
}

const STATUS_ICONS: Record<StageStatus, React.ElementType> = {
  completed: Check,
  in_progress: Loader2,
  failed: X,
  pending: Circle,
}

const STATUS_COLORS: Record<StageStatus, string> = {
  completed: 'text-success border-success/30 bg-success/10',
  in_progress: 'text-info border-info/30 bg-info/10',
  failed: 'text-destructive border-destructive/30 bg-destructive/10',
  pending: 'text-muted border-border-light bg-surface-alt',
}

const STATUS_NODE_GLOW: Record<StageStatus, string> = {
  completed: 'shadow-[0_0_16px_rgba(16,185,129,0.4)]',
  in_progress: 'shadow-[0_0_20px_rgba(59,130,246,0.5)]',
  failed: 'shadow-[0_0_16px_rgba(239,68,68,0.4)]',
  pending: '',
}

const STATUS_LINE_COLOR: Record<StageStatus, string> = {
  completed: 'bg-success',
  in_progress: 'bg-info',
  failed: 'bg-destructive',
  pending: 'bg-border',
}

function formatTimestamp(ts?: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
}

function tryJsonParse(v: unknown): unknown {
  if (typeof v === 'string') {
    try { return JSON.parse(v) } catch { return v }
  }
  return v
}

function toPercent(v: unknown): string | null {
  const n = typeof v === 'number' ? v : typeof v === 'string' ? parseFloat(v) : NaN
  if (isNaN(n)) return null
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `${pct}%`
}

function renderValue(v: unknown): React.ReactNode {
  if (v == null) return <span className="text-muted-foreground">—</span>
  if (Array.isArray(v)) {
    return (
      <ul className="space-y-0.5 list-disc list-inside">
        {v.map((item, i) => (
          <li key={i}>{renderValue(item)}</li>
        ))}
      </ul>
    )
  }
  if (typeof v === 'object') {
    return (
      <div className="space-y-0.5">
        {Object.entries(v as Record<string, unknown>).map(([k, val]) => (
          <div key={k} className="flex gap-2 text-xs">
            <span className="text-muted-foreground shrink-0">{k.replace(/_/g, ' ')}:</span>
            <span className="text-foreground">{renderValue(val)}</span>
          </div>
        ))}
      </div>
    )
  }
  return <span>{String(v)}</span>
}

function ScoreCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex flex-col items-center p-2.5 rounded-lg border border-glass-border bg-surface-alt">
      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className={`text-lg font-bold font-mono ${color}`}>{value}</span>
    </div>
  )
}

function PayloadView({ payload }: { payload: Record<string, unknown> }) {
  const parsed = Object.fromEntries(
    Object.entries(payload).map(([k, v]) => [k, tryJsonParse(v)]),
  )
  const entries = Object.entries(parsed).filter(
    ([k]) => !['agent', 'progress', 'timestamp', 'action', 'output', 'input', 'latency', 'reasoning', 'logs', 'inputData', 'outputData', 'confidence', 'confidence_score', 'match_score', 'matchScore', 'risk_score', 'riskScore', 'details', 'message', 'domain', 'pending_simulations', 'outcome_summary', 'verdict', 'caseworker_note', 'saved_at', 'expires_at', 'simulation_id', 'interventions'].includes(k),
  )

  const matchScore = toPercent(payload.match_score ?? payload.matchScore ?? payload.match)
  const confidenceScore = toPercent(payload.confidence_score ?? payload.confidenceScore ?? payload.confidence)
  const riskScore = toPercent(payload.risk_score ?? payload.riskScore ?? payload.risk)
  const explanation = payload.decisionExplanation ?? payload.explanation ?? ''
  const family = payload.recommended_family ?? payload.family_name ?? payload.family ?? ''
  const familyId = payload.family_id ?? payload.familyId ?? ''

  return (
    <div className="space-y-3">
      {/* Recommended family */}
      {family && (
        <div className="p-3 rounded-lg border border-glass-border bg-surface-alt">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Recommended Family</p>
          <p className="text-sm font-medium text-foreground">
            {String(family)}
            {familyId && <span className="text-muted-foreground ml-1 text-xs">({String(familyId)})</span>}
          </p>
        </div>
      )}

      {/* Scores grid */}
      {(matchScore || confidenceScore || riskScore) && (
        <div className="grid grid-cols-3 gap-2">
          {matchScore && <ScoreCard label="Match" value={matchScore} color="text-info" />}
          {confidenceScore && <ScoreCard label="Confidence" value={confidenceScore} color="text-success" />}
          {riskScore && <ScoreCard label="Risk" value={riskScore} color={parseInt(riskScore) >= 70 ? 'text-destructive' : parseInt(riskScore) >= 40 ? 'text-warning' : 'text-success'} />}
        </div>
      )}

      {/* Decision explanation */}
      {explanation && (
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Decision Summary</p>
          <p className="text-xs text-muted-foreground bg-surface-alt p-2.5 rounded-lg border border-border leading-relaxed">
            {String(explanation)}
          </p>
        </div>
      )}

      {/* Remaining payload fields */}
      {entries.length > 0 && (
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Details</p>
          <div className="space-y-1">
            {entries.map(([k, v]) => (
              <div key={k} className="flex flex-col text-xs text-muted-foreground bg-surface-alt px-2.5 py-1.5 rounded border border-border">
                <span className="font-medium capitalize mb-0.5">{k.replace(/_/g, ' ')}</span>
                <div className="font-mono">{renderValue(v)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function TimelineStage({ event, index, isLast, isSelected, onClick, isReplay }: TimelineStageProps) {
  const [expanded, setExpanded] = useState(false)
  const Icon = STATUS_ICONS[event.status]
  const isActive = event.status === 'in_progress'
  const isCompleted = event.status === 'completed'
  const isFailed = event.status === 'failed'

  const hasDetails = event.reasoning.length > 0 || event.details || event.logs || event.payload || event.decisionExplanation

  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{
        duration: 0.45,
        delay: isReplay ? index * 0.12 : 0.08,
        ease: [0.25, 0.1, 0.25, 1],
      }}
      className={cn(
        'relative flex gap-4 cursor-pointer group',
        event.status === 'pending' && !isReplay && 'opacity-50'
      )}
      onClick={onClick}
    >
      {/* Connector line with SVG for animation */}
      {!isLast && (
        <div className="absolute left-[19px] top-10 w-0.5 bottom-0 overflow-hidden">
          <div
            className={cn(
              'absolute inset-0 transition-all duration-700',
              STATUS_LINE_COLOR[event.status]
            )}
            style={{
              height: isCompleted ? '100%' : isActive ? '60%' : '0%',
            }}
          />
          {!isCompleted && !isActive && (
            <div className="absolute inset-0 bg-border" />
          )}
        </div>
      )}

      {/* Status node */}
      <div className="relative shrink-0 pt-2">
        <motion.div
          animate={
            isActive
              ? { scale: [1, 1.15, 1] }
              : isCompleted
                ? { scale: [1, 1.1, 1] }
                : {}
          }
          transition={
            isActive
              ? { duration: 1.5, repeat: Infinity, ease: 'easeInOut' }
              : isCompleted
                ? { duration: 0.3 }
                : {}
          }
          className={cn(
            'w-10 h-10 rounded-full border-2 flex items-center justify-center transition-all duration-500',
            STATUS_COLORS[event.status],
            STATUS_NODE_GLOW[event.status],
            (isSelected || expanded) && 'ring-2 ring-primary/30 ring-offset-2 ring-offset-background'
          )}
        >
          <Icon
            size={16}
            className={cn(
              isActive && 'animate-spin'
            )}
          />
        </motion.div>

        {/* Animated glow ring for active stage */}
        {isActive && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-info/30"
            animate={{ scale: [1, 1.3, 1], opacity: [0.5, 0, 0.5] }}
            transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}
      </div>

      {/* Content card */}
      <div className={cn(
        'flex-1 min-w-0 pb-6 transition-all duration-300',
        event.status === 'pending' && !isReplay && 'opacity-50'
      )}>
        <motion.div
          layout
          initial={{ boxShadow: '0 0 0px rgba(99,102,241,0)' }}
          animate={{
            boxShadow: [
              '0 0 24px rgba(99,102,241,0.25)',
              '0 0 8px rgba(99,102,241,0.08)',
              '0 0 0px rgba(99,102,241,0)',
            ],
          }}
          transition={{ duration: 1.2, ease: 'easeOut', delay: isReplay ? index * 0.12 : 0.1 }}
          className={cn(
            'rounded-xl border transition-all duration-300 overflow-hidden',
            isSelected
              ? 'border-primary/40 bg-primary/[0.03] shadow-[0_0_20px_rgba(99,102,241,0.08)]'
              : isActive
                ? 'border-info/30 bg-info/[0.02]'
                : isCompleted
                  ? 'border-success/20 bg-success/[0.02]'
                  : isFailed
                    ? 'border-destructive/20 bg-destructive/[0.02]'
                    : 'border-glass-border bg-card hover:bg-card-hover'
          )}
        >
          {/* Header row */}
          <div className="p-3.5">
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={cn(
                    'text-sm font-semibold',
                    isCompleted ? 'text-success' : isActive ? 'text-info' : isFailed ? 'text-destructive' : 'text-foreground'
                  )}>
                    {event.label}
                  </span>
                  {isCompleted && (
                    <motion.span
                      initial={{ scale: 0 }}
                      animate={{ scale: 1 }}
                      className="px-1.5 py-0.5 rounded-full bg-success/15 text-success text-[10px] font-mono font-medium"
                    >
                      {event.latency.toFixed(2)}s
                    </motion.span>
                  )}
                </div>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Bot size={11} className="text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">{event.agentName}</span>
                  {event.timestamp && (
                    <>
                      <span className="text-muted">·</span>
                      <Clock size={10} className="text-muted-foreground" />
                      <span className="text-[10px] text-muted-foreground font-mono">{formatTimestamp(event.timestamp)}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Confidence badge */}
              {event.confidenceScore > 0 && (
                <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-surface-alt border border-border shrink-0">
                  <BarChart3 size={10} className="text-muted-foreground" />
                  <span className="text-[10px] font-mono font-medium text-foreground">{event.confidenceScore}%</span>
                </div>
              )}
            </div>

            {/* Action & Output */}
            {(event.agentAction || event.agentOutput) && (
              <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {event.agentAction && (
                  <div className="flex items-center gap-1">
                    <Zap size={10} className="text-warning" />
                    <span className="text-muted-foreground">{event.agentAction}</span>
                  </div>
                )}
                {event.agentOutput && (
                  <div className="flex items-center gap-1">
                    <Sparkles size={10} className="text-primary" />
                    <span className="text-muted-foreground">{event.agentOutput}</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Expanded details */}
          <AnimatePresence>
            {expanded && hasDetails && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="border-t border-glass-border"
              >
                <div className="p-3.5 space-y-3">

                  {/* ── Structured payload (scores, family, explanation) ── */}
                  {event.payload && (
                    <PayloadView payload={event.payload} />
                  )}

                  {/* ── Reasoning entries ── */}
                  {event.reasoning.length > 0 && (
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1.5">Reasoning</p>
                      <ul className="space-y-1">
                        {event.reasoning.map((r, i) => (
                          <li key={i} className="flex items-start gap-1.5 text-xs text-muted-foreground">
                            <span className="text-primary mt-0.5">•</span>
                            {r}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* ── Decision explanation (only if not already shown in payload) ── */}
                  {event.decisionExplanation && !event.payload?.decisionExplanation && (
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Decision Explanation</p>
                      <p className="text-xs text-muted-foreground bg-surface-alt p-2 rounded-lg border border-border">
                        {event.decisionExplanation}
                      </p>
                    </div>
                  )}

                  {/* ── Fallback details (parse JSON if string) ── */}
                  {event.details && !event.payload && (
                    <PayloadView
                      payload={
                        typeof event.details === 'string'
                          ? (() => { try { return JSON.parse(event.details) as Record<string, unknown> } catch { return { details: event.details } } })()
                          : event.details as Record<string, unknown>
                      }
                    />
                  )}

                  {/* ── Logs ── */}
                  {event.logs && event.logs.length > 0 && (
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold mb-1">Logs</p>
                      <div className="space-y-0.5">
                        {event.logs.map((log, i) => (
                          <p key={i} className="text-[10px] font-mono text-muted-foreground bg-surface-alt px-2 py-1 rounded">
                            {log}
                          </p>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Expand toggle */}
          {hasDetails && (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
              className={cn(
                'flex items-center justify-center w-full py-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors border-t',
                expanded ? 'border-glass-border' : 'border-transparent'
              )}
            >
              <motion.div
                animate={{ rotate: expanded ? 180 : 0 }}
                transition={{ duration: 0.2 }}
              >
                <ChevronDown size={12} />
              </motion.div>
              <span className="ml-1">{expanded ? 'Hide details' : 'Show details'}</span>
            </button>
          )}
        </motion.div>
      </div>
    </motion.div>
  )
}
