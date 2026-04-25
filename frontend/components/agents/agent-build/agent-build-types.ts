import type { LucideIcon } from 'lucide-react'

export interface AgentBuildStageConfig {
  id: string
  labelKey: string
  descriptionKey: string
  icon: LucideIcon
  primaryActionKey?: string
}

export interface AgentBuildStatusBadge {
  label: string
  variant?: 'default' | 'outline' | 'secondary' | 'destructive'
}
