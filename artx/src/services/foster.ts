import api from './api'
import type {
  ReferralSubmission,
  ReferralResponse,
  WorkflowStatus,
  PendingApproval,
  PendingApprovalsResponse,
  ApproveRequest,
  ApproveResponse,
  Placement,
  HealthStatus,
  DashboardMetrics,
  RiskDistribution,
  WorkflowEvent,
  DashboardEventsResponse,
  AgentStatusMap,
  Family,
  FamilyCreate,
  FamilyUpdate,
} from '@/types'

export function normalizeWorkflowId(input: unknown): string {
  if (typeof input !== 'string') return ''
  const trimmed = input.trim()

  // If already a foster-* id, keep as-is
  if (/^foster-/i.test(trimmed)) return trimmed

  // CHILD-123 or CHILD-123 (case-insensitive) -> foster-123
  const mChild = trimmed.match(/^CHILD-(\d+)$/i)
  if (mChild) {
    const normalized = `foster-${mChild[1]}`
    console.log(`[foster] normalized "${trimmed}" -> "${normalized}"`)
    return normalized
  }

  // CH-123 -> foster-123
  const mCh = trimmed.match(/^CH-(\d+)$/i)
  if (mCh) {
    const normalized = `foster-${mCh[1]}`
    console.log(`[foster] normalized "${trimmed}" -> "${normalized}"`)
    return normalized
  }

  // Pure digits -> foster-<digits>
  if (/^\d+$/.test(trimmed)) {
    const normalized = `foster-${trimmed}`
    console.log(`[foster] normalized numeric input "${trimmed}" -> "${normalized}"`)
    return normalized
  }

  // Default: prefix with foster- preserving non-numeric child ids (e.g., CABC123)
  const normalized = `foster-${trimmed}`
  console.log(`[foster] normalized default "${trimmed}" -> "${normalized}"`)
  return normalized
}

export async function submitReferral(data: ReferralSubmission): Promise<ReferralResponse> {
  const payload = {
    child_id: data.child_id,
    age: data.age,
    gender: data.gender,
    special_needs: data.special_needs,
    languages: data.languages,
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

// ── Timeline → WorkflowStage converter ──────────────────────────────────────

const STAGE_NAMES = [
  'Intake',
  'Eligibility Validation',
  'ML Inference',
  'Placement Matching',
  'Recommendation Generated',
  'Approval Pending',
  'Placement Approved',
  'Placement Active',
  'Monitoring',
]

function buildStagesFromTimeline(
  timeline: any[],
  currentStage: string,
): WorkflowStage[] {
  return STAGE_NAMES.map((name) => {
    const events = (timeline || []).filter((e: any) => {
      const eStage = (e.stage || e.name || '').toLowerCase()
      return eStage === name.toLowerCase()
    })
    const completedEvent = events.find(
      (e: any) => e.status === 'completed' || e.status === 'active',
    )
    const startEvent = events[0]
    const isCurrent =
      currentStage &&
      name.toLowerCase() === currentStage.toLowerCase()

    let status: WorkflowStage['status'] = 'pending'
    if (completedEvent) {
      status = 'completed'
    } else if (isCurrent || events.length > 0) {
      status = 'in_progress'
    }

    return {
      name: name.toLowerCase().replace(/\s+/g, '_'),
      label: name,
      status,
      started_at: startEvent?.timestamp || undefined,
      completed_at: completedEvent?.timestamp || undefined,
      details: startEvent?.data
        ? JSON.stringify(startEvent.data).slice(0, 120)
        : undefined,
    }
  })
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
  const res = await api.get<any>(`/foster/status/${encodeURIComponent(normalized)}`)
  console.log(`[foster] workflow status response for "${normalized}":`, res.data)

  const d = res.data || {}
  const now = new Date().toISOString()
  const timeline = d.timeline || []

  const normalizedStatus: WorkflowStatus = {
    workflow_id: d.workflow_id || normalized,
    child_id: d.child_id || '',
    family_id: d.family_id || '',
    status: d.status || 'unknown',
    current_stage: d.current_stage || '',
    stages: buildStagesFromTimeline(timeline, d.current_stage || ''),
    risk_score: d.risk_score ?? null,
    match_score: d.match_score ?? null,
    confidence_score: d.confidence_score ?? null,
    recommended_family: d.recommended_family || null,
    capacity: d.capacity ?? null,
    progress: d.progress ?? 0,
    timeline,
    feature_importance: d.feature_importance || null,
    top_matches: d.top_matches || null,
    active: d.active ?? true,
    metadata: d.metadata || {},
    created_at: d.created_at || now,
    updated_at: d.updated_at || now,
  }
  console.log(`[foster] normalized workflow status:`, normalizedStatus)
  return normalizedStatus
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

// ── Families CRUD ─────────────────────────────────────────────────────────

export interface FamiliesResponse {
  families: Family[]
  count: number
}

export async function getFamilies(): Promise<Family[]> {
  console.log('[foster] fetching families...')
  const res = await api.get<FamiliesResponse | Family[]>('/families')
  if (Array.isArray(res.data)) {
    return res.data as Family[]
  }
  const wrapper = res.data as FamiliesResponse
  if (wrapper && Array.isArray(wrapper.families)) {
    return wrapper.families
  }
  return []
}

export async function getFamily(familyId: string): Promise<Family> {
  const res = await api.get<Family>(`/families/${encodeURIComponent(familyId)}`)
  return res.data
}

export async function createFamily(data: FamilyCreate): Promise<Family> {
  const res = await api.post<Family>('/families', data)
  return res.data
}

export async function updateFamily(familyId: string, data: FamilyUpdate): Promise<Family> {
  const res = await api.put<Family>(`/families/${encodeURIComponent(familyId)}`, data)
  return res.data
}

export async function deleteFamily(familyId: string): Promise<void> {
  await api.delete(`/families/${encodeURIComponent(familyId)}`)
}

// --- WebSocket streaming helper for workflow updates ---------------------
export function subscribeWorkflowStream(
  workflowId: string,
  onMessage: (msg: any) => void,
  onOpen?: () => void,
  onClose?: () => void,
): { close: () => void } {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const host = window.location.host
  const url = `${protocol}://${host}/workflow/${encodeURIComponent(workflowId)}/stream`

  let ws: WebSocket | null = null
  let shouldClose = false

  function connect() {
    ws = new WebSocket(url)
    ws.onopen = () => { onOpen && onOpen() }
    ws.onmessage = (ev) => {
      try { const data = JSON.parse(ev.data); onMessage(data) } catch (err) { console.warn('[foster.ws] parse error', err) }
    }
    ws.onclose = () => {
      if (shouldClose) { onClose && onClose(); return }
      // reconnect with backoff
      setTimeout(() => connect(), 1000)
    }
    ws.onerror = (e) => { console.warn('[foster.ws] error', e) }
  }

  connect()

  return {
    close: () => {
      shouldClose = true
      try { ws?.close() } catch (_) {}
    },
  }
}

export async function getDashboardMetrics(): Promise<DashboardMetrics> {
  const res = await api.get<DashboardMetrics>('/dashboard/metrics')
  return res.data
}

export async function getRiskDistribution(): Promise<RiskDistribution> {
  const res = await api.get<RiskDistribution>('/dashboard/risk-distribution')
  return res.data
}

export async function getDashboardEvents(): Promise<WorkflowEvent[]> {
  const res = await api.get<DashboardEventsResponse | WorkflowEvent[]>('/dashboard/events')
  const data = res.data
  if (Array.isArray(data)) return data as WorkflowEvent[]
  if (data && 'events' in data) return data.events || []
  return []
}

export async function getAgentStatuses(): Promise<AgentStatusMap> {
  const res = await api.get<AgentStatusMap>('/agent/status')
  return res.data
}
