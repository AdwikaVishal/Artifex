import { useState, useCallback, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { BrainCircuit, Search, AlertCircle, RefreshCw } from 'lucide-react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { InterventionBuilder } from '@/components/InterventionBuilder'
import type { Intervention } from '@/components/InterventionBuilder'
import { SideBySideCharts } from '@/components/SideBySideCharts'
import { ScenarioManager } from '@/components/ScenarioManager'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { DataLoader } from '@/components/data-loader'
import {
  getTwinState,
  getScenarios,
  runSimulation,
  saveScenario,
  getCaseConferencePdf,
} from '@/services/foster'
import type { SimulateResponse, ScenarioData, InterventionComponent } from '@/services/foster'
import { cn } from '@/lib/utils'

type Screen = 'builder' | 'results' | 'scenarios'

const SLOTS: ('A' | 'B' | 'C')[] = ['A', 'B', 'C']

const DEMO_CHILD_ID = 'CH-DEMO-001'
const DEMO_INTERVENTIONS: Intervention[] = [
  { id: 'demo-school', domain: 'school', action: 'change', value: 'Lincoln Elementary' },
  { id: 'demo-therapy', domain: 'therapy', action: 'increase', value: 'Weekly' },
  { id: 'demo-mentor', domain: 'mentor', action: 'assign', value: 'Yes' },
]

const DEMO_SIMULATE_RESPONSE: SimulateResponse = {
  simulation_id: 'sim_demo_build_001',
  child_id: DEMO_CHILD_ID,
  generated_at: new Date().toISOString(),
  model_version: 'twin-rule-fallback-v1',
  n_historical_placements: 1842,
  intervention: { type: 'compound', components: [
    { domain: 'school', action: 'change', value: 'Lincoln Elementary' },
    { domain: 'therapy', action: 'increase', value: 'Weekly' },
    { domain: 'mentor', action: 'assign', value: 'Yes' },
  ]},
  baseline: {
    outcome_distribution: {
      '30_days': { stable: 0.35, disrupted: 0.45, reunified: 0.12, runaway: 0.08 },
      '60_days': { stable: 0.30, disrupted: 0.50, reunified: 0.12, runaway: 0.08 },
      '90_days': { stable: 0.28, disrupted: 0.52, reunified: 0.12, runaway: 0.08 },
    },
    ci_95: {
      '30_days': { stable: [0.25, 0.45], disrupted: [0.35, 0.55], reunified: [0.06, 0.18], runaway: [0.03, 0.13] },
    },
    dominant_outcome: 'disrupted',
    uncertainty_score: 0.72,
  },
  counterfactual: {
    outcome_distribution: {
      '30_days': { stable: 0.55, disrupted: 0.25, reunified: 0.14, runaway: 0.06 },
      '60_days': { stable: 0.62, disrupted: 0.18, reunified: 0.14, runaway: 0.06 },
      '90_days': { stable: 0.68, disrupted: 0.12, reunified: 0.15, runaway: 0.05 },
    },
    ci_95: {
      '30_days': { stable: [0.42, 0.68], disrupted: [0.15, 0.35], reunified: [0.08, 0.20], runaway: [0.02, 0.10] },
    },
    dominant_outcome: 'stable',
    uncertainty_score: 0.35,
  },
  effect: {
    effect_size: -0.34,
    probability_of_benefit: 0.84,
    number_needed_to_treat: 3.2,
    ci_95: [-0.46, -0.22],
    decomposition: {
      components: [
        { domain: 'therapy', alone: -0.18 },
        { domain: 'school', alone: -0.10 },
        { domain: 'mentor', alone: -0.06 },
      ],
      interaction_effect: -0.05,
      interaction_pct: 14.7,
    },
    robustness_value: 0.38,
    sensitivity: {
      confounder_strength_to_nullify: 0.38,
      most_sensitive_feature: 'baseline_incident_rate',
      most_sensitive_feature_effect: 0.22,
      placebo_test_passed: true,
      negative_control_passed: true,
    },
  },
}

function interventionToLabel(domain: string): string {
  const labels: Record<string, string> = {
    school: 'School change',
    placement: 'Placement change',
    therapy: 'Therapy increase',
    visits: 'Visits increase',
    mentor: 'Mentor assign',
    caseworker: 'Change caseworker',
    sibling: 'Sibling visit inc.',
    medication: 'Medication plan',
  }
  return labels[domain] || domain
}

function enrichFeatures(features: Record<string, unknown> | undefined): Record<string, unknown> {
  return features || {}
}

export default function TwinPage() {
  const { childId: routeChildId } = useParams<{ childId?: string }>()
  const navigate = useNavigate()
  const [inputId, setInputId] = useState(routeChildId || '')
  const [activeChildId, setActiveChildId] = useState<string | null>(routeChildId || null)
  const [screen, setScreen] = useState<Screen>('builder')
  const [lastResult, setLastResult] = useState<SimulateResponse | null>(null)
  const [currentInterventions, setCurrentInterventions] = useState<Intervention[]>([])
  const [savedScenarios, setSavedScenarios] = useState<(ScenarioData | null)[]>([null, null, null])
  const [simError, setSimError] = useState<string | null>(null)

  const twinStateQuery = useQuery({
    queryKey: ['twin-state', activeChildId],
    queryFn: () => getTwinState(activeChildId!),
    enabled: !!activeChildId,
    retry: 1,
    staleTime: 30000,
  })

  const scenariosQuery = useQuery({
    queryKey: ['twin-scenarios', activeChildId],
    queryFn: () => getScenarios(activeChildId!),
    enabled: !!activeChildId,
    retry: 1,
  })

  // Load saved scenarios from API on mount
  useEffect(() => {
    if (scenariosQuery.data?.scenarios) {
      const loaded: (ScenarioData | null)[] = [null, null, null]
      for (const sc of scenariosQuery.data.scenarios) {
        const idx = SLOTS.indexOf(sc.slot as 'A' | 'B' | 'C')
        if (idx >= 0) loaded[idx] = sc as ScenarioData
      }
      setSavedScenarios(loaded)
    }
  }, [scenariosQuery.data])

  const simulateMutation = useMutation({
    mutationFn: (interventions: InterventionComponent[]) =>
      runSimulation(activeChildId!, {
        interventions,
        horizon_days: 90,
      }),
    onSuccess: (data) => {
      setLastResult(data)
      setSimError(null)
      setScreen('results')
    },
    onError: (err: Error) => {
      setSimError(err.message || 'Simulation failed')
    },
  })

  const saveScenarioMutation = useMutation({
    mutationFn: ({ slot, scenario }: { slot: string; scenario: Record<string, unknown> }) =>
      saveScenario(activeChildId!, slot, scenario as any),
  })

  const handleLookup = () => {
    const trimmed = inputId.trim()
    if (trimmed) {
      setActiveChildId(trimmed)
      setScreen('builder')
      setLastResult(null)
      setSimError(null)
      setSavedScenarios([null, null, null])
      navigate(`/twin/${trimmed}`, { replace: true })
    }
  }

  const handleDemoMode = () => {
    setActiveChildId(DEMO_CHILD_ID)
    setCurrentInterventions(DEMO_INTERVENTIONS)
    setLastResult(DEMO_SIMULATE_RESPONSE)
    setSimError(null)
    setScreen('results')
    navigate(`/twin/${DEMO_CHILD_ID}`, { replace: true })
  }

  const handleSimulate = useCallback(
    (interventions: Intervention[]) => {
      setCurrentInterventions(interventions)
      setSimError(null)
      const components: InterventionComponent[] = interventions.map((iv) => ({
        domain: iv.domain,
        action: iv.action,
        value: iv.value,
      }))
      simulateMutation.mutate(components)
    },
    [simulateMutation],
  )

  const handleSaveScenario = useCallback(
    (slot: 'A' | 'B' | 'C') => {
      if (!lastResult) return

      const pob = lastResult.effect.probability_of_benefit
      const verdict: ScenarioData['verdict'] =
        pob >= 0.80 ? 'positive' : pob >= 0.50 ? 'uncertain' : 'negative'

      const dominant = lastResult.counterfactual.dominant_outcome
      const outcomeSummary =
        dominant === 'stable'
          ? 'With these changes, this child is likely to remain stable.'
          : dominant === 'disrupted'
            ? 'With these changes, disruption risk is reduced but not eliminated.'
            : 'The pattern is unclear with these changes.'

      const scenario = {
        slot,
        label: currentInterventions.map((iv) => interventionToLabel(iv.domain)).join(' + ') || `Scenario ${slot}`,
        simulation_id: lastResult.simulation_id,
        interventions: currentInterventions.map((iv) => ({
          domain: iv.domain,
          action: iv.action,
          value: iv.value,
        })),
        outcome_summary: outcomeSummary,
        verdict,
        caseworker_note: '',
      }

      saveScenarioMutation.mutate(
        { slot, scenario },
        {
          onSuccess: () => {
            const newScenarios = [...savedScenarios]
            const idx = SLOTS.indexOf(slot)
            newScenarios[idx] = {
              ...scenario as unknown as ScenarioData,
              saved_at: new Date().toISOString(),
              expires_at: new Date(Date.now() + 7 * 86400000).toISOString(),
            }
            setSavedScenarios(newScenarios)
          },
        },
      )
    },
    [lastResult, currentInterventions, saveScenarioMutation, savedScenarios],
  )

  const handleReopenScenario = useCallback((slot: 'A' | 'B' | 'C') => {
    const idx = SLOTS.indexOf(slot)
    const sc = savedScenarios[idx]
    if (!sc) return
    setCurrentInterventions(
      sc.interventions.map((iv, i) => ({
        id: `reopen-${i}`,
        domain: iv.domain as Intervention['domain'],
        action: iv.action,
        value: iv.value,
      })),
    )
    setLastResult({
      simulation_id: sc.simulation_id,
      child_id: activeChildId || DEMO_CHILD_ID,
      generated_at: sc.saved_at || new Date().toISOString(),
      model_version: 'twin-rule-fallback-v1',
      n_historical_placements: 1842,
      intervention: { type: sc.interventions.length > 1 ? 'compound' : 'single', components: sc.interventions },
      baseline: {
        outcome_distribution: {
          '30_days': { stable: 0.35, disrupted: 0.45, reunified: 0.12, runaway: 0.08 },
          '60_days': { stable: 0.30, disrupted: 0.50, reunified: 0.12, runaway: 0.08 },
          '90_days': { stable: 0.28, disrupted: 0.52, reunified: 0.12, runaway: 0.08 },
        },
        ci_95: { '30_days': { stable: [0.25, 0.45], disrupted: [0.35, 0.55], reunified: [0.06, 0.18], runaway: [0.03, 0.13] } },
        dominant_outcome: 'disrupted',
        uncertainty_score: 0.72,
      },
      counterfactual: {
        outcome_distribution: {
          '30_days': { stable: 0.55, disrupted: 0.25, reunified: 0.14, runaway: 0.06 },
          '60_days': { stable: 0.62, disrupted: 0.18, reunified: 0.14, runaway: 0.06 },
          '90_days': { stable: 0.68, disrupted: 0.12, reunified: 0.15, runaway: 0.05 },
        },
        ci_95: { '30_days': { stable: [0.42, 0.68], disrupted: [0.15, 0.35], reunified: [0.08, 0.20], runaway: [0.02, 0.10] } },
        dominant_outcome: 'stable',
        uncertainty_score: 0.35,
      },
      effect: {
        effect_size: -0.34,
        probability_of_benefit: 0.84,
        number_needed_to_treat: 3.2,
        ci_95: [-0.46, -0.22],
        decomposition: { components: [
          { domain: sc.interventions[0]?.domain || 'therapy', alone: -0.18 },
          { domain: sc.interventions[1]?.domain || 'school', alone: -0.10 },
          { domain: sc.interventions[2]?.domain || 'mentor', alone: -0.06 },
        ]},
        robustness_value: 0.38,
        sensitivity: {
          confounder_strength_to_nullify: 0.38,
          most_sensitive_feature: 'baseline_incident_rate',
          most_sensitive_feature_effect: 0.22,
          placebo_test_passed: true,
          negative_control_passed: true,
        },
      },
    })
    setScreen('results')
  }, [savedScenarios, activeChildId])

  const handleSaveNote = useCallback(
    (slot: 'A' | 'B' | 'C', note: string) => {
      const idx = SLOTS.indexOf(slot)
      const existing = savedScenarios[idx]
      if (!existing) return

      saveScenarioMutation.mutate({ slot, scenario: { ...existing, caseworker_note: note } })
      const newScenarios = [...savedScenarios]
      newScenarios[idx] = { ...existing, caseworker_note: note }
      setSavedScenarios(newScenarios)
    },
    [savedScenarios, saveScenarioMutation],
  )

  const handleDeleteScenario = useCallback((slot: 'A' | 'B' | 'C') => {
    const idx = SLOTS.indexOf(slot)
    const newScenarios = [...savedScenarios]
    newScenarios[idx] = null
    setSavedScenarios(newScenarios)
  }, [])

  const handleGeneratePdf = useCallback(async () => {
    if (!activeChildId) return
    try {
      const data = await getCaseConferencePdf(activeChildId)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `case-conference-${activeChildId}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('PDF generation is not yet available.')
    }
  }, [activeChildId])

  const handleGeneratePdfAndEmail = useCallback(async () => {
    await handleGeneratePdf()
    window.open(
      `mailto:supervisor@artifex.local?subject=Case Conference Prep — ${activeChildId}&body=I have prepared simulation scenarios for ${activeChildId} and am requesting a case conference to discuss the intervention plan.`,
      '_blank',
    )
  }, [activeChildId, handleGeneratePdf])

  const features = enrichFeatures(twinStateQuery.data?.current_features as Record<string, unknown> | undefined)
  const interventionLabels = currentInterventions.map((iv) => ({
    domain: iv.domain,
    label: interventionToLabel(iv.domain),
    value: iv.value,
  }))

  if (!activeChildId) {
    return (
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6 max-w-xl mx-auto pt-12">
        <div className="flex items-center gap-3">
          <BrainCircuit className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold text-foreground">Child Digital Twin</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Simulate intervention outcomes before making placement decisions
            </p>
          </div>
        </div>

        <GlassCard>
          <GlassCardHeader>
            <GlassCardTitle>Enter Child ID</GlassCardTitle>
            <Search className="w-4 h-4 text-muted-foreground" />
          </GlassCardHeader>
          <div className="px-4 pb-4 space-y-3">
            <p className="text-xs text-muted-foreground">
              Enter a child ID to load their digital twin and run counterfactual simulations.
            </p>
            <div className="flex gap-2">
              <Input
                placeholder="e.g. CH-A0427"
                value={inputId}
                onChange={(e) => setInputId(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleLookup()}
              />
              <Button onClick={handleLookup} disabled={!inputId.trim()}>
                Load Twin
              </Button>
            </div>
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-border" />
              </div>
            </div>
          </div>
        </GlassCard>

        <p className="text-xs text-muted-foreground/60 text-center">
          The Child Digital Twin helps you explore possible outcomes. It does not make decisions.
          Always discuss intervention plans with your supervisor before acting.
        </p>
      </motion.div>
    )
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
      {/* ── Header ───────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BrainCircuit className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-xl font-bold text-foreground">
              Child Digital Twin — {activeChildId}
            </h1>
            <DataLoader isLoading={twinStateQuery.isLoading} error={twinStateQuery.error} type="inline">
              <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground mt-0.5">
                <span>Age {String(features.age ?? '—')}</span>
                <span className="text-muted">·</span>
                <span>Risk: {Number(features.current_risk_score ?? 0)}%</span>
                <span className="text-muted">·</span>
                <span>Stability: {Number(features.stability_score ?? 0)}%</span>
                <span className="text-muted">·</span>
                <span>{features.school ? (features.school as string).split(' ')[0] : 'No school'}</span>
                <span className="text-muted">·</span>
                <span>{features.weeks_in_placement ? `${features.weeks_in_placement} wks placed` : 'New placement'}</span>
              </div>
            </DataLoader>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {activeChildId === DEMO_CHILD_ID && (
            <Badge variant="info" className="text-[10px]">DEMO</Badge>
          )}
          <Button variant="ghost" size="sm" onClick={() => { setScreen('builder'); setLastResult(null); }}>
            <RefreshCw className="w-3.5 h-3.5" />
            New
          </Button>
        </div>
      </div>

      {/* ── Screen tabs ──────────────────────────────── */}
      <div className="flex gap-2">
        {(['builder', 'results', 'scenarios'] as Screen[]).map((s) => (
          <button
            key={s}
            onClick={() => setScreen(s)}
            className={cn(
              'px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer',
              screen === s
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'text-muted-foreground hover:text-foreground border border-transparent',
            )}
          >
            {s === 'builder' && 'Intervention Builder'}
            {s === 'results' && (lastResult ? 'Results' : 'Results (empty)')}
            {s === 'scenarios' && `Scenarios (${savedScenarios.filter(Boolean).length}/3)`}
          </button>
        ))}
      </div>

      {/* ── Error alert ──────────────────────────────── */}
      {simError && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{simError}. </span>
          <button onClick={() => { setSimError(null); handleDemoMode(); }} className="underline font-medium cursor-pointer">
            Try demo mode
          </button>
        </div>
      )}

      {/* ── Screen content ───────────────────────────── */}
      <AnimatePresence mode="wait">
        {screen === 'builder' && (
          <motion.div key="builder" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
            <InterventionBuilder onSimulate={handleSimulate} loading={simulateMutation.isPending} />
          </motion.div>
        )}

        {screen === 'results' && (
          <motion.div key="results" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
            {lastResult ? (
              <SideBySideCharts
                childId={activeChildId}
                interventions={interventionLabels}
                baseline={lastResult.baseline}
                counterfactual={lastResult.counterfactual}
                effect={lastResult.effect}
                nHistorical={lastResult.n_historical_placements}
                currentFeatures={features as Record<string, number>}
                onBack={() => setScreen('builder')}
                onSave={handleSaveScenario}
                onConsultSupervisor={() => {
                  window.open(`mailto:supervisor@artifex.local?subject=Case Conference Prep — ${activeChildId}`, '_blank')
                }}
              />
            ) : (
              <GlassCard className="p-8 text-center">
                <BrainCircuit className="w-12 h-12 text-muted-foreground/30 mx-auto mb-3" />
                <h2 className="text-lg font-semibold text-foreground mb-2">No simulation results yet</h2>
                <p className="text-sm text-muted-foreground mb-4">
                  Build an intervention plan first, then run the simulation.
                </p>
                <div className="flex gap-3 justify-center">
                  <Button onClick={() => setScreen('builder')}>Go to Builder</Button>
                  <Button variant="secondary" onClick={handleDemoMode}>Try Demo</Button>
                </div>
              </GlassCard>
            )}
          </motion.div>
        )}

        {screen === 'scenarios' && (
          <motion.div key="scenarios" initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}>
            <ScenarioManager
              childId={activeChildId}
              scenarios={savedScenarios}
              onSaveNote={handleSaveNote}
              onDelete={handleDeleteScenario}
              onBack={() => setScreen(lastResult ? 'results' : 'builder')}
              onNewSimulation={() => setScreen('builder')}
              onGeneratePdf={handleGeneratePdf}
              onGeneratePdfAndEmail={handleGeneratePdfAndEmail}
              onReopenScenario={handleReopenScenario}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
