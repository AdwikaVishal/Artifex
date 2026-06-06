import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  Shield, Search, Download, CheckCircle, AlertTriangle,
  Clock, FileText, Filter,
} from 'lucide-react'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { DataLoader } from '@/components/data-loader'
import { API_BASE_URL } from '@/lib/config'

interface VerifyResult {
  valid: boolean
  checked: number
  broken_links: { id: number; issues: string[] }[]
  oldest_row: string
  newest_row: string
  message: string
}

interface Decision {
  id: number
  child_id: string
  placement_id: string
  decision_type: string
  model_name: string
  model_version: string
  child_demographics: Record<string, unknown>
  output_score: number
  output_label: string
  output_confidence: number
  human_overridden: boolean
  human_decision: string
  decided_at: string
  hash: string
}

const API = `${API_BASE_URL}/api/ml-audit`

async function apiFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, API_BASE_URL)
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export default function MlAuditPage() {
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [verifyError, setVerifyError] = useState<Error | null>(null)

  const [decisions, setDecisions] = useState<Decision[]>([])
  const [decisionsLoading, setDecisionsLoading] = useState(false)
  const [decisionsError, setDecisionsError] = useState<Error | null>(null)
  const [totalDecisions, setTotalDecisions] = useState(0)

  const [filterType, setFilterType] = useState('')
  const [filterChild, setFilterChild] = useState('')
  const [filterDemoKey, setFilterDemoKey] = useState('')
  const [filterDemoVal, setFilterDemoVal] = useState('')

  const runVerify = async () => {
    setVerifyLoading(true)
    setVerifyError(null)
    try {
      const result = await apiFetch<VerifyResult>(`${API}/verify`)
      setVerifyResult(result)
    } catch (e) {
      setVerifyError(e instanceof Error ? e : new Error('Unable to verify chain'))
    } finally {
      setVerifyLoading(false)
    }
  }

  const searchDecisions = async (page = 0) => {
    setDecisionsLoading(true)
    setDecisionsError(null)
    try {
      const params: Record<string, string> = { limit: '50', offset: String(page * 50) }
      if (filterType) params.decision_type = filterType
      if (filterChild) params.child_id = filterChild
      if (filterDemoKey && filterDemoVal) {
        params.demographic_key = filterDemoKey
        params.demographic_val = filterDemoVal
      }
      const result = await apiFetch<{ decisions: Decision[]; total: number }>(`${API}/decisions`, params)
      setDecisions(result.decisions)
      setTotalDecisions(result.total)
    } catch (e) {
      setDecisionsError(e instanceof Error ? e : new Error('Unable to load decisions'))
    } finally {
      setDecisionsLoading(false)
    }
  }

  useEffect(() => {
    runVerify()
    searchDecisions()
  }, [])

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-foreground">ML Decision Audit Trail</h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Tamper-evident audit log of every AI recommendation
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={runVerify} disabled={verifyLoading}>
            <CheckCircle className="w-4 h-4 mr-2" />
            {verifyLoading ? 'Verifying...' : 'Verify Chain'}
          </Button>
          <Button variant="outline" onClick={() => window.open(`${API}/export?format=csv`)}>
            <Download className="w-4 h-4 mr-2" />
            Export CSV
          </Button>
        </div>
      </div>

      {/* Integrity status card */}
      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>Hash Chain Integrity</GlassCardTitle>
          <Clock className="w-4 h-4 text-muted-foreground" />
        </GlassCardHeader>
        <DataLoader isLoading={verifyLoading} error={verifyError} type="card" rows={2}>
          {verifyResult && (
            <div className="px-4 pb-4 space-y-3">
              <div className="flex items-center gap-3">
                {verifyResult.valid ? (
                  <CheckCircle className="w-6 h-6 text-success" />
                ) : (
                  <AlertTriangle className="w-6 h-6 text-destructive" />
                )}
                <div>
                  <p className="text-sm font-medium">
                    {verifyResult.valid ? 'Hash chain intact' : 'Integrity breach detected'}
                  </p>
                  <p className="text-xs text-muted-foreground">{verifyResult.message}</p>
                </div>
              </div>
              <div className="flex gap-6 text-xs text-muted-foreground">
                <span>{verifyResult.checked.toLocaleString()} decisions checked</span>
                {verifyResult.oldest_row && <span>From: {verifyResult.oldest_row}</span>}
                {verifyResult.newest_row && <span>To: {verifyResult.newest_row}</span>}
              </div>
            </div>
          )}
        </DataLoader>
      </GlassCard>

      {/* Filters */}
      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>Filter Decisions</GlassCardTitle>
          <Filter className="w-4 h-4 text-muted-foreground" />
        </GlassCardHeader>
        <div className="px-4 pb-4">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Decision type</label>
              <select
                className="h-9 rounded-md border border-input bg-background px-3 text-sm"
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
              >
                <option value="">All types</option>
                <option value="crisis_prediction">Crisis Prediction</option>
                <option value="risk_score">Risk Score</option>
                <option value="placement_match">Placement Match</option>
                <option value="human_override">Human Override</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Child ID</label>
              <Input
                placeholder="e.g. CH-A0427"
                value={filterChild}
                onChange={(e) => setFilterChild(e.target.value)}
                className="h-9 w-40"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Demo key</label>
              <Input
                placeholder="e.g. race"
                value={filterDemoKey}
                onChange={(e) => setFilterDemoKey(e.target.value)}
                className="h-9 w-28"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs text-muted-foreground">Demo value</label>
              <Input
                placeholder="e.g. Black"
                value={filterDemoVal}
                onChange={(e) => setFilterDemoVal(e.target.value)}
                className="h-9 w-36"
              />
            </div>
            <Button onClick={() => searchDecisions()} disabled={decisionsLoading}>
              <Search className="w-4 h-4 mr-2" />
              Search
            </Button>
          </div>
        </div>
      </GlassCard>

      {/* Decisions table */}
      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>
            Decisions
            <span className="text-xs text-muted-foreground ml-2">
              {totalDecisions.toLocaleString()} total
            </span>
          </GlassCardTitle>
          <FileText className="w-4 h-4 text-muted-foreground" />
        </GlassCardHeader>
        <DataLoader isLoading={decisionsLoading} error={decisionsError} type="card" rows={5}>
          {decisions.length === 0 ? (
            <div className="px-4 pb-4 text-sm text-muted-foreground">No decisions match the current filters.</div>
          ) : (
            <div className="px-4 pb-4 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">ID</th>
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Child</th>
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Type</th>
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Score</th>
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Model</th>
                    <th className="text-left py-2 pr-3 font-medium text-muted-foreground">Overridden</th>
                    <th className="text-left py-2 font-medium text-muted-foreground">Decided</th>
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((d) => (
                    <tr key={d.id} className="border-b border-border/50 hover:bg-accent/30">
                      <td className="py-2 pr-3 font-mono text-muted-foreground">{d.id}</td>
                      <td className="py-2 pr-3 font-mono">{d.child_id}</td>
                      <td className="py-2 pr-3">
                        <span className={cn(
                          'px-1.5 py-0.5 rounded text-[10px] font-medium',
                          d.decision_type === 'crisis_prediction' && 'bg-red-500/15 text-red-400',
                          d.decision_type === 'risk_score' && 'bg-amber-500/15 text-amber-400',
                          d.decision_type === 'placement_match' && 'bg-blue-500/15 text-blue-400',
                          d.decision_type === 'human_override' && 'bg-purple-500/15 text-purple-400',
                        )}>
                          {d.decision_type.replace('_', ' ')}
                        </span>
                      </td>
                      <td className="py-2 pr-3 font-mono">
                        {d.output_score?.toFixed(1) ?? '—'}
                      </td>
                      <td className="py-2 pr-3 text-muted-foreground">{d.model_version}</td>
                      <td className="py-2 pr-3">
                        {d.human_overridden ? (
                          <span className="text-purple-400">{d.human_decision || 'Yes'}</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2 font-mono text-muted-foreground">
                        {d.decided_at?.slice(0, 10)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataLoader>
      </GlassCard>
    </motion.div>
  )
}

function cn(...classes: (string | false | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ')
}
