import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Star, Edit, Trash2, FileText, Mail, ArrowLeft, Clock, ExternalLink,
} from 'lucide-react'
import { GlassCard } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface Scenario {
  slot: 'A' | 'B' | 'C'
  label: string
  simulation_id: string
  interventions: { domain: string; action: string; value: string; label?: string }[]
  outcome_summary: string
  verdict: 'positive' | 'uncertain' | 'negative' | ''
  caseworker_note: string
  saved_at: string
  expires_at: string
}

interface ScenarioManagerProps {
  childId: string
  scenarios: (Scenario | null)[]  // length 3, one per slot
  onSaveNote: (slot: 'A' | 'B' | 'C', note: string) => void
  onDelete: (slot: 'A' | 'B' | 'C') => void
  onBack: () => void
  onNewSimulation: () => void
  onGeneratePdf: () => void
  onGeneratePdfAndEmail: () => void
  onReopenScenario: (slot: 'A' | 'B' | 'C') => void
}

function ScenarioCard({
  scenario,
  slot,
  onSaveNote,
  onDelete,
  onReopen,
}: {
  scenario: Scenario | null
  slot: 'A' | 'B' | 'C'
  onSaveNote: (slot: 'A' | 'B' | 'C', note: string) => void
  onDelete: (slot: 'A' | 'B' | 'C') => void
  onReopen: (slot: 'A' | 'B' | 'C') => void
}) {
  const [note, setNote] = useState(scenario?.caseworker_note || '')
  const [saving, setSaving] = useState(false)

  if (!scenario) {
    return (
      <GlassCard className="border-dashed flex flex-col items-center justify-center py-10 min-h-[220px]">
        <Star className="w-8 h-8 text-muted-foreground/40 mb-2" />
        <p className="text-sm font-medium text-muted-foreground">+ New Scenario</p>
        <p className="text-xs text-muted-foreground/60 mt-1">Run a simulation and save it here.</p>
      </GlassCard>
    )
  }

  const handleSaveNote = async () => {
    setSaving(true)
    onSaveNote(slot, note)
    await new Promise(r => setTimeout(r, 300))
    setSaving(false)
  }

  const verdictConfig = {
    positive: { bg: 'bg-success/10 border-success/30 text-success', label: 'Likely to help' },
    uncertain: { bg: 'bg-warning/10 border-warning/30 text-warning', label: 'Uncertain' },
    negative: { bg: 'bg-destructive/10 border-destructive/30 text-destructive', label: 'Unlikely to help' },
  }

  const vc = scenario.verdict ? verdictConfig[scenario.verdict] : null

  return (
    <GlassCard className="relative">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Star className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">
            Scenario {slot} — "{scenario.label}"
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => onReopen(slot)} className="text-muted-foreground hover:text-primary transition-colors cursor-pointer p-1" title="Reopen results">
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => onDelete(slot)} className="text-muted-foreground hover:text-destructive transition-colors cursor-pointer p-1" aria-label="Delete scenario">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="space-y-2 mb-4">
        {scenario.interventions.map((iv) => {
          const borderColor: Record<string, string> = {
            school: 'border-l-orange-500', placement: 'border-l-purple-500', therapy: 'border-l-emerald-500',
            visits: 'border-l-blue-500', mentor: 'border-l-yellow-500', caseworker: 'border-l-gray-400',
            sibling: 'border-l-pink-400', medication: 'border-l-red-500',
          }
          const displayLabel = iv.label || iv.domain.charAt(0).toUpperCase() + iv.domain.slice(1)
          return (
            <div key={iv.domain} className={cn('text-xs px-2.5 py-1.5 rounded bg-glass border border-border-light border-l-4', borderColor[iv.domain] || 'border-l-primary')}>
              {displayLabel}: {iv.value || 'selected'}
            </div>
          )
        })}
      </div>

      <p className="text-sm text-foreground mb-2">{scenario.outcome_summary}</p>

      {vc && (
        <span className={cn('inline-block text-xs font-medium px-2.5 py-1 rounded-full border', vc.bg)}>
          {vc.label}
        </span>
      )}

      <div className="flex items-center gap-1.5 mt-3 text-[10px] text-muted-foreground">
        <Clock className="w-3 h-3" />
        <span>Saved: {new Date(scenario.saved_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
      </div>

      <div className="mt-4 space-y-2">
        <textarea
          className="w-full h-20 px-3 py-2 rounded-lg text-xs bg-glass-hover text-foreground border border-border-light outline-none focus:border-primary/40 resize-none"
          placeholder="Why are you considering this scenario? (max 500 chars)"
          maxLength={500}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button variant="secondary" size="sm" className="w-full" onClick={handleSaveNote} loading={saving} disabled={note === scenario.caseworker_note}>
          Save note
        </Button>
      </div>
    </GlassCard>
  )
}

export function ScenarioManager({
  childId,
  scenarios,
  onSaveNote,
  onDelete,
  onBack,
  onNewSimulation,
  onGeneratePdf,
  onGeneratePdfAndEmail,
  onReopenScenario,
}: ScenarioManagerProps) {
  const filledCount = scenarios.filter(Boolean).length

  const handleConsultSupervisor = () => {
    window.open(`mailto:supervisor@artifex.local?subject=Case Conference Prep — ${childId}&body=I have prepared simulation scenarios and am requesting a case conference.`, '_blank')
  }

  const slots: ('A' | 'B' | 'C')[] = ['A', 'B', 'C']

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
          <ArrowLeft className="w-4 h-4" />
          Back to simulation
        </button>
        <Button variant="secondary" size="sm" onClick={handleConsultSupervisor}>
          Consult supervisor
        </Button>
      </div>

      <div>
        <h2 className="text-lg font-semibold text-foreground mb-1">Saved scenarios for {childId}</h2>
        <p className="text-sm text-muted-foreground">{filledCount} of 3 scenarios saved. Scenarios expire after 7 days.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {slots.map((slot) => {
          const sc = scenarios[slots.indexOf(slot)] || null
          return (
            <ScenarioCard key={slot} scenario={sc as Scenario | null} slot={slot} onSaveNote={onSaveNote} onDelete={onDelete} onReopen={onReopenScenario} />
          )
        })}
      </div>

      <AnimatePresence>
        {filledCount > 0 && (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="space-y-4">
            <GlassCard>
              <h3 className="text-sm font-semibold text-foreground mb-2">Prepare for case conference</h3>
              <p className="text-sm text-muted-foreground mb-4">
                Generate a PDF summary of all saved scenarios to share with your supervisor and the case conference team.
              </p>
              <div className="text-xs text-muted-foreground mb-4 space-y-1">
                <p>The PDF will include:</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li>Child overview (name, age, weeks in placement)</li>
                  <li>Each saved scenario with its outcomes</li>
                  <li>Side-by-side trajectory charts</li>
                  <li>Your caseworker notes</li>
                  <li>Data source disclosure: "Based on historical placements"</li>
                </ul>
              </div>
              <div className="flex gap-3">
                <Button onClick={onGeneratePdf}><FileText className="w-4 h-4" />Generate PDF</Button>
                <Button variant="secondary" onClick={onGeneratePdfAndEmail}><Mail className="w-4 h-4" />Generate PDF + Email</Button>
              </div>
            </GlassCard>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="text-center">
        <button onClick={onNewSimulation} className="text-sm text-primary hover:underline cursor-pointer">
          ← Run a new simulation
        </button>
      </div>

      <p className="text-xs text-muted-foreground/60 text-center">
        This tool helps you explore possible outcomes. It does not make decisions.
        Always discuss intervention plans with your supervisor before acting.
      </p>
    </div>
  )
}
