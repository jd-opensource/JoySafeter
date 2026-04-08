'use client'

import { useTranslation } from '@/lib/i18n'

import { formatToolDisplay } from './toolDisplayRegistry'

interface ToolCallDetailProps {
  name: string
  args: Record<string, any>
  status: 'running' | 'completed' | 'failed'
  result?: any
  startTime?: number
  endTime?: number
}

export function ToolCallDetail({ name, args, status, result, startTime, endTime }: ToolCallDetailProps) {
  const { t } = useTranslation()
  const display = formatToolDisplay(name, args)
  const duration = startTime && endTime ? ((endTime - startTime) / 1000).toFixed(1) : null

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-[var(--text-primary)]">{display.label}</h3>
        <span className={`rounded-full px-2 py-0.5 text-xs ${
          status === 'completed' ? 'bg-green-100 text-green-700' :
          status === 'failed' ? 'bg-red-100 text-red-700' :
          'bg-blue-100 text-blue-700'
        }`}>
          {status === 'completed' ? t('common.statusCompleted') :
           status === 'failed' ? t('common.statusFailed') :
           t('common.statusRunning')}
        </span>
      </div>

      {display.detail && (
        <p className="font-mono text-xs text-[var(--text-tertiary)]">{display.detail}</p>
      )}

      {duration && (
        <p className="text-xs text-[var(--text-muted)]">{duration}s</p>
      )}

      {Object.keys(args).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">{t('chat.arguments')}</summary>
          <pre className="mt-1 max-h-[200px] overflow-auto rounded bg-[var(--surface-1)] p-2 text-[var(--text-secondary)]">
            {JSON.stringify(args, null, 2)}
          </pre>
        </details>
      )}

      {result !== undefined && (
        <details className="text-xs">
          <summary className="cursor-pointer text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">{t('chat.result')}</summary>
          <pre className="mt-1 max-h-[300px] overflow-auto rounded bg-[var(--surface-1)] p-2 text-[var(--text-secondary)]">
            {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}
