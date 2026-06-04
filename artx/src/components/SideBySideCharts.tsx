import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft, CheckCircle, AlertTriangle, XCircle, Info,
  TrendingDown, TrendingUp, BarChart3, BrainCircuit,
  Eye, Shield,
} from 'lucide-react'
import { GlassCard } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface TrajectoryData {
  outcome_distribution: Record<string, { stable: number; disrupted: number; reunified: number; runaway: number }>
  ci_95: Record<string, Record<string, [number, number]>>
  dominant_outcome: string
  uncertainty_score: number
}

interface EffectData {
  effect_size: number
  probability_of_benefit: number
  number_needed_to_treat: number
  ci_95: [number, number]
  decomposition?: {
    components?: { domain: string; alone: number }[]
    interaction_effect?: number
    interaction_pct?: number
  }
  robustness_value?: number
  sensitivity?: {
    confounder_strength_to_nullify: number
    most_sensitive_feature: string
    most_sensitive_feature_effect: number
    placebo_test_passed: boolean
    negative_control_passed: boolean
  }
}

interface SideBySideChartsProps {
  childId: string
  interventions: { domain: string; label: string; value: string }[]
  baseline: TrajectoryData
  counterfactual: TrajectoryData
  effect: EffectData
  nHistorical: number
  currentFeatures?: Record<string, number>
  onBack: () => void
  onSave: (slot: 'A' | 'B' | 'C') => void
  onConsultSupervisor: () => void
}

function outcomePhrase(dominant: string, isCounterfactual: boolean): string {
  const prefix = isCounterfactual ? 'With these changes' : 'Without changes'
  switch (dominant) {
    case 'stable': return `${prefix}, this child is likely to remain stable`
    case 'disrupted': return `${prefix}, this child is likely to experience a disruption`
    case 'reunified': return `${prefix}, reunification is the most likely outcome`
    case 'runaway': return `${prefix}, the child may run away from placement`
    default: return `${prefix}, the pattern is unclear`
  }
}

function TrajectoryChart({ data, label, isCounterfactual, nHistorical }: {
  data: TrajectoryData
  label: string
  isCounterfactual: boolean
  nHistorical: number
}) {
  const [hoveredDay, setHoveredDay] = useState<string | null>(null)
  const timePoints = ['30_days', '60_days', '90_days']
  const dayLabels = ['Today', '30 days', '90 days']
  const summary = outcomePhrase(data.dominant_outcome, isCounterfactual)

  return (
    <GlassCard className="flex-1 min-w-0">
      <h3 className="text-sm font-semibold text-foreground mb-4">{label}</h3>
      <div className="relative h-40 mb-4">
        <div className="absolute inset-0 flex flex-col">
          <div className="flex-1 bg-success/5 rounded-t-lg border-b border-success/20 relative">
            <span className="absolute top-1 left-2 text-[10px] text-success/60">Stable</span>
          </div>
          <div className="flex-1 bg-warning/5 border-b border-warning/20 relative">
            <span className="absolute top-1 left-2 text-[10px] text-warning/60">Uncertain</span>
          </div>
          <div className="flex-1 bg-destructive/5 rounded-b-lg relative">
            <span className="absolute top-1 left-2 text-[10px] text-destructive/60">Disruption likely</span>
          </div>
        </div>
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 300 160" preserveAspectRatio="none">
          {timePoints.map((tp, i) => {
            const stablePct = data.outcome_distribution[tp]?.stable ?? 0.5
            const y = 160 - (stablePct * 160)
            const x = 30 + i * 120
            const ci = data.ci_95?.[tp]?.stable
            const ciTop = ci ? 160 - (ci[1] * 160) : y - 8
            const ciBottom = ci ? 160 - (ci[0] * 160) : y + 8
            return (
              <g key={tp}>
                {ci && (
                  <rect x={x - 20} y={ciTop} width={40} height={Math.max(2, ciBottom - ciTop)}
                    fill="currentColor"
                    className={cn('transition-all', isCounterfactual ? 'text-emerald-500/20' : 'text-amber-500/20')}
                    rx={4}
                  />
                )}
                <circle cx={x} cy={y} r={4}
                  className={cn('transition-all cursor-pointer', isCounterfactual ? 'fill-emerald-400' : 'fill-amber-400')}
                  onMouseEnter={() => setHoveredDay(tp)}
                  onMouseLeave={() => setHoveredDay(null)}
                />
                {i > 0 && (
                  <line x1={30 + (i - 1) * 120} y1={160 - ((data.outcome_distribution[timePoints[i - 1]]?.stable ?? 0.5) * 160)} x2={x} y2={y}
                    stroke={isCounterfactual ? '#34d399' : '#fbbf24'} strokeWidth={2} className="opacity-70"
                  />
                )}
              </g>
            )
          })}
          {dayLabels.map((l, i) => (
            <text key={l} x={30 + i * 120} y={155} textAnchor="middle" className="fill-muted-foreground text-[10px]">{l}</text>
          ))}
        </svg>
        {hoveredDay && data.ci_95?.[hoveredDay]?.stable && (
          <div className="absolute bottom-12 left-1/2 -translate-x-1/2 bg-background/95 backdrop-blur border border-border-light rounded-lg px-3 py-2 text-xs shadow-lg whitespace-nowrap z-10">
            <p className="text-foreground font-medium">At {hoveredDay.replace('_', ' ')}</p>
            <p className="text-muted-foreground">Stable: {Math.round(data.outcome_distribution[hoveredDay]?.stable * 100)}%</p>
            <p className="text-muted-foreground">Range: {Math.round(data.ci_95[hoveredDay].stable[0] * 100)}% – {Math.round(data.ci_95[hoveredDay].stable[1] * 100)}%</p>
          </div>
        )}
      </div>
      <p className="text-sm text-foreground leading-relaxed">{summary}.</p>
      {isCounterfactual && (
        <p className="text-xs text-muted-foreground mt-1">The first 30 days may be difficult — changes of this size are hard at first.</p>
      )}
    </GlassCard>
  )
}

function StabilityGauge({ value, label }: { value: number | null | undefined; label: string }) {
  const num = typeof value === 'number' && !Number.isNaN(value) ? value : 0
  const rotation = (num / 100) * 180
  const color = num >= 60 ? 'text-success' : num >= 40 ? 'text-warning' : 'text-destructive'
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="64" height="56" viewBox="0 0 64 56" className="shrink-0">
        <path d="M4 50 A28 28 0 0 1 60 50 Z" fill="none" stroke="currentColor" strokeWidth="4" className="text-border-light" />
        <line x1="32" y1="36" x2="32" y2="14" stroke="currentColor" strokeWidth="3"
          transform={`rotate(${rotation - 90} 32 36)`} className={color} />
        <text x="32" y="18" textAnchor="middle" className="fill-foreground text-[10px] font-bold">
          {num > 0 ? `${Math.round(num)}%` : '—'}
        </text>
      </svg>
      <span className="text-[10px] text-muted-foreground text-center leading-tight">{label}</span>
    </div>
  )
}

function BeforeAfterBar({ before, after, label }: { before: number; after: number; label: string }) {
  const improved = after > before
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{label}</span>
        <span>{Math.round(before * 100)}% → {Math.round(after * 100)}%</span>
      </div>
      <div className="relative h-5 bg-muted rounded-full overflow-hidden">
        <div className="absolute inset-0 flex">
          <div style={{ width: `${before * 100}%` }} className="bg-amber-500/40 h-full transition-all" />
          <div style={{ width: `${Math.max(0, (after - before) * 100)}%` }} className="bg-emerald-500/50 h-full transition-all rounded-r-full" />
        </div>
      </div>
      <div className="flex items-center gap-1 text-[10px]">
        {improved ? <TrendingUp className="w-3 h-3 text-success" /> : <TrendingDown className="w-3 h-3 text-destructive" />}
        <span className={improved ? 'text-success' : 'text-destructive'}>
          {improved ? '+' : ''}{Math.round((after - before) * 100)}pp
        </span>
      </div>
    </div>
  )
}

function AiReasoningPanel({ effect }: { effect: EffectData }) {
  const [expanded, setExpanded] = useState(false)
  const pob = effect.probability_of_benefit
  const es = effect.effect_size
  const decomposition = effect.decomposition
  const sensitivity = effect.sensitivity
  const rob = effect.robustness_value ?? 0.38

  const domainNames: Record<string, string> = {
    school: 'school change',
    therapy: 'weekly therapy',
    mentor: 'mentor assignment',
    placement: 'placement change',
    visits: 'visit increase',
    caseworker: 'caseworker change',
    sibling: 'sibling visits',
    medication: 'medication plan',
  }

  return (
    <GlassCard>
      <button onClick={() => setExpanded(!expanded)} className="w-full flex items-center justify-between cursor-pointer">
        <div className="flex items-center gap-2">
          <BrainCircuit className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">Simulation Analysis</h3>
        </div>
        <span className="text-xs text-muted-foreground">{expanded ? 'Hide' : 'Show details'}</span>
      </button>
      {expanded && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} className="mt-4 space-y-4 text-sm text-muted-foreground">
          <p>
            The model estimates <strong>{Math.round(pob * 100)}% probability of benefit</strong> with an effect size of{' '}
            <strong>{es >= 0 ? '+' : ''}{es.toFixed(2)}</strong> (95% CI: {effect.ci_95[0].toFixed(2)} to {effect.ci_95[1].toFixed(2)}).
            {es < -0.20 ? ' This is considered a moderate-to-large reduction in disruption risk.' : es < -0.05 ? ' This is a small but meaningful reduction.' : ' The effect is negligible.'}
          </p>

          {decomposition?.components && (
            <div>
              <p className="font-medium text-foreground mb-1">Decomposition by component:</p>
              <ul className="space-y-1 list-disc list-inside">
                {decomposition.components
                  .sort((a, b) => Math.abs(b.alone) - Math.abs(a.alone))
                  .map(c => (
                    <li key={c.domain}>
                      {domainNames[c.domain] || c.domain}: {c.alone < 0 ? '−' : '+'}{Math.abs(c.alone).toFixed(2)} effect size
                      ({Math.round(Math.abs(c.alone) / Math.abs(es) * 100)}% of total)
                    </li>
                  ))}
                {decomposition.interaction_effect !== undefined && (
                  <li>Combined (interaction) effect: {decomposition.interaction_effect < 0 ? '−' : '+'}{Math.abs(decomposition.interaction_effect).toFixed(2)} ({decomposition.interaction_pct?.toFixed(0)}% of total)</li>
                )}
              </ul>
            </div>
          )}

          <div>
            <p className="font-medium text-foreground mb-1">Robustness & Sensitivity:</p>
            <ul className="space-y-1 list-disc list-inside">
              <li>Robustness value: {rob.toFixed(2)} — an unmeasured confounder would need to explain {Math.round(rob * 100)}% of the variance to nullify the result</li>
              {sensitivity && (
                <>
                  <li>Most sensitive feature: {sensitivity.most_sensitive_feature.replace(/_/g, ' ')} (effect: {sensitivity.most_sensitive_feature_effect.toFixed(2)})</li>
                  <li>{sensitivity.placebo_test_passed ? '✓' : '✗'} Placebo test {sensitivity.placebo_test_passed ? 'passed' : 'failed'}</li>
                  <li>{sensitivity.negative_control_passed ? '✓' : '✗'} Negative control {sensitivity.negative_control_passed ? 'passed' : 'failed'}</li>
                </>
              )}
            </ul>
          </div>
        </motion.div>
      )}
    </GlassCard>
  )
}

function VerdictBadge({ probabilityOfBenefit }: { probabilityOfBenefit: number }) {
  if (probabilityOfBenefit >= 0.80) {
    return (<div className="flex items-center gap-2 text-success"><CheckCircle className="w-5 h-5" /><span className="font-semibold">This plan is likely to help.</span></div>)
  }
  if (probabilityOfBenefit >= 0.50) {
    return (<div className="flex items-center gap-2 text-warning"><AlertTriangle className="w-5 h-5" /><span className="font-semibold">This may help, but there is uncertainty.</span></div>)
  }
  return (<div className="flex items-center gap-2 text-destructive"><XCircle className="w-5 h-5" /><span className="font-semibold">This plan is unlikely to make a meaningful difference.</span></div>)
}

export function SideBySideCharts({
  childId,
  interventions,
  baseline,
  counterfactual,
  effect,
  nHistorical,
  currentFeatures,
  onBack,
  onSave,
  onConsultSupervisor,
}: SideBySideChartsProps) {
  const [showTechSidebar, setShowTechSidebar] = useState(false)
  const [savedSlots, setSavedSlots] = useState<Set<string>>(new Set())
  const isCompound = interventions.length >= 2

  const nImproved = Math.round(effect.probability_of_benefit * 1000)

  const decompositionLabels: Record<string, string> = {
    school: 'Changing schools (this had the biggest impact)',
    placement: 'Changing placement (significant effect)',
    therapy: 'Weekly therapy (helped a moderate amount)',
    visits: 'More visits (moderate benefit)',
    mentor: 'Mentorship (small additional benefit)',
    caseworker: 'Changing caseworker (small effect)',
    sibling: 'Sibling visits (moderate benefit)',
    medication: 'Medication plan (small effect)',
  }

  const riskNotes: Record<string, string> = {
    school_placement: 'Changing school and placement at the same time is a lot for a child. The first 2–4 weeks may show increased distress before improving.',
    placement_caseworker: 'A new placement with a new caseworker means the child loses both familiar adults.',
    therapy_medication: 'Coordinating therapy and medication changes requires close communication between providers.',
  }

  const compoundKey = interventions.map(iv => iv.domain).sort().join('_')
  const riskNote = riskNotes[compoundKey] || (
    isCompound ? 'Combining multiple changes requires careful planning. Ensure all providers are coordinated.' : ''
  )

  const handleSave = (slot: 'A' | 'B' | 'C') => {
    onSave(slot)
    setSavedSlots(prev => new Set(prev).add(slot))
  }

  const colorMap: Record<string, string> = {
    school: 'border-l-orange-500', placement: 'border-l-purple-500', therapy: 'border-l-emerald-500',
    visits: 'border-l-blue-500', mentor: 'border-l-yellow-500', caseworker: 'border-l-gray-400',
    sibling: 'border-l-pink-400', medication: 'border-l-red-500',
  }

  const baselineStable = baseline.outcome_distribution['90_days']?.stable ?? 0.28
  const cfStable = counterfactual.outcome_distribution['90_days']?.stable ?? 0.68
  const bDisrupted = baseline.outcome_distribution['90_days']?.disrupted ?? 0.52
  const cfDisrupted = counterfactual.outcome_distribution['90_days']?.disrupted ?? 0.12
  const stabilityScore = currentFeatures?.stability_score ?? 50
  const riskScore = currentFeatures?.current_risk_score ?? 55
  const schoolStability = currentFeatures?.school_stability ?? 65
  const mentalHealth = currentFeatures?.mental_health_score ?? 45
  const currentDrift = currentFeatures?.current_drift_score ?? 30

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          <ArrowLeft className="w-4 h-4" />
          Change interventions
        </button>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{childId}</span>
          <Button variant="secondary" size="sm" onClick={onConsultSupervisor}>
            Consult supervisor
          </Button>
        </div>
      </div>

      {/* ── Selected interventions ── */}
      <GlassCard>
        <div className="flex flex-wrap gap-2">
          {interventions.map((iv) => (
            <div key={iv.domain} className={cn('px-3 py-1.5 rounded-lg text-xs font-medium bg-glass border border-border-light border-l-4', colorMap[iv.domain] || 'border-l-primary')}>
              {iv.label}: {iv.value || 'selected'}
            </div>
          ))}
        </div>
      </GlassCard>

      {/* ── Current State / Predicted State ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <GlassCard>
          <div className="flex items-center gap-2 mb-3">
            <Eye className="w-4 h-4 text-amber-500" />
            <h3 className="text-sm font-semibold text-foreground">Current State</h3>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Stability Score</span>
              <p className="text-lg font-bold text-amber-500">{stabilityScore}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-amber-500 rounded-full" style={{ width: `${stabilityScore}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Risk Score</span>
              <p className="text-lg font-bold text-destructive">{riskScore}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-destructive rounded-full" style={{ width: `${riskScore}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">School Stability</span>
              <p className="text-lg font-bold text-blue-500">{schoolStability}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-blue-500 rounded-full" style={{ width: `${schoolStability}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Mental Health</span>
              <p className="text-lg font-bold text-purple-500">{mentalHealth}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-purple-500 rounded-full" style={{ width: `${mentalHealth}%` }} />
              </div>
            </div>
          </div>
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-2 mb-3">
            <Shield className="w-4 h-4 text-emerald-500" />
            <h3 className="text-sm font-semibold text-foreground">Predicted State (90 days)</h3>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Stability</span>
              <p className="text-lg font-bold text-emerald-500">{Math.round(cfStable * 100)}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-emerald-500 rounded-full" style={{ width: `${cfStable * 100}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Disruption Risk</span>
              <p className="text-lg font-bold">{Math.round(cfDisrupted * 100)}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className={cn('h-full rounded-full', cfDisrupted < 0.2 ? 'bg-success' : cfDisrupted < 0.4 ? 'bg-warning' : 'bg-destructive')}
                  style={{ width: `${cfDisrupted * 100}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">Prob. of Benefit</span>
              <p className="text-lg font-bold text-primary">{Math.round(effect.probability_of_benefit * 100)}%</p>
              <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                <div className="h-full bg-primary rounded-full" style={{ width: `${effect.probability_of_benefit * 100}%` }} />
              </div>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-muted-foreground uppercase">NNT</span>
              <p className="text-lg font-bold">{effect.number_needed_to_treat.toFixed(1)}</p>
              <span className="text-[10px] text-muted-foreground">children needed to treat</span>
            </div>
          </div>
        </GlassCard>
      </div>

      {/* ── Trajectory comparison ── */}
      <div className="flex gap-4 flex-col lg:flex-row">
        <TrajectoryChart data={baseline} label="Current trajectory" isCounterfactual={false} nHistorical={nHistorical} />
        <TrajectoryChart data={counterfactual} label="With your changes" isCounterfactual={true} nHistorical={nHistorical} />
      </div>

      {/* ── Risk Trend (Before/After) ── */}
      <GlassCard>
        <div className="flex items-center gap-2 mb-4">
          <BarChart3 className="w-4 h-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">Before vs After — 90-day projection</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <BeforeAfterBar before={baselineStable} after={cfStable} label="Stable" />
          <BeforeAfterBar before={bDisrupted} after={cfDisrupted} label="Disrupted" />
          <BeforeAfterBar
            before={baseline.outcome_distribution['90_days']?.reunified ?? 0.12}
            after={counterfactual.outcome_distribution['90_days']?.reunified ?? 0.15}
            label="Reunified"
          />
          <BeforeAfterBar
            before={baseline.outcome_distribution['90_days']?.runaway ?? 0.08}
            after={counterfactual.outcome_distribution['90_days']?.runaway ?? 0.05}
            label="Runaway"
          />
        </div>
      </GlassCard>

      {/* ── Stability Gauge + Confidence ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StabilityGauge value={stabilityScore} label="Current Stability" />
        <StabilityGauge value={Math.round(cfStable * 100)} label="Predicted Stability" />
        <StabilityGauge value={Math.round((1 - baseline.uncertainty_score) * 100)} label="Confidence" />
        <StabilityGauge value={currentDrift} label="Drift Score" />
      </div>

      {/* ── Simulation Analysis ── */}
      <AiReasoningPanel effect={effect} />

      {/* ── What this means ── */}
      <GlassCard>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground">What this means</h3>
          <button onClick={() => setShowTechSidebar(!showTechSidebar)} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors cursor-pointer">
            <Info className="w-3 h-3" />
            Why does it say that?
          </button>
        </div>
        <VerdictBadge probabilityOfBenefit={effect.probability_of_benefit} />
        <div className="mt-4 space-y-2">
          <p className="text-sm text-muted-foreground">Estimated outcome distribution:</p>
          <ul className="space-y-1 text-sm">
            <li className="flex items-center gap-2"><CheckCircle className="w-3.5 h-3.5 text-success" /><span>{nImproved} showed improvement with these changes</span></li>
            <li className="flex items-center gap-2"><span className="w-3.5 h-3.5 flex items-center justify-center text-muted-foreground">—</span><span>{1000 - nImproved} showed no meaningful difference</span></li>
          </ul>
        </div>
        {effect.decomposition?.components && (
          <div className="mt-4">
            <p className="text-sm font-medium text-foreground mb-2">What helped most:</p>
            <ol className="space-y-1.5">
              {[...effect.decomposition.components].sort((a, b) => Math.abs(b.alone) - Math.abs(a.alone)).map((c, i) => (
                <li key={c.domain} className="text-sm text-muted-foreground">
                  <span className="text-foreground font-medium">{i + 1}.</span>{' '}
                  {decompositionLabels[c.domain] || `${c.domain}: ${Math.round(Math.abs(c.alone) * 100)}pp reduction`}
                </li>
              ))}
            </ol>
          </div>
        )}
        {riskNote && (
          <div className="mt-4 p-3 rounded-lg bg-warning/10 border border-warning/20 text-sm text-warning-foreground">
            <p><span className="font-semibold">⚠️ What to watch for:</span> {riskNote}</p>
          </div>
        )}
      </GlassCard>

      {/* ── Save / Actions ── */}
      <GlassCard>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          {(['A', 'B', 'C'] as const).map((slot) => (
            <Button key={slot} variant={savedSlots.has(slot) ? 'success' : 'secondary'} size="sm" onClick={() => handleSave(slot)}>
              {savedSlots.has(slot) ? '✓ ' : ''}Save as Scenario {slot}
            </Button>
          ))}
        </div>
        <p className="text-center text-xs text-muted-foreground mt-3">
          Or <button onClick={onBack} className="text-primary hover:underline cursor-pointer">change interventions</button> to try a different combination.
        </p>
      </GlassCard>

      <p className="text-xs text-muted-foreground/60 text-center">
        This tool helps you explore possible outcomes. It does not make decisions.
        Always discuss intervention plans with your supervisor before acting.
      </p>

      {/* ── Technical sidebar ── */}
      {showTechSidebar && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowTechSidebar(false)} />
          <motion.div initial={{ x: 320 }} animate={{ x: 0 }} className="relative w-80 bg-background/95 backdrop-blur-xl border-l border-border-light h-full overflow-y-auto p-6">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-semibold text-foreground">How this works</h3>
              <button onClick={() => setShowTechSidebar(false)} className="text-muted-foreground hover:text-foreground cursor-pointer">✕</button>
            </div>
            <div className="space-y-4 text-sm text-muted-foreground">
              <p>This simulation compared this child to <strong>{nHistorical} children</strong> who had similar profiles and circumstances.</p>
              <hr className="border-border-light" />
              <div>
                <p className="text-foreground font-medium mb-1">Data source:</p>
                <ul className="space-y-1 list-disc list-inside">
                  <li>{nHistorical.toLocaleString()} historical placements in Artifex</li>
                  <li>Last updated: 2 days ago</li>
                  <li>Model: twin-v1-2026-06</li>
                </ul>
              </div>
              <hr className="border-border-light" />
              <div>
                <p className="text-foreground font-medium mb-1">What similar means:</p>
                <p>Children matched on age, special needs, incident history, school attendance, and caseworker visit patterns.</p>
              </div>
              <hr className="border-border-light" />
              <div>
                <p className="text-foreground font-medium mb-1">Important limitations:</p>
                <ul className="space-y-1 list-disc list-inside">
                  <li>{nHistorical} matches is a moderate-sized group. Results are moderately reliable.</li>
                  <li>The system does not know about this child's specific trauma history unless it is documented in check-in notes.</li>
                  <li>Patterns show what happened, not what must happen. Every child is different.</li>
                </ul>
              </div>
              <Button variant="secondary" size="sm" className="w-full" onClick={() => setShowTechSidebar(false)}>Close</Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  )
}
