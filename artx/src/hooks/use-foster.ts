import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  submitReferral,
  getPendingApprovals,
  approveReferral,
  supervisorApprove,
  getPlacements,
  getWorkflowStatus,
  getHealth,
  getHealthCheck,
  sendChatMessage,
  getDashboardMetrics,
  getRiskDistribution,
  getDashboardEvents,
  getAgentStatuses,
  getFamilies,
  createFamily,
  updateFamily,
  deleteFamily,
  getWorkflowActivity,
  getCrisisPrediction,
  refreshCrisisPrediction,
  getFairnessMetrics,
  getShapExplanation,
  getChildTimeline,
} from '@/services/foster'
import type { ReferralSubmission, ApproveRequest, FamilyCreate, FamilyUpdate } from '@/types'

export function useDashboardMetrics() {
  return useQuery({
    queryKey: ['dashboard', 'metrics'],
    queryFn: getDashboardMetrics,
    refetchInterval: 15000,
  })
}

export function useRiskDistribution() {
  return useQuery({
    queryKey: ['dashboard', 'risk-distribution'],
    queryFn: getRiskDistribution,
    refetchInterval: 30000,
  })
}

export function useDashboardEvents() {
  return useQuery({
    queryKey: ['dashboard', 'events'],
    queryFn: getDashboardEvents,
    refetchInterval: 10000,
  })
}

export function useAgentStatuses() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: getAgentStatuses,
    refetchInterval: 8000,
  })
}

export function useWorkflowActivity() {
  return useQuery({
    queryKey: ['dashboard', 'workflow-activity'],
    queryFn: getWorkflowActivity,
    refetchInterval: 60000,
  })
}

export function useSubmitReferral() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ReferralSubmission) => submitReferral(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
}

export function usePendingApprovals() {
  return useQuery({
    queryKey: ['approvals'],
    queryFn: getPendingApprovals,
    refetchInterval: 10000,
    retry: 2,
    retryDelay: 1000,
  })
}

export function useApproveReferral() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ApproveRequest) => approveReferral(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['placements'] })
      queryClient.invalidateQueries({ queryKey: ['families'] })
    },
  })
}

export function useSupervisorApprove() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: ApproveRequest) => supervisorApprove(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      queryClient.invalidateQueries({ queryKey: ['placements'] })
      queryClient.invalidateQueries({ queryKey: ['families'] })
    },
  })
}

export function usePlacements() {
  return useQuery({
    queryKey: ['placements'],
    queryFn: getPlacements,
    refetchInterval: 20000,
    retry: 2,
    retryDelay: 1000,
  })
}

export function useWorkflowStatus(workflowId: string | null) {
  return useQuery({
    queryKey: ['workflow', workflowId],
    queryFn: () => getWorkflowStatus(workflowId!),
    enabled: !!workflowId && workflowId.trim().length > 0,
    refetchInterval: 5000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10000),
  })
}

export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 10000,
    retry: 2,
  })
}

export function useHealthCheck() {
  return useQuery({
    queryKey: ['health-check'],
    queryFn: getHealthCheck,
    refetchInterval: 10000,
    retry: false,
    staleTime: 5000,
  })
}

export interface MlInsights {
  avg_match_score: number
  avg_confidence_score: number
  avg_risk_score: number
  total_placements: number
  high_risk_count: number
  top_features: Array<{ feature: string; importance: number }>
  low_match_count: number
  high_match_count: number
  avg_alternatives_count: number
  avg_runner_up_score: number
}

export function useMlInsights() {
  const { data: placements } = usePlacements()
  return useQuery({
    queryKey: ['ml-insights', placements],
    queryFn: (): MlInsights => {
      const all = placements || []
      const withMatch = all.filter((p) => p.match_score != null)
      const withRisk = all.filter((p) => p.risk_score != null)
      const withConfidence = all.filter((p) => p.confidence_score != null)
      const withFeatures = all.filter((p) => p.feature_importance && p.feature_importance.length > 0)

      const avgMatch = withMatch.length
        ? withMatch.reduce((s, p) => s + (p.match_score ?? 0), 0) / withMatch.length
        : 0
      const avgConfidence = withConfidence.length
        ? withConfidence.reduce((s, p) => s + (p.confidence_score ?? 0), 0) / withConfidence.length
        : 0
      const avgRisk = withRisk.length
        ? withRisk.reduce((s, p) => s + (p.risk_score ?? 0), 0) / withRisk.length
        : 0

      // Aggregate feature importance across all placements that have it
      const featureMap = new Map<string, { total: number; count: number }>()
      for (const p of withFeatures) {
        for (const fi of (p.feature_importance || [])) {
          const entry = featureMap.get(fi.feature) || { total: 0, count: 0 }
          entry.total += fi.importance
          entry.count += 1
          featureMap.set(fi.feature, entry)
        }
      }
      const topFeatures = [...featureMap.entries()]
        .map(([feature, { total, count }]) => ({ feature, importance: parseFloat((total / count).toFixed(4)) }))
        .sort((a, b) => b.importance - a.importance)
        .slice(0, 5)

      // Aggregate top_matches across placements
      const withAlternatives = all.filter((p) => p.top_matches && p.top_matches.length > 1)
      const runnerUpScores: number[] = []
      for (const p of withAlternatives) {
        const runnerUp = (p.top_matches ?? [])[1]
        if (runnerUp) {
          const score = (runnerUp as any).blended_score ?? (runnerUp as any).match_score ?? 0
          runnerUpScores.push(score)
        }
      }
      const avgRunnerUp = runnerUpScores.length
        ? runnerUpScores.reduce((s, v) => s + v, 0) / runnerUpScores.length
        : 0

      return {
        avg_match_score: parseFloat(avgMatch.toFixed(1)),
        avg_confidence_score: parseFloat(avgConfidence.toFixed(3)),
        avg_risk_score: parseFloat(avgRisk.toFixed(1)),
        total_placements: all.length,
        high_risk_count: withRisk.filter((p) => (p.risk_score ?? 0) >= 7).length,
        low_match_count: withMatch.filter((p) => (p.match_score ?? 0) < 60).length,
        high_match_count: withMatch.filter((p) => (p.match_score ?? 0) >= 85).length,
        top_features: topFeatures,
        avg_alternatives_count: withAlternatives.length
          ? parseFloat((withAlternatives.reduce((s, p) => s + ((p.top_matches?.length ?? 1) - 1), 0) / withAlternatives.length).toFixed(1))
          : 0,
        avg_runner_up_score: parseFloat(avgRunnerUp.toFixed(1)),
      }
    },
    enabled: !!placements,
  })
}

// ── Families hooks ───────────────────────────────────────────────────────

export function useFamilies() {
  return useQuery({
    queryKey: ['families'],
    queryFn: () => getFamilies(),
    refetchInterval: 30000,
  })
}

export function useCreateFamily() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: FamilyCreate) => createFamily(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['families'] })
    },
  })
}

export function useUpdateFamily() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ familyId, data }: { familyId: string; data: FamilyUpdate }) =>
      updateFamily(familyId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['families'] })
    },
  })
}

export function useDeleteFamily() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (familyId: string) => deleteFamily(familyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['families'] })
    },
  })
}

export function useChat() {
  return useMutation({
    mutationFn: ({ message, workflowId }: { message: string; workflowId?: string }) =>
      sendChatMessage(message, workflowId),
  })
}

// ── Crisis Prediction hooks ───────────────────────────────────────────────

export function useCrisisPrediction(placementId: string | null) {
  return useQuery({
    queryKey: ['crisis-prediction', placementId],
    queryFn: () => getCrisisPrediction(placementId!),
    enabled: !!placementId,
    staleTime: 1000 * 60 * 60, // 1 hour – predictions are cached 24h server-side
    retry: 1,
  })
}

export function useRefreshCrisisPrediction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (placementId: string) => refreshCrisisPrediction(placementId),
    onSuccess: (_data, placementId) => {
      queryClient.invalidateQueries({ queryKey: ['crisis-prediction', placementId] })
    },
  })
}

// ── Fairness hooks ────────────────────────────────────────────────────────

export function useFairnessMetrics() {
  return useQuery({
    queryKey: ['fairness', 'metrics'],
    queryFn: getFairnessMetrics,
    staleTime: 1000 * 60 * 5, // 5 minutes
    retry: 1,
  })
}

export function useShapExplanation(workflowId: string | null) {
  return useQuery({
    queryKey: ['fairness', 'shap', workflowId],
    queryFn: () => getShapExplanation(workflowId!),
    enabled: !!workflowId,
    staleTime: 1000 * 60 * 10,
    retry: 1,
  })
}

// ── Child Timeline hook ───────────────────────────────────────────────────

export function useChildTimeline(childId: string | null) {
  return useQuery({
    queryKey: ['child-timeline', childId],
    queryFn: () => getChildTimeline(childId!),
    enabled: !!childId,
    staleTime: 1000 * 60 * 2, // 2 minutes
    retry: 1,
  })
}
