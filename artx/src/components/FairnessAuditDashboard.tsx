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
  AlertTriangle, CheckCircle, Info, ArrowRight,
  BarChart3, TrendingUp, ExternalLink, Clock,
} from 'lucide-react'
import { GlassCard, GlassCardHeader, GlassCardTitle, GlassCardValue } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

// ── Shared ───────────────────────────────────────────────────────────

const STATUS_COLORS = {
  fair:     'text-success',
  watch:    'text-warning',
  violation: 'text-destructive',
} as const

const STATUS_BG = {
  fair:     'bg-success/15',
  watch:    'bg-warning/15',
  violation: 'bg-destructive/15',
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

function OverviewTab() {
  // Mock data — replaced with TanStack query later
  const health = {
    score: 78,
    status: 'watch' as Status,
    lastAudit: '2026-06-01 06:00 UTC',
    totalDecisions: 38741,
    violations: [
      { metric: 'Race disparity', value: 'Black children 38% high-risk · White children 22%', severity: 'violation' as Status },
      { metric: 'SES disparity', value: 'Lowest quartile 35% · Highest quartile 19%', severity: 'violation' as Status },
      { metric: 'Consistency score', value: '0.74 — 26% of children get inconsistent scores', severity: 'watch' as Status },
    ],
    metrics: [
      { label: 'Demographic Parity', value: 0.16, threshold: 0.05, status: 'violation' as Status },
      { label: 'Bias Amplification', value: 1.6, threshold: 1.0, status: 'violation' as Status },
      { label: 'Individual Fairness', value: 0.74, threshold: 0.85, status: 'watch' as Status },
      { label: 'FPR Disparity', value: 0.18, threshold: 0.10, status: 'violation' as Status },
    ],
  }

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">

      {/* Health score header */}
      <motion.div variants={item} className="flex items-start gap-6">
        <div className="relative shrink-0">
          <svg width="120" height="120" viewBox="0 0 120 120" className="rotate-[-90deg]">
            <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="8"
              className="text-border-light" />
            <circle cx="60" cy="60" r="52" fill="none" stroke="currentColor" strokeWidth="8"
              strokeDasharray={`${(health.score / 100) * 327} 327`}
              className={cn(
                health.score >= 85 ? 'text-success' : health.score >= 60 ? 'text-warning' : 'text-destructive',
                'transition-all duration-1000',
              )}
              strokeLinecap="round" />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={cn(
              'text-3xl font-bold',
              health.score >= 85 ? 'text-success' : health.score >= 60 ? 'text-warning' : 'text-destructive',
            )}>{health.score}</span>
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider mt-0.5">Health</span>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-xl font-bold text-foreground">Fairness & Bias Audit</h1>
            <StatusBadge status={health.status} label={
              health.status === 'fair' ? 'Within Thresholds' :
              health.status === 'watch' ? 'Needs Attention' : 'Violations Found'
            } />
          </div>
          <p className="text-sm text-muted-foreground mb-4">
            Monitoring AI placement decisions for bias across race, income, geography, and other protected characteristics.
            {health.status === 'violation' && (
              <span className="text-destructive"> 2 active violations require review.</span>
            )}
          </p>

          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" /> Last audit: {health.lastAudit}
            </span>
            <span className="flex items-center gap-1.5">
              <BarChart3 className="w-3.5 h-3.5" /> {health.totalDecisions.toLocaleString()} decisions audited
            </span>
            <span className="flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5" /> Hash chain intact
            </span>
          </div>
        </div>
      </motion.div>

      {/* Metric cards row */}
      <motion.div variants={item} className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {health.metrics.map((m) => {
          const methodology: Record<string, string> = {
            'Demographic Parity': 'Measures whether the AI flags similar percentages of children as high-risk across different groups (by race, income, gender, etc.). A small difference is normal; a large difference means the model may be treating groups unequally.',
            'Bias Amplification': 'Compares how much disparity the model produces vs. what existed in historical data. A ratio of 1.0 means the model matches historical bias. Above 1.0 means it is making disparities worse — which blocks automated retraining.',
            'Individual Fairness': 'Checks whether similar children get similar risk scores. A score of 1.0 means perfect consistency. A low score means two nearly identical children may receive very different risk predictions.',
            'FPR Disparity': 'False Positive Rate measures how often the AI flags a stable placement as high-risk. A disparity means the system cries wolf more often for some groups than others, wasting caseworker time and causing unnecessary stress.',
          }
          return (
            <GlassCard key={m.label} hover={false}>
              <div className="flex items-center gap-1.5">
                <GlassCardTitle>{m.label}</GlassCardTitle>
                <span className="group relative cursor-help">
                  <Info className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 p-2 rounded-lg bg-foreground/90 text-background text-[11px] leading-relaxed shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-10 pointer-events-none">
                    {methodology[m.label] || 'Metric derived from ml_decision_audit table with weekly aggregation.'}
                  </span>
                </span>
              </div>
              <div className="flex items-baseline gap-2 mt-1.5">
                <span className={cn(
                  'text-2xl font-bold',
                  STATUS_COLORS[m.status],
                )}>{m.value.toFixed(2)}</span>
                <span className="text-xs text-muted-foreground">
                  threshold {m.threshold}
                </span>
              </div>
              {/* Mini progress bar showing how far past threshold */}
              <div className="mt-2 h-1 rounded-full bg-border-light overflow-hidden">
                <div className={cn(
                  'h-full rounded-full transition-all',
                  STATUS_BG[m.status],
                )} style={{ width: `${Math.min((m.value / (m.threshold * 2)) * 100, 100)}%` }} />
              </div>
            </GlassCard>
          )
        })}
      </motion.div>

      {/* Active violations */}
      {health.violations.filter(v => v.severity !== 'fair').length > 0 && (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Active Review Items</GlassCardTitle>
              <span className="text-xs text-muted-foreground">
                {health.violations.filter(v => v.severity === 'violation').length} violation
                {health.violations.filter(v => v.severity === 'violation').length !== 1 ? 's' : ''}
              </span>
            </GlassCardHeader>
            <div className="space-y-3">
              {health.violations.map((v, i) => (
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
            <p>
              <strong className="text-foreground">Health score 78 — needs attention.</strong>{' '}
              The AI model is making fair decisions overall, but we found differences across racial and income groups
              that need review. A score of 100 means every demographic group receives equivalent treatment.
            </p>
            <p>
              <strong className="text-destructive">Two violations found:</strong> Black children are
              flagged as high-risk 16 percentage points more often than White children, even when their
              actual disruption rates are similar. Low-income children also receive lower placement match scores.
              These differences may reflect historical inequities in the training data, not the individual child's needs.
            </p>
            <p>
              <strong className="text-warning">One item watching:</strong> The individual fairness score
              of 0.74 means some similar children receive different risk scores. This usually improves as more
              data is collected.
            </p>
            <p className="text-xs text-muted-foreground/60 mt-2">
              Thresholds follow the{' '}
              <a href="#" className="text-primary hover:underline">AI Fairness & Bias Audit Specification</a>.
              Demographic parity threshold: 0.05. BAR threshold: 1.0. Individual consistency threshold: 0.85.
            </p>
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  )
}

// ── Demographic Breakdown Tab ────────────────────────────────────────

function DemographicBreakdownTab() {
  const attributes = [
    {
      key: 'race',
      label: 'Race & Ethnicity',
      groups: [
        { label: 'Black or African American', highRiskRate: 0.38, count: 45, barColor: '#f97316' },
        { label: 'Hispanic or Latino',        highRiskRate: 0.24, count: 38, barColor: '#f59e0b' },
        { label: 'White',                     highRiskRate: 0.22, count: 120, barColor: '#06b6d4' },
        { label: 'Asian',                     highRiskRate: 0.18, count: 22, barColor: '#10b981' },
        { label: 'Other / Multiracial',       highRiskRate: 0.20, count: 31, barColor: '#6366f1' },
      ],
      insight: 'Black children are flagged high-risk at nearly double the rate of White children. This gap exceeds the acceptable threshold.',
      status: 'violation' as Status,
    },
    {
      key: 'ses',
      label: 'Income Level (FPL %)',
      groups: [
        { label: 'Lowest (0–100% FPL)',  highRiskRate: 0.35, count: 52, barColor: '#f97316' },
        { label: 'Low-Middle (101–200%)', highRiskRate: 0.28, count: 48, barColor: '#f59e0b' },
        { label: 'Middle (201–300%)',     highRiskRate: 0.24, count: 35, barColor: '#06b6d4' },
        { label: 'Highest (301%+)',       highRiskRate: 0.19, count: 30, barColor: '#10b981' },
      ],
      insight: 'Children from the lowest-income families are 1.8× more likely to receive high-risk labels than those from the highest-income families.',
      status: 'violation' as Status,
    },
    {
      key: 'zip',
      label: 'Geographic Area (ZIP prefix)',
      groups: [
        { label: '606 — South Side Chicago', highRiskRate: 0.32, count: 28, barColor: '#f97316' },
        { label: '902 — Los Angeles',        highRiskRate: 0.28, count: 22, barColor: '#f59e0b' },
        { label: '770 — Houston',            highRiskRate: 0.25, count: 18, barColor: '#f59e0b' },
        { label: '100 — New York City',      highRiskRate: 0.21, count: 35, barColor: '#06b6d4' },
        { label: '981 — Seattle',            highRiskRate: 0.17, count: 15, barColor: '#10b981' },
      ],
      insight: 'Geographic disparities correlate strongly with income and race. ZIP codes with higher poverty rates show higher high-risk rates.',
      status: 'watch' as Status,
    },
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

      {attributes.length === 0 ? (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <div className="text-center py-8 space-y-3">
              <p className="text-sm text-muted-foreground">No demographic data available yet.</p>
              <p className="text-xs text-muted-foreground/60 max-w-md mx-auto">
                Demographic breakdowns require race, income, and zip code data collected at intake.
                These fields are stored on each child's profile (children.race, children.fpl_percent,
                children.zip_code). Data appears once at least 20 children per demographic group have
                received an AI decision.
              </p>
            </div>
          </GlassCard>
        </motion.div>
      ) : attributes.map((attr) => (
        <motion.div key={attr.key} variants={item}>
          <GlassCard hover={false}>
            <GlassCardHeader>
              <div className="flex items-center gap-2">
                <GlassCardTitle>{attr.label}</GlassCardTitle>
                <StatusBadge status={attr.status} label={
                  attr.status === 'violation' ? 'Threshold Exceeded' :
                  attr.status === 'watch' ? 'Monitor' : 'Within Threshold'
                } />
              </div>
              <span className="text-xs text-muted-foreground">
                {attr.groups.reduce((s, g) => s + g.count, 0)} children
              </span>
            </GlassCardHeader>

            {/* Horizontal bar chart */}
            <div className="space-y-3">
              {attr.groups.map((group) => {
                const pct = (group.highRiskRate * 100).toFixed(0)
                return (
                  <div key={group.label} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-foreground">{group.label}</span>
                      <span className="text-xs text-muted-foreground">
                        <span className={cn(
                          'font-semibold',
                          group.highRiskRate > 0.30 ? 'text-destructive' :
                          group.highRiskRate > 0.20 ? 'text-warning' : 'text-success',
                        )}>{pct}%</span>
                        {' · '}n={group.count}
                      </span>
                    </div>
                    <div className="h-4 rounded-full bg-border-light overflow-hidden relative">
                      <div
                        className="h-full rounded-full transition-all duration-700"
                        style={{
                          width: `${pct}%`,
                          backgroundColor: group.barColor,
                        }}
                      />
                      {/* Population average reference line */}
                      {attr.key === 'race' && (
                        <div className="absolute top-0 bottom-0 w-0.5 bg-foreground/30"
                          style={{ left: '26%' }} />
                      )}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Plain language insight */}
            <div className={cn(
              'mt-4 p-3 rounded-lg border text-sm',
              attr.status === 'violation'
                ? 'bg-destructive/5 border-destructive/20'
                : 'bg-warning/5 border-warning/20',
            )}>
              <div className="flex items-start gap-2">
                {attr.status === 'violation'
                  ? <AlertTriangle className="w-4 h-4 text-destructive mt-0.5 shrink-0" />
                  : <Info className="w-4 h-4 text-warning mt-0.5 shrink-0" />
                }
                <div>
                  <p className="text-foreground font-medium">
                    {attr.status === 'violation' ? 'Disparity detected' : 'Trend being monitored'}
                  </p>
                  <p className="text-muted-foreground text-xs mt-0.5">{attr.insight}</p>
                </div>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      ))}

      {/* Methodology note with expanded explanation */}
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
                  group's rate differs substantially from another's. The dotted reference line on each chart
                  shows the population average. Our threshold is a 5 percentage-point difference between
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
  const [searched, setSearched] = useState(false)

  // Mock result — will be fetched from API
  const result = {
    childId: 'CH-A0427',
    age: 9,
    decisionType: 'Crisis Risk Assessment',
    decisionDate: '2026-05-28',
    score: 72.4,
    label: 'High Risk',
    modelVersion: 'crisis_drift_v2.3',
    humanOverride: false,
    features: [
      { name: 'Incident severity trend', impact: 'increasing risk', description: 'Incidents have been getting more serious over the past 4 weeks — from minor disruptions to a runaway attempt.', weight: 35 },
      { name: 'School attendance', impact: 'increasing risk', description: 'School attendance dropped from 92% to 70% over the past month — 22 percentage points below this child\'s normal baseline.', weight: 28 },
      { name: 'Caseworker visit sentiment', impact: 'increasing risk', description: 'Caseworker notes have become more negative over 3 visits — from "cooperative" to "child threatened to run away."', weight: 20 },
      { name: 'Medication compliance', impact: 'increasing risk', description: 'Medication adherence fell from 95% to 77%. 13 of 56 doses were missed in the last 28 days.', weight: 12 },
      { name: 'Communication with foster parent', impact: 'increasing risk', description: 'Foster parent response time increased from 5 hours to 18 hours on average. May indicate caregiver fatigue.', weight: 5 },
    ],
  }

  const handleSearch = () => {
    if (childId.trim()) setSearched(true)
  }

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
          <Button onClick={handleSearch} disabled={!childId.trim()}>
            Explore
          </Button>
        </div>
      </motion.div>

      {searched && result && (
        <motion.div variants={item} className="space-y-4">
          {/* Decision header */}
          <GlassCard hover={false}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="text-base font-bold text-foreground">{result.childId}</h3>
                  <span className="text-xs text-muted-foreground">Age {result.age}</span>
                </div>
                <p className="text-sm text-muted-foreground">
                  {result.decisionType} · {result.decisionDate}
                </p>
                {result.humanOverride && (
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
                    result.score >= 80 ? 'text-destructive' :
                    result.score >= 60 ? 'text-warning' : 'text-success',
                  )}>{result.score}</span>
                  <span className="text-xs text-muted-foreground">/ 100</span>
                </div>
                <span className={cn(
                  'text-xs font-medium',
                  result.score >= 80 ? 'text-destructive' :
                  result.score >= 60 ? 'text-warning' : 'text-success',
                )}>{result.label}</span>
              </div>
            </div>
          </GlassCard>

          {/* Feature contributions */}
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>What influenced this decision</GlassCardTitle>
              <span className="text-xs text-muted-foreground">
                Model: {result.modelVersion}
              </span>
            </GlassCardHeader>
            <div className="space-y-3">
              {result.features.map((f, i) => (
                <div key={i} className="space-y-1">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={cn(
                        'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0',
                        f.impact === 'increasing risk'
                          ? 'bg-destructive/15 text-destructive'
                          : 'bg-success/15 text-success',
                      )}>{i + 1}</span>
                      <span className="text-sm text-foreground truncate">{f.name}</span>
                    </div>
                    <span className={cn(
                      'text-xs font-medium shrink-0',
                      f.impact === 'increasing risk' ? 'text-destructive' : 'text-success',
                    )}>
                      +{f.weight}% {f.impact}
                    </span>
                  </div>
                  {/* Contribution bar */}
                  <div className="h-2 rounded-full bg-border-light overflow-hidden">
                    <div
                      className={cn(
                        'h-full rounded-full',
                        f.impact === 'increasing risk' ? 'bg-destructive/60' : 'bg-success/60',
                      )}
                      style={{ width: `${f.weight}%` }}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground pl-7">{f.description}</p>
                </div>
              ))}
            </div>
          </GlassCard>

          {/* Recommendations from this decision */}
          <GlassCard hover={false}>
            <GlassCardHeader>
              <GlassCardTitle>Recommended actions at time of decision</GlassCardTitle>
            </GlassCardHeader>
            <div className="flex flex-wrap gap-2">
              {['Schedule urgent therapy review', 'Initiate school liaison meeting', 'Increase caseworker visits to weekly', 'Assign mentor support'].map((r, i) => (
                <span key={i} className="px-3 py-1.5 rounded-full text-xs bg-primary/10 text-primary border border-primary/20">
                  {r}
                </span>
              ))}
            </div>
          </GlassCard>

          {/* What to do next */}
          <GlassCard hover={false}>
            <div className="flex items-start gap-3 text-sm text-muted-foreground">
              <Info className="w-4 h-4 mt-0.5 shrink-0 text-primary" />
              <div>
                <p className="font-medium text-foreground mb-1">What this means</p>
                <p className="text-xs leading-relaxed">
                  The AI flagged this child as high-risk because of a combination of worsening incidents,
                  declining school attendance, and increasing negativity in caseworker visits. No single
                  factor caused this score — it is the combination that triggered the alert.
                  If you disagree with this assessment, you can{' '}
                  <button className="text-primary hover:underline">submit feedback</button> to help
                  improve future predictions.
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      )}

      {searched && !result && (
        <motion.div variants={item}>
          <GlassCard hover={false}>
            <div className="text-center py-8 space-y-3">
              <p className="text-sm text-muted-foreground">
                No decision found for "{childId}".
              </p>
              <div className="max-w-md mx-auto text-xs text-muted-foreground/60 space-y-1">
                <p>Decisions are stored in the ML decision audit table — a tamper-evident log of every AI recommendation.</p>
                <p>If no result appears, the child may not have received an AI decision yet, or the child ID may differ from the one used at intake. Try searching by a different ID or check the <button className="text-primary hover:underline">full decision list</button>.</p>
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

  const handleGenerate = () => {
    setGenerating(true)
    // Simulate generation
    setTimeout(() => setGenerating(false), 2500)
  }

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
                    <BarChart3 className="w-4 h-4" />{/* Actually Table icon, using BarChart3 as proxy */}
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
                    <p>Total decisions</p>
                    <p className="text-foreground font-medium">12,450</p>
                  </div>
                  <div>
                    <p>Models covered</p>
                    <p className="text-foreground font-medium">3 (crisis, risk, placement)</p>
                  </div>
                  <div>
                    <p>Hash chain</p>
                    <p className="text-success font-medium">Intact</p>
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
                      <p className="text-xs text-muted-foreground">5 attributes · 18 demographic groups</p>
                    </div>
                  </div>
                )}
                {includeDecisions && (
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                    <BarChart3 className="w-4 h-4 text-secondary" />
                    <div className="min-w-0">
                      <p className="text-foreground">Decision records</p>
                      <p className="text-xs text-muted-foreground">12,450 rows · all decision types</p>
                    </div>
                  </div>
                )}
                {includeHashChain && (
                  <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                    <Shield className="w-4 h-4 text-success" />
                    <div className="min-w-0">
                      <p className="text-foreground">Hash chain verification</p>
                      <p className="text-xs text-muted-foreground">Chain intact · 38,741 hashes verified</p>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                  <TrendingUp className="w-4 h-4 text-accent" />
                  <div className="min-w-0">
                    <p className="text-foreground">Weekly fairness trends</p>
                    <p className="text-xs text-muted-foreground">24 weekly snapshots · all metrics</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 p-3 rounded-lg bg-glass">
                  <Scale className="w-4 h-4 text-warning" />
                  <div className="min-w-0">
                    <p className="text-foreground">Active review items</p>
                    <p className="text-xs text-muted-foreground">2 violations · 1 watching</p>
                  </div>
                </div>
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
      <div className="flex items-center gap-3">
        <Scale className="w-6 h-6 text-accent" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">Fairness & Bias Audit</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            AI placement fairness monitoring for compliance officers and agency directors
          </p>
        </div>
      </div>

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
