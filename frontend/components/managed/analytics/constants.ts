import type { TimeRange, CallStatus } from '@/lib/managed/analytics/types'

export const CHART_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
  'var(--chart-7)',
  'var(--chart-8)',
] as const

export const ENGINE_COLOR_MAP: Record<string, number> = {
  claude: 0,
  codex: 1,
  native: 2,
  opencode: 3,
  grokbuild: 4,
  qwencode: 5,
  deepseek: 6,
  other: 7,
}

export const ENGINE_LABELS: Record<string, string> = {
  claude: 'Claude',
  codex: 'Codex',
  native: 'Native',
  opencode: 'OpenCode',
  grokbuild: 'Grok Build',
  qwencode: 'Qwen Code',
  deepseek: 'DeepSeek',
  other: 'Other',
}

export const TIME_RANGE_OPTIONS: { value: TimeRange; label?: string; labelKey?: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
  { value: '90d', label: '90d' },
  { value: 'all', labelKey: 'common.all' },
]

export const CALL_STATUS_OPTIONS: { value: CallStatus; labelKey: string }[] = [
  { value: 'running', labelKey: 'analytics.status.running' },
  { value: 'completed', labelKey: 'analytics.status.completed' },
  { value: 'error', labelKey: 'common.error' },
  { value: 'timeout', labelKey: 'analytics.status.timeout' },
  { value: 'cancelled', labelKey: 'analytics.status.cancelled' },
]
