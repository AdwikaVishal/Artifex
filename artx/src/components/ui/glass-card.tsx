import { cn } from '@/lib/utils'

export function GlassCard({ className, children, hover = true, ...props }: React.HTMLAttributes<HTMLDivElement> & { hover?: boolean }) {
  return (
    <div
      className={cn(
        'glass-card p-5',
        hover && 'hover:border-glass-border/30',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export function GlassCardHeader({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('flex items-center justify-between mb-4', className)} {...props}>
      {children}
    </div>
  )
}

export function GlassCardTitle({ className, children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-sm font-semibold text-muted-foreground uppercase tracking-wider', className)} {...props}>
      {children}
    </h3>
  )
}

export function GlassCardValue({ className, children, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('text-2xl font-bold text-foreground', className)} {...props}>
      {children}
    </div>
  )
}
