import { useState } from 'react'
import { usePendingApprovals, useApproveReferral, useSupervisorApprove } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Button } from '@/components/ui/button'
import { StatusBadge, EmergencyBadge } from '@/components/ui/badge'
import { Modal } from '@/components/ui/modal'
import { DataLoader } from '@/components/data-loader'
import { TextArea } from '@/components/ui/input'
import { toast } from '@/components/ui/toast'
import { motion } from 'framer-motion'
import { CheckCircle, Shield, ExternalLink } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

export default function ApprovalsPage() {
  const navigate = useNavigate()
  const { data: approvals, isLoading, error, refetch } = usePendingApprovals()
  const approveMutation = useApproveReferral()
  const supervisorMutation = useSupervisorApprove()

  const [selectedApproval, setSelectedApproval] = useState<{ workflow_id: string; type: 'approve' | 'supervisor' } | null>(null)
  const [approveNotes, setApproveNotes] = useState('')

  const handleApprove = async () => {
    if (!selectedApproval) return
    try {
      if (selectedApproval.type === 'supervisor') {
        await supervisorMutation.mutateAsync({
          workflow_id: selectedApproval.workflow_id,
          approved: true,
          comment: approveNotes || '',
        })
        toast({ title: 'Supervisor Approved', description: `Workflow ${selectedApproval.workflow_id} approved`, variant: 'success' })
      } else {
        await approveMutation.mutateAsync({
          workflow_id: selectedApproval.workflow_id,
          approved: true,
          comment: approveNotes || '',
        })
        toast({ title: 'Approved', description: `Workflow ${selectedApproval.workflow_id} approved`, variant: 'success' })
      }
      setSelectedApproval(null)
      setApproveNotes('')
    } catch (err) {
      console.error('[approvals] approval error:', err)
      const axiosErr = err as { response?: { data?: { detail?: unknown } } } | undefined
      console.error('[approvals] response data:', axiosErr?.response?.data)
      const responseData = axiosErr?.response?.data
      const detail = responseData?.detail
      const message = Array.isArray(detail)
        ? (detail as Array<{ msg?: string }>).map((d) => d.msg).join('; ')
        : detail || (err as Error)?.message || 'Approval failed'
      toast({ title: 'Approval Failed', description: String(message), variant: 'error' })
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Pending Approvals</h1>
          <p className="text-sm text-muted-foreground mt-1">Review and approve foster care referrals</p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => refetch()}>
          Refresh
        </Button>
      </div>

      <DataLoader isLoading={isLoading} error={error} type="table" rows={5}>
        {approvals && approvals.length > 0 ? (
          <div className="space-y-3">
            {approvals.map((approval, i) => (
              <motion.div
                key={approval.workflow_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <GlassCard hover>
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2">
                        <span className="text-sm font-mono text-foreground">{approval?.workflow_id || '—'}</span>
                        <EmergencyBadge level={approval?.emergency_level} />
                        <StatusBadge status={approval?.status} />
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
                        <div>
                          <span className="text-xs text-muted-foreground block">Child</span>
                          <span className="text-foreground font-medium">{approval?.child_id || '—'}</span>
                        </div>
                        <div>
                          <span className="text-xs text-muted-foreground block">Risk Score</span>
                          <span className={`font-mono font-medium ${
                            (approval?.risk_score ?? 0) >= 7 ? 'text-destructive' :
                            (approval?.risk_score ?? 0) >= 4 ? 'text-warning' : 'text-success'
                          }`}>
                            {approval?.risk_score ?? '—'}/10
                          </span>
                        </div>
                        <div className="col-span-2">
                          <span className="text-xs text-muted-foreground block">Recommended Family</span>
                          <span className="text-foreground">{approval?.recommended_family || 'Pending'}</span>
                        </div>
                      </div>
                    </div>
                    <div className="flex flex-col gap-2 shrink-0">
                      <Button
                        size="sm"
                        variant="success"
                        onClick={() => setSelectedApproval({ workflow_id: approval?.workflow_id || '', type: 'approve' })}
                      >
                        <CheckCircle size={14} />
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="warning"
                        onClick={() => setSelectedApproval({ workflow_id: approval?.workflow_id || '', type: 'supervisor' })}
                      >
                        <Shield size={14} />
                        Supervisor
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => navigate(`/workflow/${approval.workflow_id}`)}
                      >
                        <ExternalLink size={14} />
                        View
                      </Button>
                    </div>
                  </div>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        ) : (
          <GlassCard>
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CheckCircle size={40} className="text-success mb-3" />
              <h3 className="text-lg font-semibold text-foreground mb-1">All Caught Up</h3>
              <p className="text-sm text-muted-foreground">No pending approvals at this time</p>
            </div>
          </GlassCard>
        )}
      </DataLoader>

      <Modal
        open={!!selectedApproval}
        onClose={() => setSelectedApproval(null)}
        title={selectedApproval?.type === 'supervisor' ? 'Supervisor Approval' : 'Approve Referral'}
        description={`Confirm approval for workflow ${selectedApproval?.workflow_id}`}
      >
        <div className="space-y-4">
          <TextArea
            id="approve-notes"
            label="Approval Notes (optional)"
            placeholder="Add any notes or conditions..."
            value={approveNotes}
            onChange={(e) => setApproveNotes(e.target.value)}
          />
          <div className="flex gap-3 justify-end">
            <Button variant="secondary" onClick={() => setSelectedApproval(null)}>
              Cancel
            </Button>
            <Button
              variant={selectedApproval?.type === 'supervisor' ? 'warning' : 'success'}
              onClick={handleApprove}
              loading={approveMutation.isPending || supervisorMutation.isPending}
            >
              {selectedApproval?.type === 'supervisor' ? (
                <><Shield size={16} /> Confirm Supervisor Approval</>
              ) : (
                <><CheckCircle size={16} /> Confirm Approval</>
              )}
            </Button>
          </div>
        </div>
      </Modal>
    </motion.div>
  )
}
