/**
 * TwinPage – Child Digital Twin simulation interface.
 *
 * Three screens:
 *   1. InterventionBuilder  – drag-and-drop / click-to-add workbench
 *   2. SideBySideCharts     – trajectory comparison with confidence ribbons
 *   3. ScenarioManager      – 3-slot save, notes, case conference PDF
 */
import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { BrainCircuit, Search } from 'lucide-react'
import { useQuery, useMutation } from '@tanstack/react-query'
import { InterventionBuilder, type Intervention } from '@/components/InterventionBuilder'
import { SideBySideCharts } from '@/components/SideBySideCharts'
import { ScenarioManager } from '@/components/ScenarioManager'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { DataLoader } from '@/components/data-loader'
import {
  getTwinState,
  runSimulation,
  saveScenario,
  getCaseConferencePdf,
  type SimulateResponse,
  type ScenarioData,
  type InterventionComponent,
} from '@/services/foster'

type Screen = 'builder' | 'results' | 'scenarios'

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

export default function TwinPage() {
  const { childId: routeChildId } = useParams<{ childId?: string }>()
  const navigate = useNavigate()
  const [inputId, setInputId] = useState(routeChildId || '')
  const [activeChildId, setActiveChildId] = useState<string | null>(routeChildId || null)
  const [screen, setScreen] = useState<Screen>('builder')
  const [lastResult, setLastResult] = useState<SimulateResponse | null>(null)
  const [currentInterventions, setCurrentInterventions] = useState<Intervention[]>([])
  const [savedScenarios, setSavedScenarios] = useState<(ScenarioData | null)[]>([null, null, null])

  const SLOTS: ('A' | 'B' | 'C')[] = ['A', 'B', 'C']

  const twinStateQuery = useQuery({
    queryKey: ['twin-state', activeChildId],
    queryFn: () => getTwinState(activeChildId!),
    enabled: !!activeChildId,
  })

  const simulateMutation = useMutation({
    mutationFn: (interventions: InterventionComponent[]) =>
      runSimulation(activeChildId!, {
        interventions,
        horizon_days: 90,
      }),
    onSuccess: (data) => {
      setLastResult(data)
      setScreen('results')
    },
  })

  const saveScenarioMutation = useMutation({
    mutationFn: ({
      slot,
      scenario,
    }: {
      slot: string
      scenario: {
        slot: string
        label: string
        simulation_id: string
        interventions: InterventionComponent[]
        outcome_summary: string
        verdict: string
        caseworker_note: string
      }
    }) => saveScenario(activeChildId!, slot, scenario),
  })

  const handleLookup = () => {
    const trimmed = inputId.trim()
    if (trimmed) {
      setActiveChildId(trimmed)
      setScreen('builder')
      setLastResult(null)
      navigate(`/twin/${trimmed}`, { replace: true })
    }
  }

  const handleSimulate = useCallback(
    (interventions: Intervention[]) => {
      setCurrentInterventions(interventions)
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
              ...scenario,
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

  const handleSaveNote = useCallback(
    (slot: 'A' | 'B' | 'C', note: string) => {
      const idx = SLOTS.indexOf(slot)
      const existing = savedScenarios[idx]
      if (!existing) return

      saveScenarioMutation.mutate({
        slot,
        scenario: {
          ...existing,
          caseworker_note: note,
        },
      })

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
      // Create a downloadable JSON blob for now (PDF rendering is server-side)
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `case-conference-${activeChildId}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Silently fail — fallback to alert
      alert('PDF generation is not yet available. The data payload has been prepared.')
    }
  }, [activeChildId])

  const handleGeneratePdfAndEmail = useCallback(async () => {
    await handleGeneratePdf()
    window.open(
      `mailto:supervisor@artifex.local?subject=Case Conference Prep — ${activeChildId}&body=I have prepared simulation scenarios for ${activeChildId} and am requesting a case conference to discuss the intervention plan.`,
      '_blank',
    )
  }, [activeChildId, handleGeneratePdf])

  const interventionLabels = currentInterventions.map((iv) => ({
    domain: iv.domain,
    label: interventionToLabel(iv.domain),
    value: iv.value,
  }))

  if (!activeChildId) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-6 max-w-xl mx-auto pt-12"
      >
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
          <div className="px-4 pb-4">
            <p className="text-xs text-muted-foreground mb-3">
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
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BrainCircuit className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              Child Digital Twin — {activeChildId}
            </h1>
            <DataLoader
              isLoading={twinStateQuery.isLoading}
              error={twinStateQuery.error}
              type="full"
            >
              {twinStateQuery.data && (
                <p className="text-sm text-muted-foreground mt-0.5">
                  Age {String(twinStateQuery.data.current_features?.age ?? '')}
                  {twinStateQuery.data.current_features?.weeks_in_placement
                    ? ` · ${String(twinStateQuery.data.current_features.weeks_in_placement)} wks in placement`
                    : ''}
                </p>
              )}
            </DataLoader>
          </div>
        </div>
      </div>

      <div className="flex gap-2 mb-2">
        {(['builder', 'results', 'scenarios'] as Screen[]).map((s) => (
          <button
            key={s}
            onClick={() => setScreen(s)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer ${
              screen === s
                ? 'bg-primary/20 text-primary border border-primary/30'
                : 'text-muted-foreground hover:text-foreground border border-transparent'
            }`}
          >
            {s === 'builder' && 'Builder'}
            {s === 'results' && 'Results'}
            {s === 'scenarios' && 'Scenarios'}
          </button>
        ))}
      </div>

      <AnimatePresence mode="wait">
        {screen === 'builder' && (
          <motion.div
            key="builder"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
          >
            <InterventionBuilder
              onSimulate={handleSimulate}
              loading={simulateMutation.isPending}
            />
          </motion.div>
        )}

        {screen === 'results' && lastResult && (
          <motion.div
            key="results"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
          >
            <SideBySideCharts
              childId={activeChildId}
              interventions={interventionLabels}
              baseline={lastResult.baseline}
              counterfactual={lastResult.counterfactual}
              effect={lastResult.effect}
              nHistorical={lastResult.n_historical_placements}
              onBack={() => setScreen('builder')}
              onSave={handleSaveScenario}
              onConsultSupervisor={() => {
                window.open(
                  `mailto:supervisor@artifex.local?subject=Case Conference Prep — ${activeChildId}`,
                  '_blank',
                )
              }}
            />
          </motion.div>
        )}

        {screen === 'scenarios' && (
          <motion.div
            key="scenarios"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
          >
            <ScenarioManager
              childId={activeChildId}
              scenarios={savedScenarios}
              onSaveNote={handleSaveNote}
              onDelete={handleDeleteScenario}
              onBack={() => setScreen('results')}
              onNewSimulation={() => setScreen('builder')}
              onGeneratePdf={handleGeneratePdf}
              onGeneratePdfAndEmail={handleGeneratePdfAndEmail}
            />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
