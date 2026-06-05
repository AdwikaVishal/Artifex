import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return '—'
  try {
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(date))
  } catch {
    return '—'
  }
}

export function formatDateFull(date: string | Date | null | undefined): string {
  if (!date) return '—'
  try {
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }).format(new Date(date))
  } catch {
    return '—'
  }
}

export function getEmergencyColor(level: unknown): string {
  if (!level || typeof level !== 'string') return 'text-muted-foreground border-border-light bg-glass'
  switch (level.toLowerCase()) {
    case 'critical':
      return 'text-critical border-critical/30 bg-critical/10'
    case 'high':
      return 'text-emergency border-emergency/30 bg-emergency/10'
    case 'medium':
      return 'text-warning border-warning/30 bg-warning/10'
    case 'low':
      return 'text-success border-success/30 bg-success/10'
    default:
      return 'text-muted-foreground border-border-light bg-glass'
  }
}

export function getStatusColor(status: unknown): string {
  if (!status || typeof status !== 'string') return 'bg-muted/20 text-muted-foreground border-border-light'
  switch (status.toLowerCase()) {
    case 'active':
    case 'completed':
    case 'approved':
    case 'healthy':
      return 'bg-success/20 text-success border-success/30'
    case 'pending':
    case 'processing':
    case 'matching':
    case 'analyzing':
      return 'bg-warning/20 text-warning border-warning/30'
    case 'failed':
    case 'rejected':
    case 'critical':
      return 'bg-destructive/20 text-destructive border-destructive/30'
    default:
      return 'bg-muted/20 text-muted-foreground border-border-light'
  }
}

export function getWorkflowStageIndex(stage: unknown): number {
  if (!stage || typeof stage !== 'string') return -1
  const stages = ['submitted', 'matching', 'risk_analysis', 'validation', 'approval_pending', 'placement_assigned']
  return stages.indexOf(stage.toLowerCase().replace(/\s+/g, '_'))
}

export function getStageLabel(status?: unknown) {
  if (!status) return "Unknown";

  if (typeof status === "object") {
    if ("status" in status && typeof status.status === "string") {
      status = status.status;
    } else {
      return "Unknown";
    }
  }

  if (typeof status !== "string") {
    return "Unknown";
  }

  switch (status.toLowerCase()) {
    case "running":
      return "Running";

    case "completed":
      return "Completed";

    case "failed":
      return "Failed";

    case "pending":
      return "Pending";

    default:
      return status;
  }
}

export function safeCapitalize(value?: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    return "Unknown";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function safeLowercase(value?: unknown): string {
  if (typeof value !== "string") {
    return "";
  }
  return value.toLowerCase();
}

export function riskScoreColor(score: number): string {
  if (score >= 7) return 'text-destructive'
  if (score >= 4) return 'text-warning'
  return 'text-success'
}
