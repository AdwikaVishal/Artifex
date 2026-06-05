import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { DashboardLayout } from '@/layouts/dashboard-layout'
import { ErrorBoundary } from '@/components/error-boundary'
import { AuthProvider } from '@/contexts/AuthContext'
import DashboardPage from '@/pages/dashboard'
import ReferralPage from '@/pages/referral'
import WorkflowTrackingPage from '@/pages/workflow-tracking'
import ApprovalsPage from '@/pages/approvals'
import PlacementsPage from '@/pages/placements'
import FamiliesPage from '@/pages/families'
import ChatPage from '@/pages/chat'
import MonitoringPage from '@/pages/monitoring'
import FairnessPage from '@/pages/fairness'
import ChildrenPage from '@/pages/children'
import MlAuditPage from '@/pages/ml-audit'
import TwinPage from '@/pages/twin'
import AgentOrchestrationPage from '@/pages/agent-orchestration'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 5000,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ReactQueryDevtools initialIsOpen={false} />
      <AuthProvider>
        <ErrorBoundary>
          <BrowserRouter>
            <Routes>
              <Route element={<DashboardLayout />}>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/referral" element={<ReferralPage />} />
                <Route path="/workflow" element={<WorkflowTrackingPage />} />
                <Route path="/workflow/:workflowId" element={<WorkflowTrackingPage />} />
                <Route path="/approvals" element={<ApprovalsPage />} />
                <Route path="/placements" element={<PlacementsPage />} />
                <Route path="/families" element={<FamiliesPage />} />
                <Route path="/children" element={<ChildrenPage />} />
                <Route path="/fairness" element={<FairnessPage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/monitoring" element={<MonitoringPage />} />
                <Route path="/ml-audit" element={<MlAuditPage />} />
                <Route path="/twin" element={<TwinPage />} />
                <Route path="/twin/:childId" element={<TwinPage />} />
                <Route path="/orchestration" element={<AgentOrchestrationPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </ErrorBoundary>
      </AuthProvider>
    </QueryClientProvider>
  )
}
