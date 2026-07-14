'use client'

import { useEffect } from 'react'
import { cn } from '@/lib/utils'
import { StatusBadge, MonoId } from '@/components/managed/shared'
import { useTranslation } from '@/lib/i18n'
import { StatTile } from './stat-tile'
import { ObservationWaterfall } from './observation-waterfall'
import { useObservationTree } from '@/lib/managed/analytics/hooks'
import {
  formatDuration,
  formatCompactNumber,
  formatCost,
} from '@/lib/managed/analytics/formatters'
import type { CallRecord } from '@/lib/managed/analytics/types'

interface CallDetailDrawerProps {
  call: CallRecord | null
  open: boolean
  onClose: () => void
}

function MetadataRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-sm text-foreground">{children}</span>
    </div>
  )
}

export function CallDetailDrawer({ call, open, onClose }: CallDetailDrawerProps) {
  const { t } = useTranslation()
  const { data: observations, isLoading: obsLoading } = useObservationTree(
    call?.trace_id ?? null,
  )

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  const totalDurationMs = call?.duration_ms ?? 0

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/20"
          onClick={onClose}
        />
      )}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={call?.agent_name ?? t('analytics.callDetail.title')}
        className={cn(
          'fixed inset-y-0 right-0 z-50 w-[480px] bg-card border-l border-border shadow-lg transform transition-transform duration-200 flex flex-col',
          open ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-5 py-4 shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <h2 className="text-sm font-medium truncate">
              {call?.agent_name ?? t('analytics.callDetail.title')}
            </h2>
            {call && <StatusBadge status={call.status} />}
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-accent/50 transition-colors shrink-0"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4 4l8 8M12 4l-8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {call && (
          <div className="flex-1 overflow-y-auto">
            {/* Metadata */}
            <div className="border-b border-border px-5 py-3">
              <MetadataRow label={t('analytics.calls.columns.engine')}>{call.engine_kind}</MetadataRow>
              <MetadataRow label={t('analytics.calls.columns.model')}>{call.model}</MetadataRow>
              <MetadataRow label={t('analytics.calls.columns.session')}>
                <MonoId id={call.session_id} />
              </MetadataRow>
              <MetadataRow label={t('analytics.calls.columns.time')}>
                {new Date(call.started_at).toLocaleString()}
              </MetadataRow>
              {call.completed_at && (
                <MetadataRow label={t('analytics.callDetail.completed')}>
                  {new Date(call.completed_at).toLocaleString()}
                </MetadataRow>
              )}
            </div>

            {/* Metrics */}
            <div className="grid grid-cols-3 gap-2 border-b border-border px-5 py-4">
              <StatTile
                label={t('analytics.calls.columns.inputTokens')}
                value={formatCompactNumber(call.input_tokens)}
              />
              <StatTile
                label={t('analytics.calls.columns.outputTokens')}
                value={formatCompactNumber(call.output_tokens)}
              />
              <StatTile
                label={t('analytics.calls.columns.ttft')}
                value={call.ttft_ms !== null ? formatDuration(call.ttft_ms) : '—'}
              />
              <StatTile
                label={t('analytics.calls.columns.duration')}
                value={formatDuration(call.duration_ms)}
              />
              <StatTile
                label={t('analytics.calls.columns.cost')}
                value={formatCost(call.cost)}
              />
              <StatTile
                label={t('analytics.callDetail.steps')}
                value={String(call.agent_steps)}
              />
            </div>

            {/* Observation waterfall */}
            <div className="px-5 py-4">
              <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground mb-3">
                {t('analytics.observations.title')}
              </h3>
              <ObservationWaterfall
                nodes={observations ?? []}
                totalDurationMs={totalDurationMs}
                loading={obsLoading}
              />
            </div>

            {/* Error */}
            {call.error && (
              <div className="border-t border-border px-5 py-4">
                <h3 className="text-xs font-medium uppercase tracking-wider text-red-600 dark:text-red-400 mb-2">
                  {t('common.error')}
                </h3>
                <pre className="text-xs text-red-600 dark:text-red-400 whitespace-pre-wrap break-words bg-red-50 dark:bg-red-950/30 rounded-md p-3">
                  {call.error}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
