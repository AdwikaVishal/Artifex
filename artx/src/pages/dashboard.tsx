import { useDashboardMetrics, useRiskDistribution, useDashboardEvents, useAgentStatuses } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle, GlassCardValue } from '@/components/ui/glass-card'
import { DataLoader } from '@/components/data-loader'
import { StatusBadge, EmergencyBadge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { formatDate } from '@/lib/utils'
import { motion } from 'framer-motion'
import { Activity, CheckCircle, Home, AlertTriangle, TrendingUp, TrendingDown, ArrowRight, Bot } from 'lucide-react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, PieChart, Pie,
} from 'recharts'

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.08 },
  },
}

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4 } },
}

function MetricCard({ icon: Icon, label, value, change, color }: {
  icon: React.ElementType
  label: string
  value: number | string
  change?: number
  color: string
}) {
  const isPositive = change !== undefined && change >= 0
  return (
    <motion.div variants={item}>
      <GlassCard hover>
        <div className="flex items-start justify-between">
          <div className={cn('w-10 h-10 rounded-lg flex items-center justify-center', color)}>
            <Icon size={20} />
          </div>
          {change !== undefined && (
            <span className={cn(
              'flex items-center gap-0.5 text-xs font-medium',
              isPositive ? 'text-success' : 'text-destructive'
            )}>
              {isPositive ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {Math.abs(change)}%
            </span>
          )}
        </div>
        <GlassCardValue className="mt-3">{value}</GlassCardValue>
        <GlassCardTitle className="mt-0.5">{label}</GlassCardTitle>
      </GlassCard>
    </motion.div>
  )
}

function RiskPieChart({ data }: { data: { low: number; medium: number; high: number; critical: number } }) {
  const chartData = [
    { name: 'Low', value: data.low, color: '#10b981' },
    { name: 'Medium', value: data.medium, color: '#f59e0b' },
    { name: 'High', value: data.high, color: '#f97316' },
    { name: 'Critical', value: data.critical, color: '#dc2626' },
  ]

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={80}
            paddingAngle={4}
            dataKey="value"
          >
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={entry.color} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              background: '#1a1a24',
              border: '1px solid #2a2a3d',
              borderRadius: '8px',
              fontSize: '12px',
            }}
            labelStyle={{ color: '#e8e8f0' }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-2">
        {chartData.map((entry) => (
          <div key={entry.name} className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="text-xs text-muted-foreground">{entry.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function AgentMonitor() {
  const { data: agents, isLoading, error } = useAgentStatuses()

  return (
    <DataLoader isLoading={isLoading} error={error} type="card" rows={1}>
      <div className="space-y-2">
        {agents?.map((agent) => (
          <div key={agent.name} className="flex items-center justify-between py-2 px-3 rounded-lg bg-glass">
            <div className="flex items-center gap-3 min-w-0">
              <div className={`status-dot status-dot--${agent.status === 'active' ? 'active' : agent.status === 'busy' ? 'warning' : agent.status === 'error' ? 'error' : 'inactive'}`} />
              <div className="min-w-0">
                <p className="text-sm text-foreground truncate">{agent.name}</p>
                <p className="text-xs text-muted-foreground truncate">{agent.task}</p>
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span className="text-xs text-muted-foreground font-mono">{agent.workflows_processed}</span>
              <StatusBadge status={agent.status} />
            </div>
          </div>
        ))}
      </div>
    </DataLoader>
  )
}

function EventFeed() {
  const { data: events, isLoading, error } = useDashboardEvents()

  return (
    <DataLoader isLoading={isLoading} error={error} type="card" rows={1}>
      <div className="space-y-1 max-h-[320px] overflow-y-auto">
        {events?.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-8">No recent events</p>
        )}
        {events?.map((event) => (
          <div key={event.id} className="flex items-start gap-3 py-2.5 px-2 rounded-lg hover:bg-glass transition-colors">
            <div className="flex flex-col items-center">
              <div className={`w-2 h-2 rounded-full mt-1.5 ${
                event.type === 'placement' ? 'bg-success' :
                event.type === 'alert' ? 'bg-destructive' :
                event.type === 'approval' ? 'bg-warning' : 'bg-info'
              }`} />
              <div className="w-px flex-1 bg-border mt-1" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono text-muted-foreground">{event.workflow_id}</span>
                <span className="text-[10px] text-muted-foreground">{formatDate(event.timestamp)}</span>
              </div>
              <p className="text-sm text-foreground mt-0.5">{event.message}</p>
            </div>
          </div>
        ))}
      </div>
    </DataLoader>
  )
}

function WorkflowActivityChart() {
  const data = [
    { name: 'Mon', submitted: 4, matched: 2, approved: 1 },
    { name: 'Tue', submitted: 6, matched: 3, approved: 2 },
    { name: 'Wed', submitted: 3, matched: 5, approved: 3 },
    { name: 'Thu', submitted: 7, matched: 4, approved: 2 },
    { name: 'Fri', submitted: 5, matched: 6, approved: 4 },
    { name: 'Sat', submitted: 2, matched: 2, approved: 1 },
    { name: 'Sun', submitted: 3, matched: 3, approved: 2 },
  ]

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="submitted" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="matched" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="approved" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} />
          <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} />
          <Tooltip
            contentStyle={{
              background: '#1a1a24',
              border: '1px solid #2a2a3d',
              borderRadius: '8px',
              fontSize: '12px',
            }}
            labelStyle={{ color: '#e8e8f0' }}
          />
          <Area type="monotone" dataKey="submitted" stroke="#6366f1" fill="url(#submitted)" strokeWidth={2} />
          <Area type="monotone" dataKey="matched" stroke="#06b6d4" fill="url(#matched)" strokeWidth={2} />
          <Area type="monotone" dataKey="approved" stroke="#10b981" fill="url(#approved)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

import { cn } from '@/lib/utils'

export default function DashboardPage() {
  const { data: metrics, isLoading: mLoading, error: mError } = useDashboardMetrics()
  const { data: riskData, isLoading: rLoading, error: rError } = useRiskDistribution()

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="space-y-6">
      <motion.div variants={item}>
        <div className="flex items-center justify-between mb-1">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Dashboard</h1>
            <p className="text-sm text-muted-foreground mt-1">AI foster care orchestration overview</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="status-dot status-dot--active" />
            <span className="text-xs text-muted-foreground">System Online</span>
          </div>
        </div>
      </motion.div>

      <DataLoader isLoading={mLoading} error={mError} type="card" rows={4}>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <MetricCard
            icon={Activity}
            label="Active Workflows"
            value={metrics?.active_workflows ?? 0}
            change={metrics?.workflows_change}
            color="bg-primary/15 text-primary"
          />
          <MetricCard
            icon={CheckCircle}
            label="Pending Approvals"
            value={metrics?.pending_approvals ?? 0}
            change={metrics?.approvals_change}
            color="bg-warning/15 text-warning"
          />
          <MetricCard
            icon={Home}
            label="Placements Matched"
            value={metrics?.placements_matched ?? 0}
            change={metrics?.placements_change}
            color="bg-success/15 text-success"
          />
          <MetricCard
            icon={AlertTriangle}
            label="Emergency Referrals"
            value={metrics?.emergency_referrals ?? 0}
            change={metrics?.emergency_change}
            color="bg-destructive/15 text-destructive"
          />
        </div>
      </DataLoader>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div variants={item} className="lg:col-span-2">
          <GlassCard>
            <GlassCardHeader>
              <GlassCardTitle>Workflow Activity</GlassCardTitle>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-primary" />
                  <span className="text-xs text-muted-foreground">Submitted</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-secondary" />
                  <span className="text-xs text-muted-foreground">Matched</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full bg-success" />
                  <span className="text-xs text-muted-foreground">Approved</span>
                </div>
              </div>
            </GlassCardHeader>
            <WorkflowActivityChart />
          </GlassCard>
        </motion.div>

        <motion.div variants={item}>
          <GlassCard>
            <GlassCardHeader>
              <GlassCardTitle>Risk Distribution</GlassCardTitle>
            </GlassCardHeader>
            <DataLoader isLoading={rLoading} error={rError} type="chart">
              <RiskPieChart data={riskData ?? { low: 0, medium: 0, high: 0, critical: 0 }} />
            </DataLoader>
          </GlassCard>
        </motion.div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div variants={item} className="lg:col-span-2">
          <GlassCard>
            <GlassCardHeader>
              <GlassCardTitle>Agent Heartbeat Monitor</GlassCardTitle>
              <Bot size={16} className="text-muted-foreground" />
            </GlassCardHeader>
            <AgentMonitor />
          </GlassCard>
        </motion.div>

        <motion.div variants={item}>
          <GlassCard>
            <GlassCardHeader>
              <GlassCardTitle>Live Event Feed</GlassCardTitle>
              <Activity size={16} className="text-muted-foreground" />
            </GlassCardHeader>
            <EventFeed />
          </GlassCard>
        </motion.div>
      </div>
    </motion.div>
  )
}
