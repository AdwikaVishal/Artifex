export type StageStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export type StagePayload = Record<string, unknown>

export interface TimelineEvent {
  id: string
  stage: string
  label: string
  status: StageStatus
  agentName: string
  agentAction: string
  agentOutput: string
  latency: number
  confidenceScore: number
  reasoning: string[]
  timestamp?: string
  startedAt?: string
  completedAt?: string
  details?: string
  payload?: StagePayload
  inputData?: string
  outputData?: string
  decisionExplanation?: string
  logs?: string[]
}

export interface ExecutionMetrics {
  progress: number
  completedStages: number
  totalStages: number
  executionTime: number
  activeAgents: number
  messagesExchanged: number
  riskScore: number
  matchScore: number
  confidenceScore: number
}

export interface ReasoningEntry {
  id: string
  timestamp: string
  agentName: string
  content: string
}

export const MOCK_TIMELINE_EVENTS: TimelineEvent[] = [
  {
    id: 'referral-submitted',
    stage: 'referral_submitted',
    label: 'Referral Submitted',
    status: 'completed',
    agentName: 'Intake Agent',
    agentAction: 'Received referral',
    agentOutput: 'Referral validated — CH-2024-0842',
    latency: 0.12,
    confidenceScore: 98,
    timestamp: new Date(Date.now() - 60000).toISOString(),
    startedAt: new Date(Date.now() - 61000).toISOString(),
    completedAt: new Date(Date.now() - 60000).toISOString(),
    reasoning: ['Emergency referral received via DCFS portal', 'Child age 8, female, West District'],
    details: 'Referral #RF-2024-0842 for emergency foster placement',
    decisionExplanation: 'Referral automatically accepted based on emergency criteria',
  },
  {
    id: 'eligibility-validated',
    stage: 'eligibility_validated',
    label: 'Eligibility Validated',
    status: 'completed',
    agentName: 'Intake Agent',
    agentAction: 'Validated eligibility',
    agentOutput: 'All criteria met — proceeding',
    latency: 0.18,
    confidenceScore: 95,
    timestamp: new Date(Date.now() - 55000).toISOString(),
    startedAt: new Date(Date.now() - 60000).toISOString(),
    completedAt: new Date(Date.now() - 55000).toISOString(),
    reasoning: ['Age within program range (0-17)', 'No prior placement history', 'Emergency priority confirmed'],
    inputData: 'Child age: 8, Region: West, Priority: Emergency',
    outputData: 'Eligibility: Approved, Priority Score: 92/100',
  },
  {
    id: 'child-profile-created',
    stage: 'child_profile_created',
    label: 'Child Profile Created',
    status: 'completed',
    agentName: 'Planner Agent',
    agentAction: 'Created comprehensive profile',
    agentOutput: 'Profile ID: CP-0842 generated',
    latency: 0.45,
    confidenceScore: 92,
    timestamp: new Date(Date.now() - 48000).toISOString(),
    startedAt: new Date(Date.now() - 55000).toISOString(),
    completedAt: new Date(Date.now() - 48000).toISOString(),
    reasoning: ['Assembled intake data into structured profile', 'Identified key needs: trauma-informed care, school continuity', 'Flagged for language requirements (Spanish bilingual)'],
    details: 'Comprehensive child profile with needs assessment',
    decisionExplanation: 'Profile includes 12 key attributes across safety, education, health, and cultural dimensions',
    logs: ['[Planner] Creating child profile...', '[Planner] Analyzing intake data', '[Planner] Profile CP-0842 ready'],
  },
  {
    id: 'risk-assessment',
    stage: 'risk_assessment',
    label: 'Risk Assessment Generated',
    status: 'in_progress',
    agentName: 'Risk Assessment Agent',
    agentAction: 'Calculated risk score',
    agentOutput: 'Risk Score: 45/100 (Low)',
    latency: 0.21,
    confidenceScore: 88,
    timestamp: new Date(Date.now() - 40000).toISOString(),
    startedAt: new Date(Date.now() - 48000).toISOString(),
    reasoning: ['Moderate trauma indicators detected but manageable', 'No active safety concerns', 'Recommend trauma-informed caregiver matching'],
    inputData: 'Case history: 3 events, no previous placements',
    outputData: 'Risk Score: 45, Confidence: 88%, Factors: [trauma: moderate, safety: low, stability: high]',
  },
  {
    id: 'family-matching',
    stage: 'family_matching',
    label: 'Family Matching Complete',
    status: 'pending',
    agentName: 'Family Matching Agent',
    agentAction: 'Evaluated candidate families',
    agentOutput: '3 families evaluated, top: Johnson Family',
    latency: 0.55,
    confidenceScore: 82,
    reasoning: ['Trauma-informed caregivers available', 'Capacity available within required timeframe', 'School continuity maintained', 'Geographic proximity: 3.2 miles', 'Language requirements met'],
    inputData: 'Criteria: trauma-informed, Spanish bilingual, West District',
    outputData: 'Top 3 matches: Johnson (30%), Martinez (28%), Chen (24%)',
  },
  {
    id: 'fairness-validation',
    stage: 'fairness_validation',
    label: 'Fairness Validation Passed',
    status: 'pending',
    agentName: 'Fairness Agent',
    agentAction: 'Audited for bias',
    agentOutput: 'Parity Score: 0.91 (Passed)',
    latency: 0.19,
    confidenceScore: 96,
    reasoning: ['No protected group disparity detected', 'Demographic parity ratio within acceptable range', 'All candidate families evaluated without bias'],
    decisionExplanation: 'Fairness audit passed with parity score 0.91 (threshold: 0.80). No demographic skew detected across race, ethnicity, or socioeconomic status.',
  },
  {
    id: 'recommendation',
    stage: 'recommendation_generated',
    label: 'Recommendation Generated',
    status: 'pending',
    agentName: 'Approval Agent',
    agentAction: 'Generated placement recommendation',
    agentOutput: 'Johnson Family selected (Score: 30%)',
    latency: 0.35,
    confidenceScore: 78,
    reasoning: ['Johnson Family ranked #1 across all dimensions', 'Trauma-informed care certification verified', 'Home study completed and passed', 'References from previous placement positive'],
    decisionExplanation: 'The Johnson Family presents optimal match based on multi-agent evaluation across safety, capacity, and compatibility dimensions.',
  },
  {
    id: 'supervisor-approval',
    stage: 'supervisor_approval',
    label: 'Supervisor Approval Requested',
    status: 'pending',
    agentName: 'Approval Agent',
    agentAction: 'Escalated for review',
    agentOutput: 'Pending supervisor decision',
    latency: 0.28,
    confidenceScore: 85,
    reasoning: ['All automated checks passed', 'Human-in-the-loop review required per policy', 'Supervisor notified via dashboard'],
    logs: ['[Approval] Escalating to supervisor...', '[Approval] All criteria validated', '[Approval] Awaiting human decision'],
  },
  {
    id: 'placement-created',
    stage: 'placement_created',
    label: 'Placement Approved',
    status: 'pending',
    agentName: 'Monitoring Agent',
    agentAction: 'Created placement record',
    agentOutput: 'Placement #PL-0842 active',
    latency: 0.31,
    confidenceScore: 93,
    reasoning: ['Placement record created in state database', '21-day adjustment tracking initiated', 'Automated check-in schedule configured'],
  },
  {
    id: 'monitoring',
    stage: 'monitoring_active',
    label: 'Monitoring Active',
    status: 'pending',
    agentName: 'Monitoring Agent',
    agentAction: 'Activated monitoring',
    agentOutput: 'Monitoring schedule: Weekly check-ins',
    latency: 0.15,
    confidenceScore: 97,
    reasoning: ['Monitoring plan configured for 90-day initial period', 'Crisis alert thresholds set', 'Placement stability tracking initiated'],
  },
]

export const MOCK_REASONING_ENTRIES: ReasoningEntry[] = [
  { id: 'r1', timestamp: new Date(Date.now() - 61000).toISOString(), agentName: 'Intake Agent', content: 'Processing emergency referral for child age 8, female, West District. Validating required documentation.' },
  { id: 'r2', timestamp: new Date(Date.now() - 58000).toISOString(), agentName: 'Intake Agent', content: 'Eligibility confirmed. All intake criteria satisfied. Priority score: 92. Routing to planner.' },
  { id: 'r3', timestamp: new Date(Date.now() - 53000).toISOString(), agentName: 'Planner Agent', content: 'Creating execution strategy. Key needs identified: trauma-informed care, school continuity, Spanish language support.' },
  { id: 'r4', timestamp: new Date(Date.now() - 48000).toISOString(), agentName: 'Planner Agent', content: 'Strategy finalized. Spawning parallel agents: Risk Assessment, Family Matching, Fairness Validation.' },
  { id: 'r5', timestamp: new Date(Date.now() - 45000).toISOString(), agentName: 'Risk Agent', content: 'Analyzing case history. Moderate trauma indicators detected but no active safety concerns. Low risk profile.' },
  { id: 'r6', timestamp: new Date(Date.now() - 42000).toISOString(), agentName: 'Risk Agent', content: 'Risk score calculated: 45/100. Recommendation: trauma-informed caregiver matching.' },
  { id: 'r7', timestamp: new Date(Date.now() - 38000).toISOString(), agentName: 'Matching Agent', content: 'Querying family database with criteria: trauma-informed, Spanish bilingual, West District, capacity available.' },
  { id: 'r8', timestamp: new Date(Date.now() - 35000).toISOString(), agentName: 'Matching Agent', content: '3 candidate families identified. Evaluating compatibility scores across 12 dimensions.' },
  { id: 'r9', timestamp: new Date(Date.now() - 32000).toISOString(), agentName: 'Matching Agent', content: 'Johnson Family ranked #1: 30% match score. Trauma-informed certified, Spanish speaking, 3.2 miles from school.' },
  { id: 'r10', timestamp: new Date(Date.now() - 29000).toISOString(), agentName: 'Fairness Agent', content: 'Running bias audit across all candidate matches. Checking demographic parity and equal opportunity metrics.' },
  { id: 'r11', timestamp: new Date(Date.now() - 26000).toISOString(), agentName: 'Fairness Agent', content: 'Bias audit passed. Parity score: 0.91. No protected group disparity detected.' },
  { id: 'r12', timestamp: new Date(Date.now() - 22000).toISOString(), agentName: 'Approval Agent', content: 'Aggregating all agent outputs. Risk: 45/100, Match: Johnson 30%, Fairness: 0.91. Generating recommendation.' },
  { id: 'r13', timestamp: new Date(Date.now() - 18000).toISOString(), agentName: 'Approval Agent', content: 'Recommendation: The Johnson Family. Escalating for supervisor review per policy requirements.' },
  { id: 'r14', timestamp: new Date(Date.now() - 5000).toISOString(), agentName: 'Monitoring Agent', content: 'Placement approved. Creating monitoring schedule: weekly check-ins for 90-day initial period.' },
]
