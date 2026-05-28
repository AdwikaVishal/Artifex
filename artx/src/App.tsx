import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'
import { DashboardLayout } from '@/layouts/dashboard-layout'
import { ErrorBoundary } from '@/components/error-boundary'
import DashboardPage from '@/pages/dashboard'
import ReferralPage from '@/pages/referral'
import WorkflowTrackingPage from '@/pages/workflow-tracking'
import ApprovalsPage from '@/pages/approvals'
import PlacementsPage from '@/pages/placements'
import ChatPage from '@/pages/chat'
import MonitoringPage from '@/pages/monitoring'

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
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/monitoring" element={<MonitoringPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ErrorBoundary>
    </QueryClientProvider>
  )
}
