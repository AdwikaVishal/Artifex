import { useQuery } from '@tanstack/react-query'
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
import { normalizeWorkflowId } from '@/services/foster'
import { motion } from 'framer-motion'
import { Search, Clock, AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { WorkflowStatus, WorkflowStage } from '@/types'
import { useState, useEffect, useCallback } from 'react'

function TimelineView({ stages }: { stages: WorkflowStage[] }) {
  return (
    <div className="space-y-3">
      {stages.map((stage, i) => {
        const isCompleted = stage.status === 'completed'
        const isActive = stage.status === 'in_progress'
        const isFailed = stage.status === 'failed'
        return (
          <div key={stage.name} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-all duration-300 ${
                isCompleted ? 'bg-primary border-primary text-white' :
                isActive ? 'border-primary text-primary bg-primary/10' :
                isFailed ? 'border-destructive text-destructive bg-destructive/10' :
                'border-border-light text-muted bg-surface-alt'
              }`}>
                {isCompleted ? '✓' : isFailed ? '✕' : i + 1}
              </div>
              {i < stages.length - 1 && (
                <div className={`w-0.5 flex-1 mt-1 ${isCompleted ? 'bg-primary/40' : 'bg-border'}`} />
              )}
            </div>
            <div className="flex-1 pb-6">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-sm font-medium ${
                  isCompleted ? 'text-primary' : isActive ? 'text-foreground' : isFailed ? 'text-destructive' : 'text-muted'
                }`}>
                  {getStageLabel(stage.name)}
                </span>
                <StatusBadge status={stage.status} />
              </div>
              {stage.started_at && (
                <p className="text-xs text-muted-foreground flex items-center gap-1">
                  <Clock size={10} />
                  {formatDate(stage.started_at)}
                  {stage.duration && ` · ${stage.duration}`}
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

function StageMetrics({ stages }: { stages: WorkflowStage[] }) {
  const total = stages.length
  const completed = stages.filter((s) => s.status === 'completed').length
  const failed = stages.filter((s) => s.status === 'failed').length
  const progress = total > 0 ? (completed / total) * 100 : 0
  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="text-center">
        <p className="text-2xl font-bold text-foreground">{completed}/{total}</p>
        <p className="text-xs text-muted-foreground mt-1">Stages Complete</p>
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-primary">{Math.round(progress)}%</p>
        <p className="text-xs text-muted-foreground mt-1">Progress</p>
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-destructive">{failed}</p>
        <p className="text-xs text-muted-foreground mt-1">Failed</p>
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
      console.log("[workflow-tracking] rendering — workflow:", workflow)
      console.log("[workflow-tracking] workflow.status:", workflow?.status)
    }
  }, [workflow])

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
              placeholder="Workflow ID (e.g. foster-CHILD-3001)"
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
                      <p className="text-sm font-mono text-foreground mt-1">{workflow.child_id}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Status</p>
                      <div className="mt-1"><StatusBadge status={workflow.status} /></div>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Current Stage</p>
                      <p className="text-sm text-foreground mt-1">{getStageLabel(workflow?.status || "unknown")}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Created</p>
                      <p className="text-sm text-muted-foreground mt-1">{formatDate(workflow.created_at)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Updated</p>
                      <p className="text-sm text-muted-foreground mt-1">{formatDate(workflow.updated_at)}</p>
                    </div>
                    {workflow.risk_score !== undefined && (
                      <div>
                        <p className="text-xs text-muted-foreground">Risk Score</p>
                        <p className="text-sm font-mono text-foreground mt-1">{workflow.risk_score}/10</p>
                      </div>
                    )}
                    {workflow.recommended_family && (
                      <div>
                        <p className="text-xs text-muted-foreground">Recommended Family</p>
                        <p className="text-sm text-foreground mt-1">{workflow.recommended_family}</p>
                      </div>
                    )}
                  </div>
                </GlassCard>
                <GlassCard>
                  <GlassCardHeader>
                    <GlassCardTitle>Stage Progress</GlassCardTitle>
                  </GlassCardHeader>
                  <StageMetrics stages={workflow.stages || []} />
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
                <TimelineView stages={workflow.stages || []} />
              </GlassCard>

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
