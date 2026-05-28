import api from './api'
import type {
  ReferralSubmission,
  ReferralResponse,
  WorkflowStatus,
  WorkflowNestedStatus,
  PendingApproval,
  PendingApprovalsResponse,
  ApproveRequest,
  ApproveResponse,
  Placement,
  HealthStatus,
  AgentStatus,
  DashboardMetrics,
  RiskDistribution,
  WorkflowEvent,
} from '@/types'

export function normalizeWorkflowId(input: unknown): string {
  if (typeof input !== 'string') return ''
  const trimmed = input.trim()

  if (/^foster-CHILD-\d+$/.test(trimmed)) {
    return trimmed
  }

  if (/^CHILD-\d+$/i.test(trimmed)) {
    const normalized = `foster-${trimmed.toUpperCase()}`
    console.log(`[foster] normalized "${trimmed}" -> "${normalized}"`)
    return normalized
  }

  const digits = trimmed.match(/\d+/)
  if (digits) {
    const normalized = `foster-CHILD-${digits[0]}`
    console.log(`[foster] normalized numeric input "${trimmed}" -> "${normalized}"`)
    return normalized
  }

  return trimmed
}

export async function submitReferral(data: ReferralSubmission): Promise<ReferralResponse> {
  const payload = {
    child_id: data.child_id,
    age: data.age,
    gender: data.gender,
    medical_needs: data.medical_needs,
    behavioral_support: data.behavioral_support,
    sibling_group: data.sibling_group,
    emergency_level: data.emergency_level,
    preferred_location: data.preferred_location,
    foster_home_type: data.foster_home_type,
    capacity_needed: data.capacity_needed,
    accessibility_needs: data.accessibility_needs,
    school_continuity: data.school_continuity,
    risk_flags: data.risk_flags,
    notes: data.notes,
  }
  console.log('[foster] submitReferral payload:', JSON.stringify(payload, null, 2))
  const res = await api.post<ReferralResponse>('/api/referral', payload)
  console.log('[foster] submitReferral response:', res.data)
  console.log(`[foster] workflow_id received: "${res.data.workflow_id}" — will navigate to /workflow/${res.data.workflow_id}`)
  return res.data
}

export async function getPendingApprovals(): Promise<PendingApproval[]> {
  console.log('[foster] fetching pending approvals...')
  const res = await api.get<PendingApprovalsResponse | PendingApproval[]>('/api/pending_approvals')
  console.log('[foster] pending approvals response:', res.data)

  if (Array.isArray(res.data)) {
    return res.data as PendingApproval[]
  }

  const wrapper = res.data as PendingApprovalsResponse
  if (wrapper && Array.isArray(wrapper.approvals)) {
    return wrapper.approvals
  }

  console.warn('[foster] unexpected approvals response shape:', res.data)
  return []
}

export async function approveReferral(data: ApproveRequest): Promise<ApproveResponse> {
  const payload = {
    workflow_id: data.workflow_id,
    approved: data.approved,
    comment: data.comment,
  }
  console.log('[foster] approveReferral payload:', JSON.stringify(payload, null, 2))
  const res = await api.post<ApproveResponse>('/api/approve', payload)
  console.log('[foster] approveReferral response:', res.data)
  return res.data
}

export async function supervisorApprove(data: ApproveRequest): Promise<ApproveResponse> {
  const payload = {
    workflow_id: data.workflow_id,
    approved: data.approved,
    comment: data.comment,
  }
  console.log('[foster] supervisorApprove payload:', JSON.stringify(payload, null, 2))
  const res = await api.post<ApproveResponse>('/api/supervisor_approve', payload)
  console.log('[foster] supervisorApprove response:', res.data)
  return res.data
}

export async function getPlacements(): Promise<Placement[]> {
  console.log('[foster] fetching placements...')
  const res = await api.get<Placement[] | { placements: Placement[] }>('/foster/placements')
  console.log('[foster] placements response:', res.data)

  let placements: Placement[] = []

  if (Array.isArray(res.data)) {
    placements = res.data as Placement[]
  } else {
    const wrapper = res.data as { placements: Placement[] }
    if (wrapper && Array.isArray(wrapper.placements)) {
      placements = wrapper.placements
    }
  }

  placements.forEach((p, i) => {
    if (!p || typeof p !== 'object') {
      console.warn(`[foster] placement[${i}] is not an object:`, p)
    } else {
      Object.entries(p).forEach(([key, val]) => {
        if (val === null || val === undefined) {
          console.warn(`[foster] placement[${i}].${key} is ${val}`)
        }
      })
    }
  })

  return placements
}

export async function getWorkflowStatus(workflowId: string): Promise<WorkflowStatus> {
  const raw = workflowId
  const normalized = normalizeWorkflowId(workflowId)

  if (!normalized || !normalized.trim()) {
    throw new Error('workflow_id is required')
  }

  if (raw !== normalized) {
    console.log(`[foster] normalized workflow ID: "${raw}" -> "${normalized}"`)
  }

  console.log(`[foster] fetching workflow status for: "${normalized}"`)
  const res = await api.get<{ workflow_id: string; status: WorkflowNestedStatus | string }>(`/foster/status/${encodeURIComponent(normalized)}`)
  console.log(`[foster] workflow status response for "${normalized}":`, res.data)

  const rawData = res.data

  if (rawData.status && typeof rawData.status === 'object') {
    const nested = rawData.status as WorkflowNestedStatus
    const now = new Date().toISOString()
    const normalizedStatus: WorkflowStatus = {
      workflow_id: rawData.workflow_id || nested.workflow_id || normalized,
      child_id: nested.child_id || '',
      status: nested.status || 'unknown',
      current_stage: nested.current_stage || nested.stage || '',
      stages: nested.stages || [],
      risk_score: nested.risk_score,
      recommended_family: nested.recommended_family,
      metadata: nested.metadata,
      created_at: nested.created_at || now,
      updated_at: nested.updated_at || now,
    }
    console.log(`[foster] normalized workflow status:`, normalizedStatus)
    return normalizedStatus
  }

  return rawData as unknown as WorkflowStatus
}

export async function getAgentStatus(agentName: string): Promise<AgentStatus> {
  const res = await api.get<AgentStatus>(`/agent/status/${agentName}`)
  return res.data
}

export async function getHealth(): Promise<HealthStatus> {
  console.log('[foster] fetching health...')
  const res = await api.get<HealthStatus>('/health')
  console.log('[foster] health response:', res.data)
  return res.data
}

export async function sendChatMessage(
  message: string,
  workflowId?: string
): Promise<{ id: string; message: string; sources?: string[]; actions?: { label: string; action: string; payload?: Record<string, unknown> }[] }> {
  const body: Record<string, unknown> = { message }
  if (workflowId) body.workflow_id = workflowId
  const res = await api.post('/chat', body)
  return res.data
}

export async function getHealthCheck(): Promise<boolean> {
  try {
    const res = await api.get('/health', { timeout: 5000 })
    const ok = res.status === 200
    console.log(`[foster] health check: ${ok ? 'OK' : 'FAIL'} (status ${res.status})`, res.data)
    return ok
  } catch (err) {
    console.warn('[foster] health check failed:', err instanceof Error ? err.message : err)
    return false
  }
}

export function getMockMetrics(): DashboardMetrics {
  return {
    active_workflows: 24,
    pending_approvals: 8,
    placements_matched: 156,
    emergency_referrals: 3,
    workflows_change: 12,
    approvals_change: -2,
    placements_change: 8,
    emergency_change: 0,
  }
}

export function getMockRiskDistribution(): RiskDistribution {
  return { low: 45, medium: 30, high: 18, critical: 7 }
}

export function getMockEvents(): WorkflowEvent[] {
  return [
    { id: '1', type: 'status_change', workflow_id: 'WF-2024-001', workflow_stage: 'matching', child_id: 'CH-101', message: 'Matching algorithm initiated for child CH-101', timestamp: new Date(Date.now() - 30000).toISOString() },
    { id: '2', type: 'approval', workflow_id: 'WF-2024-002', workflow_stage: 'approval_pending', child_id: 'CH-102', message: 'Approval request sent to supervisor', timestamp: new Date(Date.now() - 120000).toISOString() },
    { id: '3', type: 'placement', workflow_id: 'WF-2024-003', workflow_stage: 'placement_assigned', child_id: 'CH-103', message: 'Placement confirmed with Johnson family', timestamp: new Date(Date.now() - 300000).toISOString() },
    { id: '4', type: 'alert', workflow_id: 'WF-2024-004', workflow_stage: 'risk_analysis', child_id: 'CH-104', message: 'High risk flags detected - manual review required', timestamp: new Date(Date.now() - 600000).toISOString() },
    { id: '5', type: 'status_change', workflow_id: 'WF-2024-005', workflow_stage: 'submitted', child_id: 'CH-105', message: 'New referral submitted for CH-105', timestamp: new Date(Date.now() - 1800000).toISOString() },
  ]
}

export function getMockAgentStatuses(): AgentStatus[] {
  return [
    { name: 'matching-agent', status: 'active', task: 'Matching CH-104 with foster families', last_heartbeat: new Date(Date.now() - 5000).toISOString(), workflows_processed: 142 },
    { name: 'risk-analyzer', status: 'active', task: 'Analyzing risk profile for WF-2024-006', last_heartbeat: new Date(Date.now() - 8000).toISOString(), workflows_processed: 98 },
    { name: 'approval-coordinator', status: 'busy', task: 'Processing supervisor approval for WF-2024-002', last_heartbeat: new Date(Date.now() - 15000).toISOString(), workflows_processed: 56 },
    { name: 'notification-agent', status: 'active', task: 'Idle', last_heartbeat: new Date(Date.now() - 3000).toISOString(), workflows_processed: 210 },
    { name: 'placement-optimizer', status: 'active', task: 'Optimizing placement for CH-101', last_heartbeat: new Date(Date.now() - 12000).toISOString(), workflows_processed: 73 },
  ]
}
