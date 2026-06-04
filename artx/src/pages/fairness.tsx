/**
 * FairnessPage – full-page Fairness & Bias Audit view.
 *
 * Shows the FairnessDashboard component plus a SHAP explanation lookup
 * for any workflow ID.
 */
import { useState } from 'react'
import { motion } from 'framer-motion'
import { Shield, Search } from 'lucide-react'
import FairnessAuditDashboard from '@/components/FairnessAuditDashboard'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { useShapExplanation } from '@/hooks/use-foster'
import { normalizeWorkflowId } from '@/services/foster'
import { DataLoader } from '@/components/data-loader'

function ShapPanel({ workflowId }: { workflowId: string }) {
  const { data, isLoading, error } = useShapExplanation(workflowId)

  return (
    <GlassCard>
      <GlassCardHeader>
        <GlassCardTitle>SHAP Explanation – {workflowId}</GlassCardTitle>
      </GlassCardHeader>
      <div className="px-4 pb-4">
        <DataLoader isLoading={isLoading} error={error} type="card" rows={3}>
          {data && (
            <div className="space-y-4">
              <div className="flex gap-6 text-sm">
                {data.match_score != null && (
                  <div>
                    <p className="text-xs text-gray-400">Match Score</p>
                    <p className="text-lg font-bold text-primary">
                      {data.match_score.toFixed(1)}%
                    </p>
                  </div>
                )}
                {data.confidence_score != null && (
                  <div>
                    <p className="text-xs text-gray-400">Confidence</p>
                    <p className="text-lg font-bold text-secondary">
                      {(data.confidence_score * 100).toFixed(1)}%
                    </p>
                  </div>
                )}
              </div>

              {data.feature_importance.length > 0 && (
                <div>
                  <p className="text-xs text-gray-400 mb-3">Feature Importance</p>
                  <div className="space-y-2">
                    {data.feature_importance.map((fi) => (
                      <div key={fi.feature}>
                        <div className="flex items-center justify-between mb-0.5">
                          <span className="text-xs text-gray-300">{fi.description}</span>
                          <span className="text-xs font-mono text-gray-400">
                            {(fi.importance * 100).toFixed(1)}%
                          </span>
                        </div>
                        <div className="h-1.5 rounded-full bg-gray-700 overflow-hidden">
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{
                              width: `${Math.min(fi.importance * 100, 100)}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DataLoader>
      </div>
    </GlassCard>
  )
}

export default function FairnessPage() {
  const [inputId, setInputId] = useState('')
  const [activeId, setActiveId] = useState<string | null>(null)

  const handleLookup = () => {
    const trimmed = inputId.trim()
    if (trimmed) setActiveId(normalizeWorkflowId(trimmed))
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-6"
    >
      <div className="flex items-center gap-3">
        <Shield className="w-6 h-6 text-blue-400" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">Fairness & Bias Audit</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            AI placement disparity metrics and explainability
          </p>
        </div>
      </div>

      {/* Main fairness audit dashboard — 5 metric families */}
      <FairnessAuditDashboard />

      {/* SHAP explanation lookup */}
      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>Placement Explanation Lookup</GlassCardTitle>
          <Search className="w-4 h-4 text-muted-foreground" />
        </GlassCardHeader>
        <div className="px-4 pb-4">
          <p className="text-xs text-gray-400 mb-3">
            Enter a workflow ID to see why the AI recommended a specific family
            (SHAP-style feature importance).
          </p>
          <div className="flex gap-2">
            <Input
              placeholder="e.g. foster-CHILD001"
              value={inputId}
              onChange={(e) => setInputId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleLookup()}
            />
            <Button onClick={handleLookup} disabled={!inputId.trim()}>
              Explain
            </Button>
          </div>
        </div>
      </GlassCard>

      {activeId && <ShapPanel workflowId={activeId} />}
    </motion.div>
  )
}
