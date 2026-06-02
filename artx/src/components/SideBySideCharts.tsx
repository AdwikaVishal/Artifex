import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft, CheckCircle, AlertTriangle, XCircle, Info,
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
}

interface SideBySideChartsProps {
  childId: string
  interventions: { domain: string; label: string; value: string }[]
  baseline: TrajectoryData
  counterfactual: TrajectoryData
  effect: EffectData
  nHistorical: number
  onBack: () => void
  onSave: (slot: 'A' | 'B' | 'C') => void
  onConsultSupervisor: () => void
}

function confidencePhrase(n: number): string {
  if (n >= 100) return 'well-established pattern'
  if (n >= 50) return 'moderately reliable'
  return 'rough guide — limited data'
}

function outcomePhrase(dominant: string, isCounterfactual: boolean): string {
  const prefix = isCounterfactual ? 'With these changes' : 'Without changes'
  switch (dominant) {
    case 'stable':
      return `${prefix}, this child is likely to remain stable`
    case 'disrupted':
      return `${prefix}, this child is likely to experience a disruption`
    case 'reunified':
      return `${prefix}, reunification is the most likely outcome`
    case 'runaway':
      return `${prefix}, the child may run away from placement`
    default:
      return `${prefix}, the pattern is unclear`
  }
}

function TrajectoryChart({
  data,
  label,
  isCounterfactual,
  nHistorical,
}: {
  data: TrajectoryData
  label: string
  isCounterfactual: boolean
  nHistorical: number
}) {
  const [hoveredDay, setHoveredDay] = useState<string | null>(null)

  const timePoints = ['30_days', '60_days', '90_days']
  const dayLabels = ['Today', '30 days', '90 days']

  const dominant = data.dominant_outcome
  const summary = outcomePhrase(dominant, isCounterfactual)

  return (
    <GlassCard className="flex-1">
      <h3 className="text-sm font-semibold text-foreground mb-4">{label}</h3>

      <div className="relative h-40 mb-4">
        <div className="absolute inset-0 flex flex-col">
          {/* Qualitative zone labels */}
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

        {/* SVG trajectory */}
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
                  <rect
                    x={x - 20}
                    y={ciTop}
                    width={40}
                    height={Math.max(2, ciBottom - ciTop)}
                    fill="currentColor"
                    className={cn(
                      'transition-all',
                      isCounterfactual ? 'text-emerald-500/20' : 'text-amber-500/20',
                    )}
                    rx={4}
                  />
                )}
                <circle
                  cx={x}
                  cy={y}
                  r={4}
                  className={cn(
                    'transition-all cursor-pointer',
                    isCounterfactual ? 'fill-emerald-400' : 'fill-amber-400',
                  )}
                  onMouseEnter={() => setHoveredDay(tp)}
                  onMouseLeave={() => setHoveredDay(null)}
                />
                {i > 0 && (
                  <line
                    x1={30 + (i - 1) * 120}
                    y1={160 - ((data.outcome_distribution[timePoints[i - 1]]?.stable ?? 0.5) * 160)}
                    x2={x}
                    y2={y}
                    stroke={isCounterfactual ? '#34d399' : '#fbbf24'}
                    strokeWidth={2}
                    className="opacity-70"
                  />
                )}
              </g>
            )
          })}

          {/* X-axis labels */}
          {dayLabels.map((label, i) => (
            <text
              key={label}
              x={30 + i * 120}
              y={155}
              textAnchor="middle"
              className="fill-muted-foreground text-[10px]"
            >
              {label}
            </text>
          ))}
        </svg>

        {/* Hover tooltip */}
        {hoveredDay && data.ci_95?.[hoveredDay]?.stable && (
          <div className="absolute bottom-12 left-1/2 -translate-x-1/2 bg-background/95 backdrop-blur border border-border-light rounded-lg px-3 py-2 text-xs shadow-lg whitespace-nowrap z-10">
            <p className="text-foreground font-medium">At {hoveredDay.replace('_', ' ')}</p>
            <p className="text-muted-foreground">
              Stable: {Math.round(data.outcome_distribution[hoveredDay]?.stable * 100)}%
            </p>
            <p className="text-muted-foreground">
              Range: {Math.round(data.ci_95[hoveredDay].stable[0] * 100)}% – {Math.round(data.ci_95[hoveredDay].stable[1] * 100)}%
            </p>
          </div>
        )}
      </div>

      <p className="text-sm text-foreground leading-relaxed">
        {summary}.{' '}
        <span className="text-muted-foreground">
          Patterns from {nHistorical} similar children show this outcome.
        </span>
      </p>
      {isCounterfactual && (
        <p className="text-xs text-muted-foreground mt-1">
          The first 30 days may be difficult — changes of this size are hard at first.
        </p>
      )}
    </GlassCard>
  )
}

function VerdictBadge({ probabilityOfBenefit }: { probabilityOfBenefit: number }) {
  if (probabilityOfBenefit >= 0.80) {
    return (
      <div className="flex items-center gap-2 text-success">
        <CheckCircle className="w-5 h-5" />
        <span className="font-semibold">This plan is likely to help.</span>
      </div>
    )
  }
  if (probabilityOfBenefit >= 0.50) {
    return (
      <div className="flex items-center gap-2 text-warning">
        <AlertTriangle className="w-5 h-5" />
        <span className="font-semibold">This may help, but there is uncertainty.</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 text-destructive">
      <XCircle className="w-5 h-5" />
      <span className="font-semibold">This plan is unlikely to make a meaningful difference.</span>
    </div>
  )
}

export function SideBySideCharts({
  childId,
  interventions,
  baseline,
  counterfactual,
  effect,
  nHistorical,
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
    school_placement: 'Changing school and placement at the same time is a lot for a child. The first 2–4 weeks may show increased distress before improving. Plan for extra support during the transition period.',
    placement_caseworker: 'A new placement with a new caseworker means the child loses both familiar adults. Consider overlapping visits for the first 2 weeks.',
    therapy_medication: 'Coordinating therapy and medication changes requires close communication between providers. Confirm they are aware of each other\'s plans.',
  }

  const compoundKey = interventions.map(iv => iv.domain).sort().join('_')
  const riskNote = riskNotes[compoundKey] || (
    isCompound
      ? 'Combining multiple changes requires careful planning. Ensure all providers are coordinated and the child has adequate support during the transition.'
      : ''
  )

  const handleSave = (slot: 'A' | 'B' | 'C') => {
    onSave(slot)
    setSavedSlots(prev => new Set(prev).add(slot))
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          Change interventions
        </button>
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">CH-A0427</span>
          <Button variant="secondary" size="sm" onClick={onConsultSupervisor}>
            Consult supervisor
          </Button>
        </div>
      </div>

      <GlassCard>
        <div className="flex flex-wrap gap-2">
          {interventions.map((iv) => {
            const colorMap: Record<string, string> = {
              school: 'border-l-orange-500',
              placement: 'border-l-purple-500',
              therapy: 'border-l-emerald-500',
              visits: 'border-l-blue-500',
              mentor: 'border-l-yellow-500',
              caseworker: 'border-l-gray-400',
              sibling: 'border-l-pink-400',
              medication: 'border-l-red-500',
            }
            return (
              <div
                key={iv.domain}
                className={cn(
                  'px-3 py-1.5 rounded-lg text-xs font-medium bg-glass border border-border-light border-l-4',
                  colorMap[iv.domain] || 'border-l-primary',
                )}
              >
                {iv.label}: {iv.value || 'selected'}
              </div>
            )
          })}
        </div>
      </GlassCard>

      <div className="flex gap-4 flex-col lg:flex-row">
        <TrajectoryChart
          data={baseline}
          label="Current trajectory"
          isCounterfactual={false}
          nHistorical={nHistorical}
        />
        <TrajectoryChart
          data={counterfactual}
          label="With your changes"
          isCounterfactual={true}
          nHistorical={nHistorical}
        />
      </div>

      <GlassCard>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground">What this means</h3>
          <button
            onClick={() => setShowTechSidebar(!showTechSidebar)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary transition-colors cursor-pointer"
          >
            <Info className="w-3 h-3" />
            Why does it say that?
          </button>
        </div>

        <VerdictBadge probabilityOfBenefit={effect.probability_of_benefit} />

        <div className="mt-4 space-y-2">
          <p className="text-sm text-muted-foreground">
            Out of 1,000 simulated scenarios:
          </p>
          <ul className="space-y-1 text-sm">
            <li className="flex items-center gap-2">
              <CheckCircle className="w-3.5 h-3.5 text-success" />
              <span>{nImproved} showed improvement with these changes</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="w-3.5 h-3.5 flex items-center justify-center text-muted-foreground">—</span>
              <span>{1000 - nImproved} showed no meaningful difference</span>
            </li>
          </ul>
        </div>

        {effect.decomposition?.components && (
          <div className="mt-4">
            <p className="text-sm font-medium text-foreground mb-2">What helped most:</p>
            <ol className="space-y-1.5">
              {[...effect.decomposition.components]
                .sort((a, b) => Math.abs(b.alone) - Math.abs(a.alone))
                .map((c, i) => (
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

      <GlassCard>
        <div className="flex items-center justify-center gap-3 flex-wrap">
          {(['A', 'B', 'C'] as const).map((slot) => (
            <Button
              key={slot}
              variant={savedSlots.has(slot) ? 'success' : 'secondary'}
              size="sm"
              onClick={() => handleSave(slot)}
            >
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

      {/* Technical sidebar */}
      {showTechSidebar && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="fixed inset-0 z-50 flex justify-end"
        >
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowTechSidebar(false)} />
          <motion.div
            initial={{ x: 320 }}
            animate={{ x: 0 }}
            className="relative w-80 bg-background/95 backdrop-blur-xl border-l border-border-light h-full overflow-y-auto p-6"
          >
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-sm font-semibold text-foreground">How this works</h3>
              <button
                onClick={() => setShowTechSidebar(false)}
                className="text-muted-foreground hover:text-foreground cursor-pointer"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-sm text-muted-foreground">
              <p>
                This simulation compared this child to <strong>{nHistorical} children</strong> who had similar profiles and circumstances.
              </p>

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

              <Button variant="secondary" size="sm" className="w-full" onClick={() => setShowTechSidebar(false)}>
                Close
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </div>
  )
}
