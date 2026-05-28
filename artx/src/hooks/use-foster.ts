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
  getMockMetrics,
  getMockRiskDistribution,
  getMockEvents,
  getMockAgentStatuses,
} from '@/services/foster'
import type { ReferralSubmission, ApproveRequest } from '@/types'

export function useDashboardMetrics() {
  return useQuery({
    queryKey: ['dashboard', 'metrics'],
    queryFn: getMockMetrics,
    refetchInterval: 15000,
  })
}

export function useRiskDistribution() {
  return useQuery({
    queryKey: ['dashboard', 'risk-distribution'],
    queryFn: getMockRiskDistribution,
    refetchInterval: 30000,
  })
}

export function useDashboardEvents() {
  return useQuery({
    queryKey: ['dashboard', 'events'],
    queryFn: getMockEvents,
    refetchInterval: 10000,
  })
}

export function useAgentStatuses() {
  return useQuery({
    queryKey: ['agents'],
    queryFn: getMockAgentStatuses,
    refetchInterval: 8000,
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

export function useChat() {
  return useMutation({
    mutationFn: ({ message, workflowId }: { message: string; workflowId?: string }) =>
      sendChatMessage(message, workflowId),
  })
}
