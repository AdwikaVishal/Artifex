import { ApiError } from '@/services/api'
import { GlassCard } from './ui/glass-card'
import { CardSkeleton, ChartSkeleton, TableSkeleton } from './ui/skeleton'
import { AlertCircle, SearchX, RefreshCw, WifiOff } from 'lucide-react'
import { Button } from './ui/button'

interface DataLoaderProps {
  isLoading: boolean
  error?: Error | null
  children?: React.ReactNode
  type?: 'card' | 'table' | 'chart' | 'full' | 'inline'
  rows?: number
  refetch?: () => void
}

function getErrorType(error: Error): { icon: React.ElementType; title: string; helpText?: string } {
  const status = error instanceof ApiError ? error.status : null

  if (status === 404) {
    return {
      icon: SearchX,
      title: 'Not Found',
      helpText: 'The requested resource was not found. Check the ID and try again.',
    }
  }

  if (status !== null && status >= 500) {
    return {
      icon: AlertCircle,
      title: 'Server Error',
      helpText: 'The backend encountered an error. Please try again later.',
    }
  }

  const msg = error.message
  if (msg.includes('Cannot reach backend') || msg.includes('Network Error') || msg.includes('ERR_CONNECTION_REFUSED') || msg.includes('ERR_NETWORK')) {
    return {
      icon: WifiOff,
      title: 'Backend Unreachable',
      helpText: 'Ensure the backend server is running and CORS is not blocking the request.',
    }
  }

  return {
    icon: AlertCircle,
    title: 'Failed to load data',
  }
}

export function DataLoader({ isLoading, error, children, type = 'full', rows, refetch }: DataLoaderProps) {
  if (isLoading) {
    switch (type) {
      case 'card':
        return (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: rows || 4 }).map((_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        )
      case 'table':
        return <TableSkeleton rows={rows || 5} />
      case 'chart':
        return <ChartSkeleton />
      default:
        return (
          <div className="glass-card p-8 flex items-center justify-center">
            <div className="flex items-center gap-3">
              <svg className="animate-spin h-5 w-5 text-primary" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm text-muted-foreground">Loading...</span>
            </div>
          </div>
        )
    }
  }

  if (error) {
    const { icon: Icon, title, helpText } = getErrorType(error)
    return (
      <GlassCard className="p-8">
        <div className="flex flex-col items-center justify-center text-center">
          <Icon size={32} className="text-destructive mb-3" />
          <p className="text-sm font-medium text-destructive mb-1">{title}</p>
          <p className="text-xs text-muted-foreground mb-1 max-w-md">{error.message}</p>
          {helpText && <p className="text-xs text-muted-foreground mb-4">{helpText}</p>}
          {refetch && (
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCw size={14} />
              Retry
            </Button>
          )}
        </div>
      </GlassCard>
    )
  }

  return <>{children}</>
}
