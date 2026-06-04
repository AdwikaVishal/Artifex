/**
 * FairnessDashboard – displays AI bias audit metrics across demographic groups.
 *
 * Shows disparity rates for gender, special needs, and emergency level,
 * with per-group breakdowns and a pass/review status badge.
 */
import { Shield, CheckCircle, AlertCircle, AlertTriangle, BarChart3, RefreshCw } from 'lucide-react'
import { useFairnessMetrics } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { DataLoader } from '@/components/data-loader'
import { cn } from '@/lib/utils'
import { useQueryClient } from '@tanstack/react-query'
import type { FairnessGroupBreakdown } from '@/services/foster'

const MIN_RELIABLE_SAMPLE = 30

function confidenceLevel(n: number): 'none' | 'low' | 'medium' | 'high' {
  if (n < 5) return 'none'
  if (n < 30) return 'low'
  if (n < 100) return 'medium'
  return 'high'
}

function getDiversityWarning(key: string, groups: FairnessGroupBreakdown[]): string | null {
  if (groups.length >= 2) return null
  if (groups.length === 0) return 'No data available'
  const groupName = groups[0].group
  if (key === 'special_needs') {
    return groupName === 'false' || groupName === 'False'
      ? 'No placements in special-needs group'
      : 'No placements without special needs'
  }
  if (key === 'emergency_level') {
    return 'Only one emergency level category present'
  }
  if (key === 'gender') {
    return `Only one gender group: ${groupName}`
  }
  return 'Not enough group diversity'
}

function BiasBar({
  label,
  value,
  threshold,
}: {
  label: string
  value: number
  threshold: number
}) {
  const pct = (value * 100).toFixed(1)
  const passing = value <= threshold
  return (
    <div className="bg-gray-800/60 rounded-lg p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm text-gray-300">{label}</p>
        <span
          className={cn(
            'text-xl font-bold tabular-nums',
            passing ? 'text-green-400' : 'text-yellow-400'
          )}
        >
          {pct}%
        </span>
      </div>
      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-gray-700 overflow-hidden">
        <div
          className={cn(
            'h-full rounded-full transition-all',
            passing ? 'bg-green-500' : 'bg-yellow-500'
          )}
          style={{ width: `${Math.min(value / (threshold * 2), 1) * 100}%` }}
        />
      </div>
      <p className="text-[10px] text-gray-500 mt-1">
        Threshold: {(threshold * 100).toFixed(0)}%
      </p>
    </div>
  )
}

function GroupBreakdownTable({ rows }: { rows: FairnessGroupBreakdown[] }) {
  if (!rows || rows.length === 0) return null
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-gray-700">
            <th className="text-left py-2 px-2 text-gray-400 font-medium">Group</th>
            <th className="text-right py-2 px-2 text-gray-400 font-medium">Total</th>
            <th className="text-right py-2 px-2 text-gray-400 font-medium">High-Risk</th>
            <th className="text-right py-2 px-2 text-gray-400 font-medium">Rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.group} className="border-b border-gray-800 hover:bg-gray-800/40">
              <td className="py-1.5 px-2 text-gray-300 capitalize">
                {String(row.group)}
              </td>
              <td className="py-1.5 px-2 text-right text-gray-400 tabular-nums">
                {row.total}
              </td>
              <td className="py-1.5 px-2 text-right text-gray-400 tabular-nums">
                {row.high_risk}
              </td>
              <td
                className={cn(
                  'py-1.5 px-2 text-right tabular-nums font-medium',
                  row.high_risk_rate > 0.7
                    ? 'text-red-400'
                    : row.high_risk_rate > 0.4
                    ? 'text-yellow-400'
                    : 'text-green-400'
                )}
              >
                {(row.high_risk_rate * 100).toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const breakdownKeys: { key: string; label: string }[] = [
  { key: 'gender', label: 'Gender' },
  { key: 'special_needs', label: 'Special Needs' },
  { key: 'emergency_level', label: 'Emergency Level' },
]

export function FairnessDashboard() {
  const { data: metrics, isLoading, error } = useFairnessMetrics()
  const queryClient = useQueryClient()

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['fairness', 'metrics'] })
  }

  const conf = metrics ? confidenceLevel(metrics.total_placements) : 'high'
  const displayMode: 'insufficient' | 'preliminary' | 'scored' =
    conf === 'none' ? 'insufficient' : conf === 'low' ? 'preliminary' : 'scored'

  return (
    <GlassCard>
      <GlassCardHeader>
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-blue-400" />
          <GlassCardTitle>Fairness & Bias Audit</GlassCardTitle>
        </div>
        <div className="flex items-center gap-3">
          {metrics && (
            <div
              className={cn(
                'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
                displayMode === 'insufficient'
                  ? 'bg-gray-500/15 text-gray-400'
                  : displayMode === 'preliminary'
                    ? 'bg-yellow-500/15 text-yellow-400'
                    : metrics.status === 'PASS'
                      ? 'bg-green-500/15 text-green-400'
                      : 'bg-yellow-500/15 text-yellow-400'
              )}
            >
              {displayMode === 'insufficient' ? (
                <AlertTriangle className="w-3.5 h-3.5" />
              ) : displayMode === 'preliminary' ? (
                <AlertTriangle className="w-3.5 h-3.5" />
              ) : metrics.status === 'PASS' ? (
                <CheckCircle className="w-3.5 h-3.5" />
              ) : (
                <AlertCircle className="w-3.5 h-3.5" />
              )}
              {displayMode === 'insufficient' ? 'Insufficient Data' :
               displayMode === 'preliminary' ? 'Preliminary' :
               metrics.status === 'PASS' ? 'Within Threshold' : 'Review Recommended'}
            </div>
          )}
          <button
            onClick={handleRefresh}
            title="Refresh metrics"
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </GlassCardHeader>

      <div className="px-4 pb-4">
        <DataLoader isLoading={isLoading} error={error} type="card" rows={3}>
          {metrics && (
            <div className="space-y-6">
              {/* Sample size warning */}
              {displayMode !== 'scored' && (
                <div className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border',
                  displayMode === 'insufficient'
                    ? 'bg-red-500/5 border-red-500/20'
                    : 'bg-yellow-500/5 border-yellow-500/20',
                )}>
                  <AlertTriangle className={cn(
                    'w-4 h-4 mt-0.5 shrink-0',
                    displayMode === 'insufficient' ? 'text-red-400' : 'text-yellow-400',
                  )} />
                  <div>
                    <p className="text-xs font-medium text-gray-200">
                      {displayMode === 'insufficient' ? 'Insufficient data' : 'Preliminary results'}
                    </p>
                    <p className="text-[10px] text-gray-400 mt-0.5">
                      {displayMode === 'insufficient'
                        ? `Only ${metrics.total_placements} placements audited. Need at least ${MIN_RELIABLE_SAMPLE} for meaningful analysis.`
                        : `${metrics.total_placements} placements audited. Results may change significantly as sample grows.`
                      }
                    </p>
                  </div>
                </div>
              )}

              {/* Bias bars */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {breakdownKeys.map((bk) => {
                  const groups = metrics.breakdowns[bk.key as keyof typeof metrics.breakdowns] ?? []
                  const warning = getDiversityWarning(bk.key, groups)
                  const computable = warning === null
                  const biasValue = bk.key === 'gender' ? metrics.gender_bias
                    : bk.key === 'special_needs' ? metrics.special_needs_bias
                    : metrics.emergency_level_bias
                  if (!computable) {
                    return (
                      <div key={bk.key} className="bg-gray-800/60 rounded-lg p-4">
                        <p className="text-sm text-gray-500 mb-2">{bk.key === 'special_needs' ? 'Special Needs Parity' : bk.label + ' Parity'}</p>
                        <p className="text-xs text-gray-500">Cannot evaluate</p>
                        <p className="text-[10px] text-gray-600 mt-0.5">{warning}</p>
                      </div>
                    )
                  }
                  return (
                    <BiasBar
                      key={bk.key}
                      label={bk.key === 'special_needs' ? 'Special Needs Parity' : bk.label + ' Parity'}
                      value={biasValue}
                      threshold={metrics.threshold}
                    />
                  )
                })}
              </div>

              {/* Breakdowns */}
              <div className="space-y-4">
                {breakdownKeys.map((bk) => {
                  const groups = metrics.breakdowns[bk.key as keyof typeof metrics.breakdowns] ?? []
                  const warning = getDiversityWarning(bk.key, groups)
                  const computable = warning === null
                  return (
                    <div key={bk.key}>
                      <p className="text-xs text-gray-400 mb-2 flex items-center gap-1.5">
                        <BarChart3 className="w-3.5 h-3.5" />
                        {bk.label} breakdown
                      </p>
                      {computable ? (
                        <GroupBreakdownTable rows={groups} />
                      ) : (
                        <div className="text-xs text-gray-500 italic py-2">
                          {warning}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between text-[10px] text-gray-500 pt-2 border-t border-gray-800">
                <span>Based on {metrics.total_placements} placements</span>
                <span>
                  Last calculated:{' '}
                  {new Date(metrics.last_calculated).toLocaleString()}
                </span>
              </div>
            </div>
          )}
        </DataLoader>
      </div>
    </GlassCard>
  )
}
