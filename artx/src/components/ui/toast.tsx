import { useState, useEffect, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react'

interface Toast {
  id: string
  title: string
  description?: string
  variant: 'success' | 'error' | 'warning' | 'info'
}

let toastListeners: ((toast: Toast) => void)[] = []

export function toast({ title, description, variant = 'info' }: Omit<Toast, 'id'>) {
  const id = Math.random().toString(36).slice(2)
  toastListeners.forEach((l) => l({ id, title, description, variant }))
  return id
}

const icons = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
}

const colors = {
  success: 'border-success/30 bg-success/10',
  error: 'border-destructive/30 bg-destructive/10',
  warning: 'border-warning/30 bg-warning/10',
  info: 'border-info/30 bg-info/10',
}

const iconColors = {
  success: 'text-success',
  error: 'text-destructive',
  warning: 'text-warning',
  info: 'text-info',
}

function ToastItem({ toast: t, onRemove }: { toast: Toast; onRemove: (id: string) => void }) {
  const Icon = icons[t.variant]

  useEffect(() => {
    const timer = setTimeout(() => onRemove(t.id), 4000)
    return () => clearTimeout(timer)
  }, [t.id, onRemove])

  return (
    <div
      className={cn(
        'glass-card p-4 border-l-4 shadow-xl animate-in flex items-start gap-3 min-w-[320px]',
        colors[t.variant]
      )}
    >
      <Icon size={20} className={cn('shrink-0 mt-0.5', iconColors[t.variant])} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{t.title}</p>
        {t.description && (
          <p className="text-xs text-muted-foreground mt-0.5">{t.description}</p>
        )}
      </div>
      <button
        onClick={() => onRemove(t.id)}
        className="text-muted-foreground hover:text-foreground shrink-0 cursor-pointer"
      >
        <X size={16} />
      </button>
    </div>
  )
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((t: Toast) => {
    setToasts((prev) => [...prev, t])
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  useEffect(() => {
    toastListeners.push(addToast)
    return () => {
      toastListeners = toastListeners.filter((l) => l !== addToast)
    }
  }, [addToast])

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onRemove={removeToast} />
      ))}
    </div>
  )
}
