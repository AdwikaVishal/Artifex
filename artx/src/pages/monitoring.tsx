import { useAgentStatuses, useHealth, useDashboardMetrics, useWorkflowActivity } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { StatusBadge } from '@/components/ui/badge'
import { DataLoader } from '@/components/data-loader'
import { motion } from 'framer-motion'
import {
  Activity, Database, Bot, Radio, Network, BarChart3, RefreshCw, 
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar, Cell,
} from 'recharts'
import { useQueryClient } from '@tanstack/react-query'

function ServiceCard({ name, icon: Icon, status, latency }: { name: string; icon: React.ElementType; status: string; latency?: number }) {
  return (
    <GlassCard hover>
      <div className="flex items-center gap-3">
        <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
          status === 'healthy' || status === 'connected' ? 'bg-success/15' :
          status === 'degraded' ? 'bg-warning/15' : 'bg-destructive/15'
        }`}>
          <Icon size={20} className={
            status === 'healthy' || status === 'connected' ? 'text-success' :
            status === 'degraded' ? 'text-warning' : 'text-destructive'
          } />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground">{name}</p>
          {latency !== undefined && (
            <p className="text-xs text-muted-foreground font-mono">{latency}ms latency</p>
          )}
        </div>
        <StatusBadge status={status} />
      </div>
    </GlassCard>
  )
}

export default function MonitoringPage() {
  const { data: agentMap, isLoading: agentsLoading, error: agentsError, refetch: refetchAgents } = useAgentStatuses()
  const { data: health, isLoading: healthLoading, error: healthError, refetch: refetchHealth } = useHealth()
  const { data: metrics } = useDashboardMetrics()
  const { data: activity } = useWorkflowActivity()
  const queryClient = useQueryClient()
  const agents = agentMap?.agents ? Object.values(agentMap.agents) : []

  const handleRefresh = () => {
    refetchAgents()
    refetchHealth()
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  // Build latency chart data from health check
  const latencyData = [
    { name: 'PostgreSQL', latency: health?.services?.postgres?.latency_ms ?? 0, color: '#10b981' },
    { name: 'NATS', latency: health?.services?.nats?.latency_ms ?? 0, color: '#06b6d4' },
    { name: 'Temporal', latency: health?.services?.temporal?.latency_ms ?? 0, color: '#6366f1' },
  ].filter(d => d.latency > 0)

  // Build throughput data from workflow activity
  const throughputData = activity && activity.length > 0
    ? activity.map(a => ({ name: a.name, events: a.submitted + a.matched + a.approved }))
    : [{ name: 'No data', events: 0 }]

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">System Monitoring</h1>
          <p className="text-sm text-muted-foreground mt-1">Real-time infrastructure and agent monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className={`status-dot ${health?.status === 'ok' ? 'status-dot--active' : 'status-dot--warning'}`} />
            <span className="text-xs text-muted-foreground">{health?.status === 'ok' ? 'All Systems' : 'Degraded'}</span>
          </div>
          <span className="text-muted">|</span>
          <span className="text-xs text-muted-foreground font-mono">{metrics?.active_workflows ?? 0} active workflows</span>
          <Button variant="ghost" size="sm" onClick={handleRefresh}>
            <RefreshCw size={14} />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <GlassCard>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-success/15 flex items-center justify-center">
              <Database size={20} className="text-success" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">PostgreSQL</p>
              <StatusBadge status={health?.services?.postgres?.status || 'healthy'} />
            </div>
          </div>
          {health?.services?.postgres?.latency_ms !== undefined && (
            <p className="text-xs text-muted-foreground font-mono">{health.services.postgres.latency_ms}ms latency</p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-info/15 flex items-center justify-center">
              <Radio size={20} className="text-info" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">NATS</p>
              <StatusBadge status={health?.services?.nats?.status || 'connected'} />
            </div>
          </div>
          {health?.services?.nats?.latency_ms !== undefined && (
            <p className="text-xs text-muted-foreground font-mono">{health.services.nats.latency_ms}ms latency</p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-accent/15 flex items-center justify-center">
              <Network size={20} className="text-accent" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Temporal</p>
              <StatusBadge status={health?.services?.temporal?.status || 'connected'} />
            </div>
          </div>
          {health?.services?.temporal?.latency_ms !== undefined && (
            <p className="text-xs text-muted-foreground font-mono">{health.services.temporal.latency_ms}ms latency</p>
          )}
        </GlassCard>

        <GlassCard>
          <div className="flex items-center gap-3 mb-3">
            <div className="w-10 h-10 rounded-lg bg-primary/15 flex items-center justify-center">
              <Bot size={20} className="text-primary" />
            </div>
            <div>
              <p className="text-xs text-muted-foreground">AI Agents</p>
              <StatusBadge status={agents.length > 0 && agents.every((a: any) => a.status === 'healthy') ? 'healthy' : 'degraded'} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground font-mono">{agents.filter((a: any) => a.status === 'healthy').length ?? 0}/{agents.length ?? 0} active</p>
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GlassCard>
          <GlassCardHeader>
            <GlassCardTitle>Event Throughput (7 days)</GlassCardTitle>
            <BarChart3 size={16} className="text-muted-foreground" />
          </GlassCardHeader>
          <div className="h-48" style={{ minHeight: 192 }}>
            <ResponsiveContainer width="100%" height="100%" minHeight={192}>
              <BarChart data={throughputData}>
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: '#1a1a24', border: '1px solid #2a2a3d', borderRadius: '8px', fontSize: '12px' }}
                  labelStyle={{ color: '#e8e8f0' }}
                />
                <Bar dataKey="events" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        <GlassCard>
          <GlassCardHeader>
            <GlassCardTitle>Service Latency (ms)</GlassCardTitle>
            <Activity size={16} className="text-muted-foreground" />
          </GlassCardHeader>
          <div className="h-48" style={{ minHeight: 192 }}>
            {latencyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%" minHeight={192}>
                <BarChart data={latencyData} layout="vertical">
                  <XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 11 }} width={80} />
                  <Tooltip
                    contentStyle={{ background: '#1a1a24', border: '1px solid #2a2a3d', borderRadius: '8px', fontSize: '12px' }}
                    formatter={(v: any) => [`${v ?? 0}ms`, 'Latency']}
                  />
                  <Bar dataKey="latency" radius={[0, 4, 4, 0]}>
                    {latencyData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center">
                <p className="text-sm text-muted-foreground">Waiting for health data…</p>
              </div>
            )}
          </div>
        </GlassCard>
      </div>

      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>AI Agent Status</GlassCardTitle>
          <Button variant="ghost" size="sm" onClick={handleRefresh}>
            <RefreshCw size={14} />
          </Button>
        </GlassCardHeader>
        <DataLoader isLoading={agentsLoading} error={agentsError} type="table" rows={3}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left py-3 px-2 text-xs text-muted-foreground font-medium uppercase tracking-wider">Agent</th>
                  <th className="text-left py-3 px-2 text-xs text-muted-foreground font-medium uppercase tracking-wider">Status</th>
                  <th className="text-left py-3 px-2 text-xs text-muted-foreground font-medium uppercase tracking-wider">Current Task</th>
                  <th className="text-right py-3 px-2 text-xs text-muted-foreground font-medium uppercase tracking-wider">Workflows</th>
                  <th className="text-right py-3 px-2 text-xs text-muted-foreground font-medium uppercase tracking-wider">Last Heartbeat</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent: any) => (
                  <tr key={agent.name} className="border-b border-border hover:bg-glass transition-colors">
                    <td className="py-3 px-2">
                      <div className="flex items-center gap-2">
                        <Bot size={14} className="text-muted-foreground" />
                        <span className="text-foreground font-medium">{agent.name}</span>
                      </div>
                    </td>
                    <td className="py-3 px-2"><StatusBadge status={agent.status === 'healthy' ? 'active' : agent.status === 'stale' ? 'busy' : 'error'} /></td>
                    <td className="py-3 px-2 text-muted-foreground max-w-[200px] truncate">-</td>
                    <td className="py-3 px-2 text-right font-mono text-foreground">-</td>
                    <td className="py-3 px-2 text-right text-muted-foreground font-mono text-xs">{agent.last_heartbeat_age_s ? `${agent.last_heartbeat_age_s}s ago` : 'N/A'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DataLoader>
      </GlassCard>
    </motion.div>
  )
}
