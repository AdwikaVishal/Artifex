import { useState, useMemo } from 'react'
import { usePlacements } from '@/hooks/use-foster'
import { GlassCard, GlassCardHeader, GlassCardTitle } from '@/components/ui/glass-card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { StatusBadge, EmergencyBadge } from '@/components/ui/badge'
import { DataLoader } from '@/components/data-loader'
import { formatDate, safeLowercase, safeCapitalize } from '@/lib/utils'
import { motion } from 'framer-motion'
import { Search, Home, MapPin, Users, ArrowRight, ChevronDown, ChevronUp } from 'lucide-react'
import type { TopMatch } from '@/types'
import { useNavigate } from 'react-router-dom'
import { CrisisAlertCard } from '@/components/CrisisAlertCard'

function AltMatches({ matches, index }: { matches: TopMatch[]; index: number }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="pt-1">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
      >
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        <span>Alternative Matches ({matches.length - 1})</span>
      </button>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          className="mt-2 space-y-1.5"
        >
          {matches.slice(1).map((m, mi) => {
            const fam = (m.family ?? m) as Record<string, unknown>
            const name = (fam.name ?? fam.family_name ?? `Family ${fam.family_id ?? ''}`) as string
            const score = (m.blended_score ?? m.match_score ?? 0) as number
            return (
              <div key={mi} className="flex items-center justify-between rounded-lg border border-border px-2.5 py-1.5 bg-surface/50">
                <span className="text-xs font-medium text-foreground truncate">{name}</span>
                <span className="text-xs font-mono text-primary">{score.toFixed(0)}%</span>
              </div>
            )
          })}
        </motion.div>
      )}
    </div>
  )
}

export default function PlacementsPage() {
  const navigate = useNavigate()
  const { data: placements, isLoading, error } = usePlacements()
  const [search, setSearch] = useState('')
  const [filterLevel, setFilterLevel] = useState<string>('all')

  const filtered = useMemo(() => {
    if (!placements) return []
    const searchLower = safeLowercase(search)
    return placements.filter((p) => {
      const matchSearch = !search ||
        safeLowercase(p?.child_id).includes(searchLower) ||
        safeLowercase(p?.foster_family_name).includes(searchLower) ||
        safeLowercase(p?.workflow_id).includes(searchLower)
      const matchLevel = filterLevel === 'all' || p?.emergency_level === filterLevel
      return matchSearch && matchLevel
    })
  }, [placements, search, filterLevel])

  const emergencyLevels = useMemo(() => {
    if (!placements) return ['all']
    const levels = new Set<string>()
    placements.forEach((p) => {
      if (p?.emergency_level) levels.add(p.emergency_level)
    })
    return ['all', ...Array.from(levels)]
  }, [placements])

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Placements</h1>
        <p className="text-sm text-muted-foreground mt-1">Active foster care placements and matching results</p>
      </div>

      <GlassCard>
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="flex-1">
            <Input
              placeholder="Search by child, family, or workflow ID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-2 flex-wrap">
            {emergencyLevels.map((level) => (
              <Button
                key={level}
                size="sm"
                variant={filterLevel === level ? 'default' : 'secondary'}
                onClick={() => setFilterLevel(level)}
              >
                {level === 'all' ? 'All' : safeCapitalize(level)}
              </Button>
            ))}
          </div>
        </div>
      </GlassCard>

      <DataLoader isLoading={isLoading} error={error} type="full" rows={1}>
        {filtered.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filtered.map((placement, i) => (
              <motion.div
                key={placement?.workflow_id || `placement-${i}`}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.03 }}
              >
                <GlassCard hover className="h-full flex flex-col">
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className="w-10 h-10 rounded-lg bg-accent/15 flex items-center justify-center">
                        <Home size={18} className="text-accent" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-foreground">{placement?.foster_family_name || 'Unassigned'}</p>
                        <p className="text-xs text-muted-foreground font-mono">{placement?.workflow_id || '—'}</p>
                      </div>
                    </div>
                    <EmergencyBadge level={placement?.emergency_level} />
                  </div>

                  <div className="space-y-2 flex-1">
                    <div className="flex items-center gap-2 text-sm">
                      <span className="text-muted-foreground">Child:</span>
                      <span className="text-foreground font-mono">{placement?.child_id || '—'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <MapPin size={14} className="text-muted-foreground" />
                      <span className="text-foreground">{placement?.location || 'Unknown'}</span>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      <Users size={14} className="text-muted-foreground" />
                      <span className="text-foreground">Capacity: {placement?.capacity ?? '—'}</span>
                      {placement?.siblings_accommodated && (
                        <span className="text-xs bg-success/10 text-success px-1.5 py-0.5 rounded">Siblings OK</span>
                      )}
                    </div>
                    <div className="flex items-center justify-between text-sm pt-1">
                      <span className="text-muted-foreground">Match Score</span>
                      <span className={`font-mono font-medium ${
                        (placement?.match_score ?? 0) >= 85 ? 'text-success' : (placement?.match_score ?? 0) >= 60 ? 'text-warning' : 'text-destructive'
                      }`}>
                        {placement?.match_score ?? '—'}%
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Confidence</span>
                      <span className="font-mono">{placement?.confidence_score != null ? `${placement.confidence_score * (placement.confidence_score <= 1 ? 100 : 1)}%` : '—'}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Risk Score</span>
                      <span className={`font-mono ${
                        (placement?.risk_score ?? 0) >= 7 ? 'text-destructive' : (placement?.risk_score ?? 0) >= 4 ? 'text-warning' : 'text-success'
                      }`}>
                        {placement?.risk_score ?? '—'}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Stage</span>
                      <span className="font-mono">{placement?.current_stage || '—'}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Workflow</span>
                      <span className="font-mono">{placement?.status || '—'}</span>
                    </div>
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">Progress</span>
                      <span className="font-mono">{placement?.progress != null ? `${placement.progress}%` : '—'}</span>
                    </div>
                  </div>

                  {placement?.top_matches && placement.top_matches.length > 0 && (
                    <AltMatches
                      matches={placement.top_matches}
                      index={i}
                    />
                  )}

                  {/* Crisis prediction for high-risk placements */}
                  {(placement?.risk_score ?? 0) > 60 && placement?.workflow_id && (
                    <div className="mt-3">
                      <CrisisAlertCard placementId={placement.workflow_id} />
                    </div>
                  )}

                  <div className="flex items-center justify-between mt-3 pt-3 border-t border-border">
                    <span className="text-xs text-muted-foreground">{formatDate(placement?.placement_date)}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => navigate(`/workflow/${placement?.workflow_id || ''}`)}
                    >
                      <ArrowRight size={14} />
                    </Button>
                  </div>
                </GlassCard>
              </motion.div>
            ))}
          </div>
        ) : (
          <GlassCard>
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Home size={40} className="text-muted mb-3" />
              <h3 className="text-lg font-semibold text-foreground mb-1">No Placements Found</h3>
              <p className="text-sm text-muted-foreground">
                {search ? 'Try a different search term' : 'No active placements at this time'}
              </p>
            </div>
          </GlassCard>
        )}
      </DataLoader>
    </motion.div>
  )
}
