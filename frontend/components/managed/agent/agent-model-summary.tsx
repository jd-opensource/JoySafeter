'use client'

import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/lib/i18n'
import {
  getAgentModelDisplayState,
  type AgentModelDisplayState,
  type AgentModelSource,
} from '@/lib/managed/agent-model-display'
import { cn } from '@/lib/utils'

function nonBlank(value: string | null | undefined) {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

function connectionTitle(t: ReturnType<typeof useTranslation>['t'], state: AgentModelDisplayState) {
  if (state.connection) {
    return (
      nonBlank(state.connection.name) ||
      nonBlank(state.connection.model) ||
      nonBlank(state.connectionId) ||
      '-'
    )
  }
  if (state.kind === 'connection_unavailable')
    return t('managed.modelDisplay.connectionUnavailable')
  return t('managed.modelDisplay.unbound')
}

function connectionMeta(state: AgentModelDisplayState) {
  if (!state.connection) return ''
  return [state.connection.provider, state.connection.protocol].filter(Boolean).join(' · ')
}

function connectionHint(t: ReturnType<typeof useTranslation>['t'], state: AgentModelDisplayState) {
  if (state.connection) return connectionMeta(state)
  if (state.kind === 'connection_unavailable')
    return t('managed.modelDisplay.connectionUnavailableHint')
  if (state.kind === 'unbound') return t('managed.modelDisplay.unboundHint')
  return ''
}

function DetailConnectionCard({ state }: { state: AgentModelDisplayState }) {
  const { t } = useTranslation()
  const title = connectionTitle(t, state)
  const meta = connectionMeta(state)

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium text-foreground">{title}</span>
        {state.connection?.is_default ? (
          <Badge variant="secondary">{t('managed.modelDisplay.defaultConnection')}</Badge>
        ) : null}
      </div>
      {meta ? <div className="mt-1 text-muted-foreground">{meta}</div> : null}
    </div>
  )
}

export function AgentModelSummary({
  agent,
  className,
  detail = false,
  showMeta = true,
}: {
  agent: AgentModelSource | null | undefined
  className?: string
  detail?: boolean
  showMeta?: boolean
}) {
  const { t } = useTranslation()
  const state = getAgentModelDisplayState(agent)

  if (detail && state.connection) {
    return (
      <div className={cn('min-w-0', className)}>
        <DetailConnectionCard state={state} />
      </div>
    )
  }

  const title = connectionTitle(t, state)
  const hint = connectionHint(t, state)

  return (
    <div className={cn('min-w-0', className)}>
      <div className="truncate text-sm text-muted-foreground">{title}</div>
      {showMeta && hint ? (
        <div className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  )
}
