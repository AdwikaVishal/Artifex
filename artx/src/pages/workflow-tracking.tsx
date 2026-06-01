import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import api from '@/services/api'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge } from '@/components/ui/badge'
import { AnimatedProgressSteps } from '@/components/ui/progress'
import { DataLoader } from '@/components/data-loader'
import { Separator } from '@/components/ui/separator'
import { formatDate, getStageLabel } from '@/lib/utils'
import { normalizeWorkflowId, subscribeWorkflowStream } from '@/services/foster'
import { motion } from 'framer-motion'
import { Search, Clock, AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowStatus, WorkflowStage } from '@/types'
import { useState, useEffect, useCallback, useRef } from 'react'

function formatPercent(value?: number | null, decimals = 0): string {
  if (value == null || Number.isNaN(value)) return '—'
  const normalized = value <= 1 ? value * 100 : value
  return `${Number(normalized.toFixed(decimals))}%`
}

function formatRiskScore(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '—'
  const normalized = value <= 1 ? value * 100 : value
  return `${normalized.toFixed(normalized < 10 ? 2 : 0)}%`
}

function normalizeTimelineEvents(events: WorkflowStage[]): WorkflowStage[] {
  // Deduplicate: for each stage, keep the most meaningful status
  // (completed > in_progress > failed > pending) to avoid duplicate React keys
  const STATUS_RANK: Record<string, number> = {
    completed: 4, in_progress: 3, failed: 2, pending: 1,
  }
  const seen = new Map<string, WorkflowStage>()
  for (const event of events || []) {
    const stageName = event.stage || event.name || ''
    const existing = seen.get(stageName)
    const rank = STATUS_RANK[event.status] ?? 0
    const existingRank = existing ? (STATUS_RANK[existing.status] ?? 0) : -1
    if (!existing || rank > existingRank) {
      seen.set(stageName, event)
    }
  }

  return Array.from(seen.values()).map((event, index) => {
    const stageName = event.stage || event.name || `event-${index}`
    const label = event.label || getStageLabel(event.stage || event.name || '') || String(stageName)
    const details = event.details ||
      (event.data && typeof event.data === 'object'
        ? (typeof event.data.message === 'string'
            ? event.data.message
            : typeof event.data.details === 'string'
              ? event.data.details
              : JSON.stringify(event.data))
        : typeof event.data === 'string'
          ? event.data
          : undefined)
    return {
      ...event,
      name: event.name || String(stageName),
      label,
      started_at: event.started_at || event.timestamp,
      details,
    }
  })
}

function TimelineView({ timeline }: { timeline: WorkflowStage[] }) {
  if (!timeline?.length) {
    return <p className="text-sm text-muted-foreground">No timeline events are available yet.</p>
  }

  return (
    <div className="space-y-3">
      {timeline.map((stage, i) => {
        const isCompleted = stage.status === 'completed'
        const isActive = stage.status === 'in_progress'
        const isFailed = stage.status === 'failed'
        return (
          <div key={`${stage.name || stage.stage || 'stage'}-${i}`} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all duration-300 ${
                isCompleted ? 'bg-primary border-primary text-white' :
                isActive ? 'border-primary text-primary bg-primary/10' :
                isFailed ? 'border-destructive text-destructive bg-destructive/10' :
                'border-border-light text-muted bg-surface-alt'
              }`}>
                {isCompleted ? '✓' : isFailed ? '✕' : i + 1}
              </div>
              {i < timeline.length - 1 && (
                <div className={`w-0.5 flex-1 mt-1 ${isCompleted ? 'bg-primary/40' : 'bg-border'}`} />
              )}
            </div>
            <div className="flex-1 pb-6">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-sm font-medium ${
                  isCompleted ? 'text-primary' : isActive ? 'text-foreground' : isFailed ? 'text-destructive' : 'text-muted'
                }`}>
                  {stage.label || stage.name}
                </span>
                <StatusBadge status={stage.status} />
              </div>
              {stage.started_at && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock size={10} />
                  {formatDate(stage.started_at)}
                </p>
              )}
              {stage.details && <p className="text-xs text-muted-foreground mt-1">{stage.details}</p>}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StageMetrics({ timeline, progress }: { timeline: WorkflowStage[]; progress: number }) {
  const completed = timeline.filter((s) => s.status === 'completed').length
  const failed = timeline.filter((s) => s.status === 'failed').length
  const total = timeline.length

  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="text-center">
        <p className="text-2xl font-bold text-foreground">{completed}/{total}</p>
        <p className="text-xs text-muted-foreground mt-1">Events Completed</p>
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-primary">{formatPercent(progress)}</p>
        <p className="text-xs text-muted-foreground mt-1">Workflow Progress</p>
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-destructive">{failed}</p>
        <p className="text-xs text-muted-foreground mt-1">Failures</p>
      </div>
    </div>
  )
}

function extractWorkflowIdFromPath(): string {
  const match = window.location.pathname.match(/\/workflow\/(.+)/)
  if (match && match[1]) {
    return decodeURIComponent(match[1])
  }
  return ''
}

export default function WorkflowTrackingPage() {
  const params = useParams<{ workflowId: string }>()
  const navigate = useNavigate()

  const routeWorkflowId = params.workflowId || extractWorkflowIdFromPath()
  const initialNormalized = routeWorkflowId ? normalizeWorkflowId(routeWorkflowId) : ''

  const [workflowId, setWorkflowId] = useState(initialNormalized)
  const [searchInput, setSearchInput] = useState(routeWorkflowId || '')
  const queryClient = useQueryClient()

  // Fix ④: track the timestamp of the most recent WebSocket push so the
  // 5-second REST poll never overwrites data that is already fresher.
  const wsLastUpdatedRef = useRef<number>(0)

  console.log(`[workflow-tracking] render — route param: "${params.workflowId}", path-derived: "${extractWorkflowIdFromPath()}", state: "${workflowId}"`)

  useEffect(() => {
    const id = params.workflowId || extractWorkflowIdFromPath()
    if (id) {
      const normalized = normalizeWorkflowId(id)
      console.log(`[workflow-tracking] route effect — "${id}" -> normalized "${normalized}"`)
      setWorkflowId(normalized)
      setSearchInput(id)
      if (normalized !== id) {
        navigate(`/workflow/${normalized}`, { replace: true })
      }
    }
  }, [params.workflowId, navigate])

  const {
    data: workflow,
    isLoading,
    error,
    refetch,
  } = useQuery<WorkflowStatus>({
    queryKey: ['workflow-status', workflowId],
    queryFn: async () => {
      if (!workflowId) throw new Error('No workflow ID provided')
      const url = `/foster/status/${encodeURIComponent(workflowId)}`
      console.log(`[workflow-tracking] 🔍 executing queryFn — GET ${url}`)
      const response = await api.get<WorkflowStatus>(url)
      console.log(`[workflow-tracking] ✅ queryFn response:`, response.data)
      console.log(`[workflow-tracking] workflow.status type: ${typeof response.data?.status} value:`, response.data?.status)
      // Fix ④: if a WebSocket push arrived in the last 3 s, keep that data
      // and discard this (potentially stale) REST snapshot.
      const age = Date.now() - wsLastUpdatedRef.current
      if (age < 3000) {
        console.log(`[workflow-tracking] skipping REST update — WS data is ${age}ms old`)
        const cached = queryClient.getQueryData<WorkflowStatus>(['workflow-status', workflowId])
        if (cached) return cached
      }
      return response.data
    },
    enabled: workflowId !== null && workflowId !== undefined && workflowId.trim().length > 0,
    refetchInterval: 5000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  })

  useEffect(() => {
    if (workflowId) {
      console.log(`[workflow-tracking] query key updated — watching workflowId: "${workflowId}"`)
    }
  }, [workflowId])

  useEffect(() => {
    if (workflow) {
      console.log('[workflow-tracking] rendering — workflow:', workflow)
      console.log('[workflow-tracking] API response timeline:', workflow.timeline)
      console.log('[workflow-tracking] current_stage:', workflow.current_stage)
      console.log('[workflow-tracking] progress:', workflow.progress)
    }
  }, [workflow])

  // Subscribe to per-workflow WebSocket stream for live updates
  useEffect(() => {
    if (!workflowId) return
    const sub = subscribeWorkflowStream(
      workflowId,
      (msg) => {
        console.log('[workflow-tracking] ws message', msg)
        // Fix ④: stamp the time so the REST poll knows WS data is fresh
        wsLastUpdatedRef.current = Date.now()
        queryClient.setQueryData(['workflow-status', workflowId], (current) => {
          const existing = (current as WorkflowStatus) || {
            workflow_id: workflowId,
            status: 'unknown',
            active: true,
            progress: 0,
            timeline: [],
            stages: [],
          }
          return {
            ...existing,
            ...msg,
            timeline: msg.timeline ?? existing.timeline,
            stages: existing.stages || [],
          } as WorkflowStatus
        })
      },
      () => console.log('[workflow-tracking] ws open'),
      () => console.log('[workflow-tracking] ws close'),
    )
    return () => sub.close()
  }, [workflowId, queryClient])

  const timelineItems = workflow ? normalizeTimelineEvents(workflow.timeline || []) : []
  const formattedMatchScore = formatPercent(workflow?.match_score ?? null)
  const formattedConfidence = formatPercent(workflow?.confidence_score ?? null)
  const formattedRiskScore = formatRiskScore(workflow?.risk_score ?? null)
  const progressValue = workflow?.progress ?? 0

  const handleSearch = useCallback(() => {
    const raw = searchInput.trim()
    if (raw) {
      const normalized = normalizeWorkflowId(raw)
      console.log(`[workflow-tracking] search — "${raw}" -> normalized "${normalized}"`)
      setWorkflowId(normalized)
      navigate(`/workflow/${normalized}`, { replace: true })
    }
  }, [searchInput, navigate])

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/" className="text-muted-foreground hover:text-foreground transition-colors">
          <ArrowLeft size={20} />
        </Link>
        <div className="flex-1">
          <h1 className="text-2xl font-bold text-foreground">Workflow Tracking</h1>
          <p className="text-sm text-muted-foreground mt-1">Track the real-time status of orchestration workflows</p>
        </div>
      </div>

      <GlassCard>
        <div className="flex gap-3">
          <div className="flex-1">
            <Input
              placeholder="Workflow ID (e.g. foster-3001)"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <Button onClick={handleSearch} loading={isLoading}>
            <Search size={16} />
            Search
          </Button>
        </div>
        {workflowId && (
          <p className="text-xs text-muted-foreground mt-2">
            Tracking: <span className="font-mono text-foreground">{workflowId}</span>
          </p>
        )}
      </GlassCard>

      {workflowId && (
        <DataLoader isLoading={isLoading} error={error} refetch={refetch}>
          {workflow ? (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <GlassCard className="lg:col-span-2">
                  <GlassCardHeader>
                    <GlassCardTitle>Workflow Overview</GlassCardTitle>
                  </GlassCardHeader>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground">Workflow ID</p>
                      <p className="text-sm font-mono text-foreground mt-1 break-all">{workflow.workflow_id}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Child ID</p>
                      <p className="text-sm font-mono text-foreground mt-1">{workflow.child_id || '—'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Status</p>
                      <div className="mt-1"><StatusBadge status={workflow.status} /></div>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Family ID</p>
                      <p className="text-sm font-mono text-foreground mt-1">{workflow.family_id || '—'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Match Score</p>
                      <p className="text-sm font-mono text-foreground mt-1">{formattedMatchScore}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Confidence</p>
                      <p className="text-sm font-mono text-foreground mt-1">{formattedConfidence}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Current Stage</p>
                      <p className="text-sm text-foreground mt-1">{workflow.current_stage || 'Unknown'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Created</p>
                      <p className="text-sm text-muted-foreground mt-1">{formatDate(workflow.created_at)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Updated</p>
                      <p className="text-sm text-muted-foreground mt-1">{formatDate(workflow.updated_at)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Risk Score</p>
                      <p className="text-sm font-mono text-foreground mt-1">{formattedRiskScore}</p>
                    </div>
                    {workflow.recommended_family && (
                      <div>
                        <p className="text-xs text-muted-foreground">Recommended Family</p>
                        <p className="text-sm text-foreground mt-1">
                          {typeof workflow.recommended_family === 'string'
                            ? workflow.recommended_family
                            : JSON.stringify(workflow.recommended_family)}
                        </p>
                      </div>
                    )}
                    {workflow.capacity !== undefined && workflow.capacity !== null && (
                      <div>
                        <p className="text-xs text-muted-foreground">Capacity</p>
                        <p className="text-sm text-foreground mt-1">{workflow.capacity}</p>
                      </div>
                    )}
                  </div>
                </GlassCard>
                <GlassCard>
                  <GlassCardHeader>
                    <GlassCardTitle>Stage Progress</GlassCardTitle>
                  </GlassCardHeader>
                  <StageMetrics timeline={timelineItems} progress={progressValue} />
                </GlassCard>
              </div>

              <GlassCard>
                <GlassCardHeader>
                  <GlassCardTitle>Workflow Timeline</GlassCardTitle>
                  <Button variant="ghost" size="sm" onClick={() => refetch()}>
                    <RefreshCw size={14} />
                  </Button>
                </GlassCardHeader>
                <div className="mb-6">
                  <AnimatedProgressSteps stages={workflow.stages || []} currentStage={workflow.current_stage || ''} />
                </div>
                <Separator className="my-4" />
                <TimelineView timeline={timelineItems} />
              </GlassCard>

              {workflow.top_matches && Array.isArray(workflow.top_matches) && workflow.top_matches.length > 0 && (
                <GlassCard>
                  <GlassCardHeader>
                    <GlassCardTitle>Top Matches</GlassCardTitle>
                  </GlassCardHeader>
                  <div className="space-y-3 p-4">
                    {workflow.top_matches.map((match, index) => {
                      const familyObj = (match as any).family ?? match
                      const familyName = typeof familyObj === 'object'
                        ? (familyObj as any).name ?? (familyObj as any).family_name ?? `Family ${(familyObj as any).family_id ?? ''}`
                        : String(familyObj)
                      const score = (match as any).blended_score ?? (match as any).match_score ?? 0
                      const riskPct = (match as any).risk_probability ?? 0
                      const explanation = (match as any).explanation ?? ''

                      return (
                        <div key={index} className="rounded-xl border border-border p-3 bg-surface">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-sm font-medium text-foreground">
                              <span className="text-muted-foreground mr-1">#{index + 1}</span>
                              {familyName}
                            </p>
                            <span className="text-sm font-semibold text-primary">{formatPercent(score)}</span>
                          </div>
                          <div className="w-full bg-muted rounded-full h-1.5 mb-1">
                            <div
                              className="bg-primary h-1.5 rounded-full transition-all"
                              style={{ width: `${Math.min(score, 100)}%` }}
                            />
                          </div>
                          <div className="flex items-center gap-3 text-xs text-muted-foreground">
                            <span>Risk: {formatPercent(riskPct * 100)}</span>
                            {explanation && <span className="truncate">{explanation}</span>}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </GlassCard>
              )}

              {workflow.feature_importance && Array.isArray(workflow.feature_importance) && workflow.feature_importance.length > 0 && (
                <GlassCard>
                  <GlassCardHeader>
                    <GlassCardTitle>Feature Importance</GlassCardTitle>
                  </GlassCardHeader>
                  <div className="space-y-3 p-4">
                    {workflow.feature_importance.map((feature, index) => (
                      <div key={index} className="rounded-xl border border-border p-3 bg-surface">
                        <p className="text-sm font-medium text-foreground">
                          {(feature as any).feature || (feature as any).name || JSON.stringify(feature)}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Importance: {((feature as any).importance ?? (feature as any).score ?? 0).toString()}
                        </p>
                      </div>
                    ))}
                  </div>
                </GlassCard>
              )}

              {workflow.metadata && Object.keys(workflow.metadata).length > 0 && (
                <GlassCard>
                  <GlassCardHeader>
                    <GlassCardTitle>Metadata</GlassCardTitle>
                  </GlassCardHeader>
                  <pre className="text-xs text-muted-foreground font-mono whitespace-pre-wrap">
                    {JSON.stringify(workflow.metadata, null, 2)}
                  </pre>
                </GlassCard>
              )}
            </div>
          ) : (
            <GlassCard>
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <AlertCircle size={32} className="text-warning mb-3" />
                <p className="text-sm text-muted-foreground">No workflow data returned for "{workflowId}"</p>
                <Button variant="secondary" size="sm" className="mt-4" onClick={() => refetch()}>
                  <RefreshCw size={14} />
                  Retry
                </Button>
              </div>
            </GlassCard>
          )}
        </DataLoader>
      )}

      {!workflowId && (
        <GlassCard>
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <Search size={40} className="text-muted mb-4" />
            <h2 className="text-lg font-semibold text-foreground mb-2">Search for a Workflow</h2>
            <p className="text-sm text-muted-foreground max-w-md">
              Enter a Workflow ID above to track its real-time status through the orchestration pipeline.
            </p>
          </div>
        </GlassCard>
      )}
    </motion.div>
  )
}
