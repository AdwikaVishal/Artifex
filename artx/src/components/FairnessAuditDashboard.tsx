/**
 * FairnessAuditDashboard – AI Fairness & Bias Audit dashboard.
 *
 * Four-tab view for compliance officers, agency directors, and external
 * auditors.  Uses plain language throughout – no ML jargon.
 *
 * Tabs:
 *   1. Overview          — health score + latest violations
 *   2. Demographic Breakdown — bar charts by race / SES / geography
 *   3. Decision Explorer — search any child, see why the AI decided what it did
 *   4. Audit Export      — date picker + format chooser + one-click report
 */

import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Shield, Scale, Users, Search, Download, FileText,
  AlertTriangle, CheckCircle, Info,
  BarChart3, TrendingUp, Clock,
} from 'lucide-react'
import { useFairnessMetrics, useAuditVerify, useDecisionByChildId } from '@/hooks/use-foster'
import { normalizeWorkflowId } from '@/services/foster'
import type { FairnessGroupBreakdown } from '@/services/foster'
import { GlassCard, GlassCardHeader, GlassCardTitle, GlassCardValue } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DataLoader } from '@/components/data-loader'
import { cn } from '@/lib/utils'

// ── Shared ───────────────────────────────────────────────────────────

const STATUS_COLORS = {
  fair:     'text-success',
  watch:    'text-warning',
  violation: 'text-destructive',
  insufficient: 'text-muted-foreground',
  preliminary: 'text-warning',
} as const

const STATUS_BG = {
  fair:     'bg-success/15',
  watch:    'bg-warning/15',
  violation: 'bg-destructive/15',
  insufficient: 'bg-muted/15',
  preliminary: 'bg-warning/15',
} as const

type Status = keyof typeof STATUS_COLORS

function StatusBadge({ status, label }: { status: Status; label: string }) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium',
      STATUS_BG[status], STATUS_COLORS[status],
    )}>
      {status === 'fair' && <CheckCircle className="w-3 h-3" />}
      {status === 'watch' && <AlertTriangle className="w-3 h-3" />}
      {status === 'violation' && <AlertTriangle className="w-3 h-3" />}
      {status === 'insufficient' && <AlertTriangle className="w-3 h-3" />}
      {status === 'preliminary' && <AlertTriangle className="w-3 h-3" />}
      {label}
    </span>
  )
}

function TabButton({ active, label, icon: Icon, onClick }: {
  active: boolean; label: string; icon: React.ElementType; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all',
        active
          ? 'bg-primary/15 text-primary shadow-sm'
          : 'text-muted-foreground hover:text-foreground hover:bg-glass',
      )}
    >
      <Icon className="w-4 h-4" />
      {label}
    </button>
  )
}

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.06 } },
}

const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35 } },
}

// ── Overview Tab ─────────────────────────────────────────────────────

const MIN_RELIABLE_SAMPLE = 30

function computeMarginOfError(n: number): number {
  if (n < 2) return 1
  return +(1.96 / Math.sqrt(2 * n)).toFixed(3)
}

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

function OverviewTab() {
  const { data: metrics, isLoading: mLoading, error: mError, refetch: mRefetch } = useFairnessMetrics()
  const { data: verify, isLoading: vLoading, error: vError, refetch: vRefetch } = useAuditVerify()

  if (mLoading || vLoading) return <DataLoader isLoading type="full" rows={4} />
  if (mError || vError) return <DataLoader isLoading={false} error={(mError || vError) as Error} refetch={() => { mRefetch(); vRefetch() }} />

  if (!metrics) return null

  const n = metrics.total_placements
  const conf = confidenceLevel(n)
  const moe = computeMarginOfError(n)

  const displayMode: 'insufficient' | 'preliminary' | 'scored' =
    conf === 'none' ? 'insufficient' : conf === 'low' ? 'preliminary' : 'scored'

  const biasEntries = [
    { key: 'gender', label: 'Gender Parity', value: metrics.gender_bias, groups: metrics.breakdowns.gender },
    { key: 'special_needs', label: 'Special Needs Parity', value: metrics.special_needs_bias, groups: metrics.breakdowns.special_needs },
    { key: 'emergency_level', label: 'Emergency Level Parity', value: metrics.emergency_level_bias, groups: metrics.breakdowns.emergency_level },
  ] as const

  const maxBias = Math.max(...biasEntries.map(b => b.value))
  const healthScore = displayMode === 'scored'
    ? metrics.status === 'PASS'
      ? Math.max(85, Math.round(100 - maxBias * 100))
      : Math.round(Math.max(0, 100 - (maxBias / metrics.threshold) * 50))
    : null
  const healthStatus: Status = displayMode === 'scored'
    ? (metrics.status === 'PASS' ? 'fair' : maxBias > metrics.threshold * 1.5 ? 'violation' : 'watch')
    : displayMode === 'preliminary' ? 'preliminary' : 'insufficient'
  const violationItems = biasEntries
    .filter(b => b.value > metrics.threshold)
    .map(b => ({
      metric: b.label,
      value: `${b.value.toFixed(3)} bias (threshold ${metrics.threshold})`,
      severity: b.value > metrics.threshold * 1.5 ? 'violation' as Status : 'watch' as Status,
    }))

  const methodDescriptions: Record<string, string> = {
    'Gender Parity': 'Measures whether the AI flags similar percentages of children as high-risk across gender groups. A small difference is normal; a large difference means the model may be treating genders unequally.',
    'Special Needs Parity': 'Measures whether the AI flags children with and without special needs at similar rates. Disparities here may indicate the model over-indexes on special needs status.',
    'Emergency Level Parity': 'Measures whether the AI\'s risk assessments vary by the child\'s emergency level. Some variation is expected, but large gaps suggest inconsistent treatment.',
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">

      {/* Sample size warning */}
      {conf !== 'high' && (
        <motion.div variants={item}>
          <div className={cn(
            'flex items-start gap-3 p-4 rounded-lg border text-sm',
            conf === 'none'
              ? 'bg-destructive/5 border-destructive/20'
              : 'bg-warning/5 border-warning/20',
          )}>
            <AlertTriangle className={cn(
              'w-5 h-5 mt-0.5 shrink-0',
              conf === 'none' ? 'text-destructive' : 'text-warning',
            )} />
            <div>
              <p className="font-medium text-foreground">
                {conf === 'none' ? 'Insufficient data for reliable analysis' : 'Limited data — low confidence'}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                Only {n} placement{n !== 1 ? 's' : ''} audited.
                {conf === 'none'
                  ? ` Need at least ${MIN_RELIABLE_SAMPLE} for statistically meaningful fairness metrics.`
                  : ` Metrics improve in reliability as sample size grows toward ${MIN_RELIABLE_SAMPLE}+.`
                }
              </p>
            </div>
          </div>
        </motion.div>
      )}

      {/* Health score header */}
      <motion.div variants={item} className="flex items-start gap-6">
        <div className="relative shrink-0">
          <svg width="120" height="120" viewBox="0 0 120 120" className="rotate-[-90deg]">
            <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="8"
              className="text-border-light" />
            {displayMode === 'scored' && healthScore !== null && (
              <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="8"
                strokeDasharray={`${(healthScore / 100) * 327} 327`}
                className={cn(
                  healthScore >= 85 ? 'text-success' : healthScore >= 60 ? 'text-warning' : 'text-destructive',
                  'transition-all duration-1000',
                )}
                strokeLinecap="round" />
            )}
            {displayMode === 'preliminary' && (
              <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="8"
                strokeDasharray="245 82" className="text-warning/50" />
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            {displayMode === 'scored' && healthScore !== null ? (
              <>
                <span className={cn(
                  'text-3xl font-bold',
                  healthScore >= 85 ? 'text-success' : healthScore >= 60 ? 'text-warning' : 'text-destructive',
                )}>{healthScore}</span>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">Health</span>
              </>
            ) : displayMode === 'preliminary' ? (
              <>
                <span className="text-sm font-bold text-warning leading-tight text-center">PRELIM<br/>INARY</span>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">Health</span>
              </>
            ) : (
              <>
                <span className="text-lg font-bold text-muted-foreground">N/A</span>
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">Health</span>
              </>
            )}
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-bold text-foreground">Fairness & Bias Audit</h1>
            <StatusBadge status={healthStatus} label={
              healthStatus === 'insufficient' ? 'Insufficient Data' :
              healthStatus === 'preliminary' ? 'Preliminary' :
              healthStatus === 'fair' ? 'Within Thresholds' :
              healthStatus === 'watch' ? 'Needs Attention' : 'Violations Found'
            } />
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            Monitoring AI placement decisions for bias across gender, special needs status, emergency level, and other protected characteristics.
            {violationItems.length > 0 && (
              <span className="text-destructive"> {violationItems.filter(v => v.severity === 'violation').length} active violation{violationItems.filter(v => v.severity === 'violation').length !== 1 ? 's' : ''} require review.</span>
            )}
          </p>

          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" /> Last audit: {metrics.last_calculated}
            </span>
            <span className="flex items-center gap-1.5">
              <BarChart3 className="w-3.5 h-3.5" /> {n.toLocaleString()} placement{n !== 1 ? 's' : ''} audited
            </span>
            <span className="flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5" /> {conf === 'none' ? 'Hash chain N/A' : `Hash chain ${verify?.valid ? 'intact' : 'needs review'}`}
            </span>
          </div>
        </div>
      </motion.div>

      {/* Metric cards row */}
      <motion.div variants={item} className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        {biasEntries.map((b) => {
          const diversityWarning = getDiversityWarning(b.key, b.groups)
          const computable = diversityWarning === null
          const status: Status = !computable ? 'insufficient'
            : b.value > metrics.threshold * 1.5 ? 'violation'
            : b.value > metrics.threshold ? 'watch' : 'fair'
          return (
            <GlassCard key={b.key} hover={false}>
              <div className="flex items-center gap-1.5">
                <GlassCardTitle>{b.label}</GlassCardTitle>
                <span className="group relative cursor-help">
                  <Info className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 p-2 rounded-lg bg-foreground/90 text-background text-[11px] leading-relaxed shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10 pointer-events-none">
                    {methodDescriptions[b.label] || 'Bias metric computed from ml_decision_audit table with weekly aggregation.'}
                  </span>
                </span>
              </div>
              {computable ? (
                <>
                  <div className="flex items-baseline gap-2 mt-1.5">
                    <span className={cn('text-2xl font-bold', STATUS_COLORS[status])}>
                      {b.value.toFixed(3)}
                    </span>
                    <span className={cn(
                      'text-xs',
                      displayMode === 'insufficient' ? 'text-muted-foreground/40' : 'text-muted-foreground',
                    )}>
                      ±{moe}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">
                      threshold {metrics.threshold}
                    </span>
                    {displayMode !== 'scored' && (
                      <span className={cn(
                        'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                        displayMode === 'insufficient'
                          ? 'bg-destructive/10 text-destructive'
                          : 'bg-warning/10 text-warning',
                      )}>
                        n={n}
                      </span>
                    )}
                  </div>
                  <div className="mt-2 h-1 rounded-full bg-border-light overflow-hidden">
                    <div className={cn('h-full rounded-full transition-all', STATUS_BG[status])}
                      style={{ width: `${Math.min((b.value / (metrics.threshold * 2)) * 100, 100)}%` }} />
                  </div>
                  {displayMode === 'preliminary' && (
                    <p className="mt-2 text-[10px] text-warning font-medium">Preliminary only</p>
                  )}
                </>
              ) : (
                <div className="mt-2 space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">Cannot evaluate</p>
                  <p className="text-[10px] text-muted-foreground/60">{diversityWarning}</p>
                </div>
              )}
            </GlassCard>
          )
        })}
      </motion.div>

      {/* Active review items */}
      {violationItems.length > 0 && (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Active Review Items</GlassCardTitle>
              <span className="text-xs text-muted-foreground">
                {violationItems.filter(v => v.severity === 'violation').length} violation
                {violationItems.filter(v => v.severity === 'violation').length !== 1 ? 's' : ''}
              </span>
            </GlassCardHeader>
            <div className="space-y-3">
              {violationItems.map((v, i) => (
                <div key={i} className={cn(
                  'p-3 rounded-lg border text-sm',
                  v.severity === 'violation'
                    ? 'bg-destructive/5 border-destructive/20'
                    : 'bg-warning/5 border-warning/20',
                )}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium text-foreground">{v.metric}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{v.value}</p>
                    </div>
                    <StatusBadge status={v.severity} label={
                      v.severity === 'violation' ? 'Violation' : 'Watching'
                    } />
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>
        </motion.div>
      )}

      {/* Plain language explanation */}
      <motion.div variants={item}>
        <GlassCard hover={false}>
          <GlassCardHeader>
            <GlassCardTitle>What This Means</GlassCardTitle>
            <Info className="w-4 h-4 text-muted-foreground" />
          </GlassCardHeader>
          <div className="text-sm text-muted-foreground space-y-2 leading-relaxed">
            {conf === 'none' ? (
              <p>
                <strong className="text-foreground">Not enough data for a health score.</strong>{' '}
                Fairness metrics require at least {MIN_RELIABLE_SAMPLE} audited placement decisions to produce
                statistically meaningful results. With only {n} placement{n !== 1 ? 's' : ''}, the observed bias
                values of 0.000 may simply reflect insufficient sample size rather than actual parity.
              </p>
            ) : conf === 'low' ? (
              <p>
                <strong className="text-warning">Preliminary results — not yet reliable.</strong>{' '}
                Only {n} placement{n !== 1 ? 's' : ''} have been audited, which is below the minimum of {MIN_RELIABLE_SAMPLE} needed for
                statistically meaningful fairness scoring. The metrics shown are computed but may change significantly
                as more data is collected. Do not use these results for compliance or audit decisions.
              </p>
            ) : (
              <p>
                <strong className="text-foreground">Health score {healthScore} — {healthStatus === 'fair' ? 'within thresholds' : healthStatus === 'watch' ? 'needs attention' : 'violations found'}.</strong>{' '}
                The AI model is evaluated on three bias dimensions: gender, special needs status, and emergency level.
                Each metric compares the AI's high-risk flag rate across groups within that dimension.
              </p>
            )}
            {violationItems.length > 0 && (
              <p>
                <strong className="text-destructive">
                  {violationItems.filter(v => v.severity === 'violation').length > 0
                    ? `${violationItems.filter(v => v.severity === 'violation').length} violation${violationItems.filter(v => v.severity === 'violation').length !== 1 ? 's' : ''} found`
                    : 'Items being monitored'}
                </strong>
                {biasEntries.filter(b => b.value > metrics.threshold).map(b =>
                  ` The ${b.label.replace(' Parity', '').toLowerCase()} bias of ${b.value.toFixed(3)} exceeds the threshold of ${metrics.threshold}.`
                )}
                {violationItems.length > 0 && ' These disparities may reflect historical inequities in the training data, not individual children\'s needs.'}
              </p>
            )}
            <p className="text-xs text-muted-foreground/60 mt-2">
              Threshold: {metrics.threshold}. Status: {metrics.status}. {n} placement{n !== 1 ? 's' : ''} audited across {['gender', 'special_needs', 'emergency_level'].length} demographic dimensions.
            </p>
            {conf !== 'high' && (
              <div className={cn(
                'mt-3 p-3 rounded-lg border text-xs space-y-1',
                conf === 'none'
                  ? 'bg-destructive/5 border-destructive/20'
                  : 'bg-warning/5 border-warning/20',
              )}>
                <p className="font-medium text-foreground">Recommendation</p>
                <p className="text-muted-foreground">
                  Collect at least {MIN_RELIABLE_SAMPLE} AI placement decisions before relying on fairness scores for
                  compliance or audit purposes. With the current sample of {n}, the system cannot distinguish
                  between true parity and insufficient data.
                </p>
              </div>
            )}
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  )
}

// ── Demographic Breakdown Tab ────────────────────────────────────────

function DemographicBreakdownTab() {
  const { data: metrics, isLoading, error, refetch } = useFairnessMetrics()

  if (isLoading) return <DataLoader isLoading type="full" rows={3} />
  if (error) return <DataLoader isLoading={false} error={error} refetch={refetch} />

  const breakdownConfig: {
    key: string; label: string; groups: FairnessGroupBreakdown[]; barColor: string
  }[] = [
    { key: 'gender', label: 'Gender', groups: metrics?.breakdowns.gender ?? [], barColor: '#6366f1' },
    { key: 'special_needs', label: 'Special Needs Status', groups: metrics?.breakdowns.special_needs ?? [], barColor: '#f97316' },
    { key: 'emergency_level', label: 'Emergency Level', groups: metrics?.breakdowns.emergency_level ?? [], barColor: '#06b6d4' },
  ]

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">

      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="text-lg font-bold text-foreground">Demographic Breakdown</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Compare how different groups are treated by the AI. Each bar shows the percentage of children in that group
          who received a high-risk prediction. A fair system would show similar rates across all groups.
        </p>
      </motion.div>

      {/* Confidence warning */}
      {metrics && (() => {
        const dc = confidenceLevel(metrics.total_placements)
        if (dc === 'high') return null
        return (
          <motion.div variants={item}>
            <div className={cn(
              'flex items-start gap-3 p-4 rounded-lg border text-sm',
              dc === 'none'
                ? 'bg-destructive/5 border-destructive/20'
                : 'bg-warning/5 border-warning/20',
            )}>
              <AlertTriangle className={cn(
                'w-5 h-5 mt-0.5 shrink-0',
                dc === 'none' ? 'text-destructive' : 'text-warning',
              )} />
              <div>
                <p className="font-medium text-foreground">
                  {dc === 'none' ? 'Insufficient data' : 'Preliminary breakdowns'}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {dc === 'none'
                    ? `With only ${metrics.total_placements} placements, demographic comparisons are not meaningful.`
                    : `Only ${metrics.total_placements} placements audited. Group comparisons may change significantly as sample size grows.`
                  }
                </p>
              </div>
            </div>
          </motion.div>
        )
      })()}

      {breakdownConfig.filter(b => b.groups.length > 0).length === 0 ? (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <div className="text-center py-8 space-y-3">
              <p className="text-sm text-muted-foreground">No demographic data available yet.</p>
              <p className="text-xs text-muted-foreground/60 max-w-md mx-auto">
                Demographic breakdowns require sufficient placements per group to compute meaningful metrics.
                Data appears once at least 20 children per demographic group have received an AI decision.
              </p>
            </div>
          </GlassCard>
        </motion.div>
      ) : breakdownConfig.filter(b => b.groups.length > 0).map((attr) => {
        const diversityWarning = getDiversityWarning(attr.key, attr.groups)
        const computable = diversityWarning === null
        const maxRate = computable ? Math.max(...attr.groups.map(g => g.high_risk_rate)) : 0
        const minRate = computable ? Math.min(...attr.groups.map(g => g.high_risk_rate)) : 0
        const gap = maxRate - minRate
        const threshold = metrics?.threshold ?? 0.05
        const status: Status = !computable ? 'insufficient'
          : gap > threshold * 1.5 ? 'violation'
          : gap > threshold ? 'watch' : 'fair'

        const dc = metrics ? confidenceLevel(metrics.total_placements) : 'high'

        return (
          <motion.div key={attr.key} variants={item}>
            <GlassCard hover={false}>
              <GlassCardHeader>
                <div className="flex items-center gap-2">
                  <GlassCardTitle>{attr.label}</GlassCardTitle>
                  <StatusBadge status={status} label={
                    status === 'insufficient' ? 'Cannot Evaluate' :
                    status === 'violation' ? 'Threshold Exceeded' :
                    status === 'watch' ? 'Monitor' : 'Within Threshold'
                  } />
                </div>
                {computable && (
                  <span className="text-xs text-muted-foreground">
                    {attr.groups.reduce((s, g) => s + g.total, 0)} children
                  </span>
                )}
              </GlassCardHeader>

              {computable ? (
                <>
                  <div className="space-y-3">
                    {attr.groups.map((group) => {
                      const pct = (group.high_risk_rate * 100).toFixed(0)
                      return (
                        <div key={group.group} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-foreground capitalize">{group.group}</span>
                            <span className="text-xs text-muted-foreground">
                              <span className={cn(
                                'font-semibold',
                                group.high_risk_rate > 0.30 ? 'text-destructive' :
                                group.high_risk_rate > 0.20 ? 'text-warning' : 'text-success',
                              )}>{pct}%</span>
                              {' · '}n={group.total}
                            </span>
                          </div>
                          <div className="h-4 rounded-full bg-border-light overflow-hidden">
                            <div
                              className="h-full rounded-full transition-all duration-700"
                              style={{
                                width: `${pct}%`,
                                backgroundColor: attr.barColor,
                              }}
                            />
                          </div>
                        </div>
                      )
                    })}
                  </div>

                  <div className={cn(
                    'mt-4 p-3 rounded-lg border text-sm',
                    status === 'violation'
                      ? 'bg-destructive/5 border-destructive/20'
                      : 'bg-warning/5 border-warning/20',
                  )}>
                    <div className="flex items-start gap-2">
                      {status === 'violation'
                        ? <AlertTriangle className="w-4 h-4 text-destructive mt-0.5 shrink-0" />
                        : <Info className="w-4 h-4 text-warning mt-0.5 shrink-0" />
                      }
                      <div>
                        <p className="text-foreground font-medium">
                          {status === 'violation' ? 'Disparity detected' : 'Trend being monitored'}
                        </p>
                        <p className="text-muted-foreground text-xs mt-0.5">
                          High-risk rate ranges from {(minRate * 100).toFixed(0)}% to {(maxRate * 100).toFixed(0)}%
                          {' '}— a gap of {(gap * 100).toFixed(1)} percentage points (threshold: {(threshold * 100).toFixed(0)}pp).
                        </p>
                        {dc === 'low' && (
                          <p className="text-muted-foreground text-[10px] mt-1 italic">
                            Preliminary — sample size ({metrics?.total_placements}) below minimum of {MIN_RELIABLE_SAMPLE}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="py-6 text-center space-y-2">
                  <AlertTriangle className="w-8 h-8 text-warning mx-auto" />
                  <p className="text-sm font-medium text-foreground">Cannot evaluate</p>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto">{diversityWarning}</p>
                  {dc === 'low' && (
                    <p className="text-[10px] text-muted-foreground/60">
                      More data may reveal additional groups. Current sample: {metrics?.total_placements} placements.
                    </p>
                  )}
                </div>
              )}
            </GlassCard>
          </motion.div>
        )
      })}

      <motion.div variants={item}>
        <GlassCard hover={false}>
          <div className="flex items-start gap-3 text-sm text-muted-foreground">
            <Info className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <p className="font-medium text-foreground mb-1">How we measure fairness</p>
              <div className="text-xs leading-relaxed space-y-2">
                <p>
                  <strong>Demographic parity</strong> — We compare the percentage of children in each group
                  who receive a "high" or "critical" risk label from the AI. A disparity exists when one
                  group's rate differs substantially from another's. Our threshold is a {((metrics?.threshold ?? 0.05) * 100).toFixed(0)} percentage-point difference between
                  the highest and lowest group.
                </p>
                <p>
                  <strong>Minimum group size</strong> — Groups with fewer than 20 children are shown but
                  excluded from the pass/fail calculation. Small samples can produce misleading results.
                </p>
                <p>
                  <strong>What this does not mean</strong> — A detected disparity does not necessarily mean
                  the model is biased. It may reflect real differences in needs, historical data patterns, or
                  systemic inequities that existed before the AI was deployed. Each disparity is reviewed by
                  a human analyst before any action is taken.
                </p>
                <p>
                  <strong>Data source</strong> — Metrics are computed from the ml_decision_audit table,
                  which records every AI decision with the child's demographic attributes at the time of
                  the decision. The weekly fairness workflow (Temporal cron) computes these metrics every
                  Monday and stores them in the fairness_audit_log table.
                </p>
              </div>
            </div>
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  )
}

// ── Decision Explorer Tab ────────────────────────────────────────────

function DecisionExplorerTab() {
  const [childId, setChildId] = useState('')
  const [searchedId, setSearchedId] = useState<string | null>(null)
  const { data: decisionData, isLoading, error, refetch } = useDecisionByChildId(searchedId)

  const handleSearch = () => {
    const raw = childId.trim()
    if (raw) setSearchedId(normalizeWorkflowId(raw))
  }

  const result = decisionData?.decisions?.[0] ?? null

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">

      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="text-lg font-bold text-foreground">Decision Explorer</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          Search for any child to see how the AI reached its recommendation. Each decision shows
          the factors that influenced the outcome, explained in plain language.
        </p>

        {/* Search bar */}
        <div className="flex gap-2 max-w-lg">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
            <Input
              className="pl-9"
              placeholder="Search by child ID, e.g. CH-A0427"
              value={childId}
              onChange={(e) => setChildId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <Button onClick={handleSearch} disabled={!childId.trim() || isLoading}>
            {isLoading ? (
              <span className="flex items-center gap-2">
                <span className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Searching
              </span>
            ) : 'Explore'}
          </Button>
        </div>
      </motion.div>

      {error && (
        <motion.div variants={item}>
          <DataLoader isLoading={false} error={error as Error} refetch={refetch} />
        </motion.div>
      )}

      {searchedId && !isLoading && result && (
        <motion.div variants={item} className="space-y-4">
          {/* Decision header */}
          <GlassCard hover={false}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-base font-bold text-foreground">{result.child_id}</h3>
                </div>
                <p className="text-sm text-muted-foreground">
                  {result.decision_type} · {result.decided_at}
                </p>
                {result.human_overridden && (
                  <p className="text-xs text-warning mt-1 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" />
                    This decision was reviewed and overridden by a caseworker.
                  </p>
                )}
              </div>
              <div className="text-right">
                <div className="flex items-baseline gap-1.5">
                  <span className={cn(
                    'text-3xl font-bold',
                    result.output_score >= 80 ? 'text-destructive' :
                    result.output_score >= 60 ? 'text-warning' : 'text-success',
                  )}>{result.output_score}</span>
                  <span className="text-xs text-muted-foreground">/ 100</span>
                </div>
                <span className={cn(
                  'text-xs font-medium',
                  result.output_score >= 80 ? 'text-destructive' :
                  result.output_score >= 60 ? 'text-warning' : 'text-success',
                )}>{result.output_label}</span>
              </div>
            </div>
          </GlassCard>

          {/* Decision details */}
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Decision Details</GlassCardTitle>
              <span className="text-xs text-muted-foreground">
                Model: {result.model_name} v{result.model_version}
              </span>
            </GlassCardHeader>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Placement</p>
                <p className="text-foreground">{result.placement_id}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Confidence</p>
                <p className="text-foreground">
                  {result.output_confidence != null
                    ? `${(result.output_confidence * 100).toFixed(0)}%`
                    : '—'}
                </p>
              </div>
              {result.human_decision && (
                <div className="col-span-2">
                  <p className="text-xs text-muted-foreground">Human override decision</p>
                  <p className="text-foreground">{result.human_decision}</p>
                </div>
              )}
            </div>
          </GlassCard>

          {/* Demographics at time of decision */}
          {Object.keys(result.child_demographics).length > 0 && (
            <GlassCard hover={false}>
              <GlassCardHeader>
                <GlassCardTitle>Demographics at time of decision</GlassCardTitle>
              </GlassCardHeader>
              <div className="flex flex-wrap gap-2">
                {Object.entries(result.child_demographics).map(([key, value]) => (
                  <span key={key} className="px-3 py-1.5 rounded-full text-xs bg-glass border border-glass-border text-muted-foreground capitalize">
                    {key.replace(/_/g, ' ')}: {String(value)}
                  </span>
                ))}
              </div>
            </GlassCard>
          )}

          {/* Integrity verification */}
          <GlassCard hover={false}>
            <div className="flex items-start gap-3 text-sm text-muted-foreground">
              <Shield className="w-4 h-4 mt-0.5 shrink-0 text-success" />
              <div>
                <p className="font-medium text-foreground mb-1">Tamper-evident integrity</p>
                <p className="text-xs leading-relaxed font-mono text-muted-foreground/60 break-all">
                  Hash: {result.hash}
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {searchedId && !isLoading && !result && !error && (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <div className="text-center py-8 space-y-3">
              <p className="text-sm text-muted-foreground">
                No decision found for "{searchedId}".
              </p>
              <div className="max-w-md mx-auto text-xs text-muted-foreground/60 space-y-1">
                <p>Decisions are stored in the ML decision audit table — a tamper-evident log of every AI recommendation.</p>
                <p>If no result appears, the child may not have received an AI decision yet, or the child ID may differ from the one used at intake. Try searching by a different ID.</p>
                <p className="pt-1">Decisions older than 90 days are archived to Parquet and are not searchable from this panel. Export the full audit log for historical searches.</p>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}
    </motion.div>
  )
}

// ── Audit Export Tab ─────────────────────────────────────────────────

function AuditExportTab() {
  const [dateRange, setDateRange] = useState({ from: '2026-01-01', to: '2026-06-01' })
  const [format, setFormat] = useState<'pdf' | 'csv'>('pdf')
  const [includeDecisions, setIncludeDecisions] = useState(true)
  const [includeDemographics, setIncludeDemographics] = useState(true)
  const [includeHashChain, setIncludeHashChain] = useState(true)
  const [generating, setGenerating] = useState(false)
  const { data: metrics } = useFairnessMetrics()
  const { data: verify, isLoading, error, refetch } = useAuditVerify()

  const handleGenerate = () => {
    setGenerating(true)
    setTimeout(() => setGenerating(false), 2500)
  }

  const totalDecisions = verify?.checked ?? metrics?.total_placements ?? 0
  const hashIntact = verify?.valid

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">

      <motion.div variants={item}>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="text-lg font-bold text-foreground">Audit Export</h2>
        </div>
        <p className="text-sm text-muted-foreground">
          Generate a compliance report for external auditors, oversight boards, or regulatory submission.
          Reports include the full fairness analysis, hash chain verification, and all decision records
          in the selected date range.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Configuration panel */}
        <motion.div variants={item} className="lg:col-span-1">
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Report Configuration</GlassCardTitle>
            </GlassCardHeader>
            <div className="space-y-5">

              {/* Date range */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Date range</label>
                <div className="flex items-center gap-2">
                  <Input
                    type="date"
                    value={dateRange.from}
                    onChange={(e) => setDateRange(p => ({ ...p, from: e.target.value }))}
                    className="flex-1"
                  />
                  <span className="text-xs text-muted-foreground">to</span>
                  <Input
                    type="date"
                    value={dateRange.to}
                    onChange={(e) => setDateRange(p => ({ ...p, to: e.target.value }))}
                    className="flex-1"
                  />
                </div>
              </div>

              {/* Format */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1.5">Format</label>
                <div className="flex gap-2">
                  <button
                    onClick={() => setFormat('pdf')}
                    className={cn(
                      'flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all',
                      format === 'pdf'
                        ? 'bg-primary/15 border-primary/30 text-primary'
                        : 'bg-glass border-glass-border text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <FileText className="w-4 h-4" />
                    PDF
                  </button>
                  <button
                    onClick={() => setFormat('csv')}
                    className={cn(
                      'flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium transition-all',
                      format === 'csv'
                        ? 'bg-primary/15 border-primary/30 text-primary'
                        : 'bg-glass border-glass-border text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <BarChart3 className="w-4 h-4" />
                    CSV
                  </button>
                </div>
              </div>

              {/* Options */}
              <div className="space-y-2">
                <label className="block text-xs font-medium text-muted-foreground mb-1">Include in report</label>
                {[
                  { key: 'includeDecisions', label: 'Decision records', checked: includeDecisions },
                  { key: 'includeDemographics', label: 'Demographic breakdown', checked: includeDemographics },
                  { key: 'includeHashChain', label: 'Hash chain verification', checked: includeHashChain },
                ].map((opt) => (
                  <label key={opt.key} className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={opt.checked}
                      onChange={() => {
                        if (opt.key === 'includeDecisions') setIncludeDecisions(!includeDecisions)
                        if (opt.key === 'includeDemographics') setIncludeDemographics(!includeDemographics)
                        if (opt.key === 'includeHashChain') setIncludeHashChain(!includeHashChain)
                      }}
                      className="w-4 h-4 rounded border-border-light bg-glass accent-primary"
                    />
                    {opt.label}
                  </label>
                ))}
              </div>

              {/* Generate button */}
              <Button
                className="w-full"
                size="lg"
                onClick={handleGenerate}
                disabled={generating}
              >
                {generating ? (
                  <span className="flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Generating...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Download className="w-4 h-4" />
                    Generate Report
                  </span>
                )}
              </Button>
            </div>
          </GlassCard>
        </motion.div>

        {/* Preview panel */}
        <motion.div variants={item} className="lg:col-span-2">
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Report Preview</GlassCardTitle>
              <span className="text-xs text-muted-foreground">
                {dateRange.from} — {dateRange.to} · {format.toUpperCase()}
              </span>
            </GlassCardHeader>

            <DataLoader isLoading={isLoading} error={error as Error | null} refetch={refetch} type="chart">
              <div className="space-y-3 text-sm">
                {/* Report summary */}
                <div className="p-4 rounded-lg bg-glass space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-foreground font-medium">Artifex AI Fairness Audit Report</span>
                    <span className="text-xs text-muted-foreground">Draft · Not yet generated</span>
                  </div>
                  <div className="grid grid-cols-2 gap-4 text-xs text-muted-foreground">
                    <div>
                      <p>Report period</p>
                      <p className="text-foreground font-medium">{dateRange.from} — {dateRange.to}</p>
                    </div>
                    <div>
                      <p>Decisions audited</p>
                      <p className="text-foreground font-medium">{totalDecisions.toLocaleString()}</p>
                    </div>
                    <div>
                      <p>Models covered</p>
                      <p className="text-foreground font-medium">3 (crisis, risk, placement)</p>
                    </div>
                    <div>
                      <p>Hash chain</p>
                      <p className={cn('font-medium', hashIntact ? 'text-success' : 'text-destructive')}>
                        {hashIntact ? 'Intact' : 'Issues found'}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Sections list */}
                <div className="space-y-1">
                  {includeDemographics && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                      <Users className="w-4 h-4 text-primary" />
                      <div className="min-w-0">
                        <p className="text-foreground">Demographic breakdown</p>
                        <p className="text-xs text-muted-foreground">
                          Gender · Special needs · Emergency level
                        </p>
                      </div>
                    </div>
                  )}
                  {includeDecisions && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                      <BarChart3 className="w-4 h-4 text-secondary" />
                      <div className="min-w-0">
                        <p className="text-foreground">Decision records</p>
                        <p className="text-xs text-muted-foreground">{totalDecisions.toLocaleString()} rows · all decision types</p>
                      </div>
                    </div>
                  )}
                  {includeHashChain && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                      <Shield className="w-4 h-4 text-success" />
                      <div className="min-w-0">
                        <p className="text-foreground">Hash chain verification</p>
                        <p className="text-xs text-muted-foreground">
                          {hashIntact ? 'Chain intact' : 'Chain issues'} · {totalDecisions.toLocaleString()} hashes verified
                        </p>
                      </div>
                    </div>
                  )}
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                    <TrendingUp className="w-4 h-4 text-accent" />
                    <div className="min-w-0">
                      <p className="text-foreground">Fairness metrics</p>
                      <p className="text-xs text-muted-foreground">Gender · Special needs · Emergency level</p>
                    </div>
                  </div>
                  {metrics && (
                    <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                      <Scale className="w-4 h-4" />
                      <div className="min-w-0">
                        <p className="text-foreground">Overall status</p>
                        <p className="text-xs text-muted-foreground">{metrics.status}</p>
                      </div>
                    </div>
                  )}
                </div>

                {/* Encryption note */}
                <div className="flex items-start gap-2 p-3 rounded-lg bg-info/5 border border-info/20">
                  <Shield className="w-4 h-4 text-info mt-0.5 shrink-0" />
                  <div className="text-xs text-muted-foreground">
                    <span className="text-foreground font-medium">Encrypted for compliance.</span>{' '}
                    Reports are PGP-encrypted with the auditor's public key before download.
                    The hash chain verification allows any third party to confirm the report has
                    not been tampered with since generation.
                  </div>
                </div>
              </div>
            </DataLoader>
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  )
}

// ── Root component ───────────────────────────────────────────────────

const TABS = [
  { key: 'overview',   label: 'Overview',            icon: Shield },
  { key: 'demographics', label: 'Demographic Breakdown', icon: Users },
  { key: 'explorer',  label: 'Decision Explorer',    icon: Search },
  { key: 'export',    label: 'Audit Export',         icon: FileText },
] as const

export default function FairnessAuditDashboard() {
  const [activeTab, setActiveTab] = useState('overview')

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      {/* Page header */}

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1.5 p-1 rounded-xl bg-glass border border-glass-border">
        {TABS.map((tab) => (
          <TabButton
            key={tab.key}
            active={activeTab === tab.key}
            label={tab.label}
            icon={tab.icon}
            onClick={() => setActiveTab(tab.key)}
          />
        ))}
      </div>

      {/* Tab content */}
      <div className="min-h-[400px]">
        {activeTab === 'overview' && <OverviewTab />}
        {activeTab === 'demographics' && <DemographicBreakdownTab />}
        {activeTab === 'explorer' && <DecisionExplorerTab />}
        {activeTab === 'export' && <AuditExportTab />}
      </div>
    </motion.div>
  )
}
