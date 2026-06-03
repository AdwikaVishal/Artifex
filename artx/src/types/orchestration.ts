export type AgentType =
  | 'intake'
  | 'planner'
  | 'risk'
  | 'matching'
  | 'fairness'
  | 'approval'
  | 'monitoring'

export type AgentStatus = 'idle' | 'active' | 'completed' | 'error'

export type StepStatus = 'pending' | 'active' | 'completed' | 'error'

export type MessageType = 'info' | 'success' | 'error' | 'warning'

export interface AgentNodeData {
  id: string
  name: string
  type: AgentType
  status: AgentStatus
  confidence?: number
}

export interface AgentMetrics {
  tasksCompleted: number
  avgResponseTime: number
  successRate: number
  messagesProcessed: number
  confidenceScore: number
}

export interface ExecutionStep {
  id: string
  label: string
  status: StepStatus
  agentId: string
  agentName: string
}

export interface AgentMessage {
  id: string
  timestamp: Date
  from: string
  to?: string
  content: string
  type: MessageType
}

export interface DecisionReason {
  label: string
  satisfied: boolean
}

export interface DecisionData {
  recommendedFamily: string
  matchScore: number
  reasons: DecisionReason[]
  explanation: string
}

export interface DemoStepConfig {
  stepId: string
  duration: number
  message: Omit<AgentMessage, 'id' | 'timestamp'>
  activeAgentId: string
  updatedAgentStatus: AgentStatus
  stepLabel: string
}

export const AGENT_CONFIG: Record<AgentType, { name: string; label: string }> = {
  intake: { name: 'Intake Agent', label: 'Intake' },
  planner: { name: 'Planner Agent', label: 'Planner' },
  risk: { name: 'Risk Assessment Agent', label: 'Risk' },
  matching: { name: 'Family Matching Agent', label: 'Matching' },
  fairness: { name: 'Fairness Agent', label: 'Fairness' },
  approval: { name: 'Approval Agent', label: 'Approval' },
  monitoring: { name: 'Monitoring Agent', label: 'Monitoring' },
}

export const INITIAL_AGENT_METRICS: Record<AgentType, AgentMetrics> = {
  intake: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  planner: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  risk: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  matching: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  fairness: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  approval: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
  monitoring: { tasksCompleted: 0, avgResponseTime: 0, successRate: 0, messagesProcessed: 0, confidenceScore: 0 },
}
