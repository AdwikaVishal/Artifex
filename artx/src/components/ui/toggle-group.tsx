import { cn } from '@/lib/utils'

interface ToggleGroupProps {
  options: { value: string; label: string }[]
  value: string | string[]
  onChange: (value: string | string[]) => void
  multiple?: boolean
  className?: string
  label?: string
}

export function ToggleGroup({ options, value, onChange, multiple, className, label }: ToggleGroupProps) {
  const isSelected = (v: string) => (Array.isArray(value) ? value.includes(v) : value === v)

  const handleClick = (v: string) => {
    if (multiple) {
      const arr = value as string[]
      onChange(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
    } else {
      onChange(v)
    }
  }

  return (
    <div className="space-y-1.5">
      {label && (
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
      )}
      <div className={cn('flex flex-wrap gap-2', className)}>
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => handleClick(opt.value)}
            className={cn(
              'px-3 py-1.5 text-xs font-medium rounded-lg border transition-all duration-200 cursor-pointer',
              isSelected(opt.value)
                ? 'bg-primary/15 border-primary/40 text-primary'
                : 'bg-glass border-border-light text-muted-foreground hover:text-foreground hover:border-border-light/60'
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}
