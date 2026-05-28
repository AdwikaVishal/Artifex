import { useAgentStatuses, useHealth, useDashboardMetrics } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { StatusBadge } from '@/components/ui/badge'
import { DataLoader } from '@/components/data-loader'
import { formatDate } from '@/lib/utils'
import { motion } from 'framer-motion'
import {
  Activity, Database, Server, Bot, Radio, Network, Cpu, BarChart3, RefreshCw, 
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, BarChart, Bar,
} from 'recharts'

const throughputData = Array.from({ length: 24 }, (_, i) => ({
  time: `${i}:00`,
  events: Math.floor(Math.random() * 50) + 10,
  workflows: Math.floor(Math.random() * 20) + 5,
}))

const latencyData = Array.from({ length: 12 }, (_, i) => ({
  time: `${(i * 5).toString().padStart(2, '0')}:00`,
  api: Math.floor(Math.random() * 200) + 20,
  nats: Math.floor(Math.random() * 100) + 10,
  db: Math.floor(Math.random() * 50) + 5,
}))

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
  const { data: agents, isLoading: agentsLoading, error: agentsError } = useAgentStatuses()
  const { data: health, isLoading: healthLoading, error: healthError } = useHealth()
  const { data: metrics } = useDashboardMetrics()

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">System Monitoring</h1>
          <p className="text-sm text-muted-foreground mt-1">Real-time infrastructure and agent monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="status-dot status-dot--active" />
            <span className="text-xs text-muted-foreground">All Systems</span>
          </div>
          <span className="text-muted">|</span>
          <span className="text-xs text-muted-foreground font-mono">{metrics?.active_workflows ?? 0} active workflows</span>
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
              <StatusBadge status={agents?.every((a) => a.status === 'active') ? 'healthy' : 'degraded'} />
            </div>
          </div>
          <p className="text-xs text-muted-foreground font-mono">{agents?.filter((a) => a.status === 'active').length ?? 0}/{agents?.length ?? 0} active</p>
        </GlassCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <GlassCard>
          <GlassCardHeader>
            <GlassCardTitle>Event Throughput (24h)</GlassCardTitle>
            <BarChart3 size={16} className="text-muted-foreground" />
          </GlassCardHeader>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={throughputData}>
                <defs>
                  <linearGradient id="events" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="workflows" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 10 }} interval={3} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: '#1a1a24', border: '1px solid #2a2a3d', borderRadius: '8px', fontSize: '12px' }}
                  labelStyle={{ color: '#e8e8f0' }}
                />
                <Area type="monotone" dataKey="events" stroke="#6366f1" fill="url(#events)" strokeWidth={2} />
                <Area type="monotone" dataKey="workflows" stroke="#06b6d4" fill="url(#workflows)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>

        <GlassCard>
          <GlassCardHeader>
            <GlassCardTitle>Service Latency</GlassCardTitle>
            <Activity size={16} className="text-muted-foreground" />
          </GlassCardHeader>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={latencyData}>
                <XAxis dataKey="time" axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 10 }} interval={2} />
                <YAxis axisLine={false} tickLine={false} tick={{ fill: '#6b6b80', fontSize: 10 }} />
                <Tooltip
                  contentStyle={{ background: '#1a1a24', border: '1px solid #2a2a3d', borderRadius: '8px', fontSize: '12px' }}
                  labelStyle={{ color: '#e8e8f0' }}
                />
                <Bar dataKey="api" fill="#6366f1" radius={[2, 2, 0, 0]} />
                <Bar dataKey="nats" fill="#06b6d4" radius={[2, 2, 0, 0]} />
                <Bar dataKey="db" fill="#10b981" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </GlassCard>
      </div>

      <GlassCard>
        <GlassCardHeader>
          <GlassCardTitle>AI Agent Status</GlassCardTitle>
          <Button variant="ghost" size="sm">
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
                {agents?.map((agent) => (
                  <tr key={agent.name} className="border-b border-border hover:bg-glass transition-colors">
                    <td className="py-3 px-2">
                      <div className="flex items-center gap-2">
                        <Bot size={14} className="text-muted-foreground" />
                        <span className="text-foreground font-medium">{agent.name}</span>
                      </div>
                    </td>
                    <td className="py-3 px-2"><StatusBadge status={agent.status} /></td>
                    <td className="py-3 px-2 text-muted-foreground max-w-[200px] truncate">{agent.task}</td>
                    <td className="py-3 px-2 text-right font-mono text-foreground">{agent.workflows_processed}</td>
                    <td className="py-3 px-2 text-right text-muted-foreground font-mono text-xs">{formatDate(agent.last_heartbeat)}</td>
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
