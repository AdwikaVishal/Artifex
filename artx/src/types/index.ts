export interface ReferralSubmission {
  child_id: string
  age: number
  gender: string
  medical_needs: string
  behavioral_support: string
  sibling_group: boolean
  emergency_level: string
  preferred_location: string
  foster_home_type: string
  capacity_needed: number
  accessibility_needs: boolean
  school_continuity: boolean
  risk_flags: string[]
  notes: string
}

export interface ReferralResponse {
  workflow_id: string
  child_id: string
  status: string
  message: string
  created_at: string
}

export interface WorkflowNestedStatus {
  stage?: string
  status?: string
  child_id?: string
  family_id?: string
  risk_score?: number
  risk_history?: Array<{ score: number; check_score?: number; notes?: string; timestamp?: string }>
  alert_sent?: boolean
  active?: boolean
  workflow_id?: string
  current_stage?: string
  stages?: WorkflowStage[]
  recommended_family?: string
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface WorkflowStatus {
  workflow_id: string
  child_id: string
  status: string
  current_stage: string
  stages: WorkflowStage[]
  risk_score?: number
  recommended_family?: string
  metadata?: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface WorkflowStage {
  name: string
  label: string
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  started_at?: string
  completed_at?: string
  duration?: string
  details?: string
}

export interface PendingApproval {
  workflow_id?: string
  child_id?: string
  emergency_level?: string
  risk_score?: number
  recommended_family?: string
  status?: string
  created_at?: string
  age?: number
  gender?: string
  location?: string
}

export interface ApproveRequest {
  workflow_id: string
  approved: boolean
  comment: string
}

export interface ApproveResponse {
  status: string
  message?: string
}

export interface Placement {
  id?: string
  workflow_id?: string
  child_id?: string
  foster_family_name?: string
  location?: string
  emergency_level?: string
  risk_score?: number
  status?: string
  placement_date?: string
  match_score?: number
  capacity?: number
  siblings_accommodated?: boolean
  special_needs_met?: string[]
}

export interface HealthStatus {
  status: string
  service?: string
  version?: string
  uptime?: string
  services?: {
    nats?: ServiceHealth
    temporal?: ServiceHealth
    postgres?: ServiceHealth
    agents?: AgentHealth
  }
}

export interface ServiceHealth {
  status: string
  latency_ms?: number
  message?: string
}

export interface AgentHealth {
  total: number
  active: number
  failed: number
  agents: AgentStatus[]
}

export interface AgentStatus {
  name: string
  status: 'active' | 'inactive' | 'error' | 'busy'
  task: string
  uptime?: string
  last_heartbeat: string
  workflows_processed: number
}

export interface EventMessage {
  id: string
  type: string
  source: string
  message: string
  severity: 'info' | 'warning' | 'error' | 'success'
  timestamp: string
  workflow_id?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  sources?: string[]
  actions?: ChatAction[]
}

export interface ChatAction {
  label: string
  action: string
  payload?: Record<string, unknown>
}

export interface ChatRequest {
  message: string
  workflow_id?: string
  context?: Record<string, unknown>
}

export interface ChatResponse {
  id: string
  message: string
  sources?: string[]
  actions?: ChatAction[]
}

export interface DashboardMetrics {
  active_workflows: number
  pending_approvals: number
  placements_matched: number
  emergency_referrals: number
  workflows_change: number
  approvals_change: number
  placements_change: number
  emergency_change: number
}

export interface WorkflowEvent {
  id: string
  type: string
  workflow_id: string
  workflow_stage: string
  child_id: string
  message: string
  timestamp: string
}

export interface RiskDistribution {
  low: number
  medium: number
  high: number
  critical: number
}

export interface PendingApprovalsResponse {
  approvals: PendingApproval[]
  count: number
}
