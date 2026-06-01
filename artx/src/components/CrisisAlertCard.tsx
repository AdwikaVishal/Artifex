/**
 * CrisisAlertCard – displays the 21-day disruption risk prediction for a placement.
 *
 * Shows probability, risk level, top contributing reasons, and recommended
 * interventions. Supports a manual refresh button.
 */
import { AlertTriangle, TrendingUp, Minus, RefreshCw } from 'lucide-react'
import { useCrisisPrediction, useRefreshCrisisPrediction } from '@/hooks/use-foster'
import { cn } from '@/lib/utils'

interface CrisisAlertCardProps {
  placementId: string
  /** Optional CSS class override */
  className?: string
}

const RISK_STYLES = {
  low: 'bg-green-500/10 border-green-500/40 text-green-400',
  medium: 'bg-yellow-500/10 border-yellow-500/40 text-yellow-400',
  high: 'bg-orange-500/10 border-orange-500/40 text-orange-400',
  critical: 'bg-red-500/10 border-red-500/40 text-red-400',
} as const

const RISK_ICONS = {
  low: <Minus className="w-4 h-4" />,
  medium: <TrendingUp className="w-4 h-4" />,
  high: <TrendingUp className="w-4 h-4" />,
  critical: <AlertTriangle className="w-4 h-4 animate-pulse" />,
} as const

export function CrisisAlertCard({ placementId, className }: CrisisAlertCardProps) {
  const { data: prediction, isLoading, error } = useCrisisPrediction(placementId)
  const { mutate: refresh, isPending: refreshing } = useRefreshCrisisPrediction()

  if (isLoading) {
    return (
      <div
        className={cn(
          'animate-pulse h-32 rounded-xl bg-gray-800/50 border border-gray-700',
          className
        )}
      />
    )
  }

  if (error || !prediction) {
    return null
  }

  const level = prediction.risk_level ?? 'low'
  const styles = RISK_STYLES[level] ?? RISK_STYLES.low
  const icon = RISK_ICONS[level] ?? RISK_ICONS.low

  return (
    <div className={cn('rounded-xl border p-4', styles, className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold">Crisis Risk Prediction</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold tabular-nums">
            {prediction.probability.toFixed(0)}%
          </span>
          <button
            onClick={() => refresh(placementId)}
            disabled={refreshing}
            title="Refresh prediction"
            className="opacity-60 hover:opacity-100 transition-opacity"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', refreshing && 'animate-spin')} />
          </button>
        </div>
      </div>

      <p className="text-xs opacity-70 mb-3">
        Risk of placement disruption in the next 21 days
      </p>

      {/* Top reasons */}
      {prediction.top_reasons.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] uppercase tracking-wider opacity-60 mb-1">
            Contributing factors
          </p>
          <ul className="space-y-0.5">
            {prediction.top_reasons.map((r, i) => (
              <li key={i} className="text-xs flex items-start gap-1.5">
                <span className="opacity-50 shrink-0">•</span>
                <span>{r.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Interventions */}
      {prediction.recommended_interventions.length > 0 && (
        <div className="pt-2 border-t border-current/20">
          <p className="text-[10px] uppercase tracking-wider opacity-60 mb-1.5">
            Recommended interventions
          </p>
          <div className="flex flex-wrap gap-1.5">
            {prediction.recommended_interventions.map((intervention, idx) => (
              <span
                key={idx}
                className="text-[10px] px-2 py-0.5 bg-white/10 rounded-full"
              >
                {intervention}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
