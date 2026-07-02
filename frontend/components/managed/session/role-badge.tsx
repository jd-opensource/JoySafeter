'use client'

import { cn } from '@/lib/utils'
import { useTranslation } from '@/lib/i18n'

const roleStyles: Record<string, { bg: string; labelKey: string }> = {
  // User events — red
  'user.message': { bg: 'bg-red-500 text-white', labelKey: 'user' },
  'user.interrupt': { bg: 'bg-gray-600 text-white', labelKey: 'interrupt' },
  'user.define_outcome': { bg: 'bg-red-500 text-white', labelKey: 'user' },
  'user.tool_result': { bg: 'bg-gray-600 text-white', labelKey: 'result' },
  'user.custom_tool_result': { bg: 'bg-gray-600 text-white', labelKey: 'result' },
  'user.tool_confirmation': { bg: 'bg-gray-600 text-white', labelKey: 'confirm' },

  // Agent events — blue
  'agent.message': { bg: 'bg-blue-600 text-white', labelKey: 'agent' },
  'agent.thinking': { bg: 'bg-pink-500 text-white', labelKey: 'thinking' },
  'agent.mcp_tool_use': { bg: 'bg-gray-700 text-white', labelKey: 'tool' },
  'agent.mcp_tool_result': { bg: 'bg-gray-600 text-white', labelKey: 'result' },
  'agent.tool_use': { bg: 'bg-gray-700 text-white', labelKey: 'tool' },
  'agent.tool_result': { bg: 'bg-gray-600 text-white', labelKey: 'result' },
  'agent.custom_tool_use': { bg: 'bg-gray-700 text-white', labelKey: 'tool' },
  'agent.error': { bg: 'bg-red-600 text-white', labelKey: 'error' },
  'agent.thread_message_sent': { bg: 'bg-blue-600 text-white', labelKey: 'agent' },
  'agent.thread_message_received': { bg: 'bg-blue-600 text-white', labelKey: 'agent' },
  'agent.thread_context_compacted': { bg: 'bg-gray-600 text-white', labelKey: 'compact' },

  // Background sub-agent lifecycle (Task tool, run_in_background=true)
  'agent.bg_task_started': { bg: 'bg-indigo-500 text-white', labelKey: 'bgTaskStarted' },
  'agent.bg_task_progress': { bg: 'bg-indigo-400 text-white', labelKey: 'bgTaskProgress' },
  'agent.bg_task_finished': { bg: 'bg-indigo-600 text-white', labelKey: 'bgTaskFinished' },

  // Session events
  'session.created': { bg: 'bg-gray-500 text-white', labelKey: 'created' },
  'session.status_running': { bg: 'bg-emerald-500 text-white', labelKey: 'running' },
  'session.status_idle': {
    bg: 'bg-gray-400 text-gray-800 dark:bg-gray-500 dark:text-gray-100',
    labelKey: 'idle',
  },
  'session.status_terminated': { bg: 'bg-gray-500 text-white', labelKey: 'ended' },
  'session.status_rescheduled': { bg: 'bg-yellow-500 text-white', labelKey: 'rescheduled' },
  'session.error': { bg: 'bg-red-600 text-white', labelKey: 'error' },
  'session.updated': { bg: 'bg-gray-500 text-white', labelKey: 'updated' },
  'session.thread_created': { bg: 'bg-gray-500 text-white', labelKey: 'thread' },
  'session.thread_status_idle': {
    bg: 'bg-gray-400 text-gray-800 dark:bg-gray-500 dark:text-gray-100',
    labelKey: 'idle',
  },
  'session.thread_status_running': { bg: 'bg-emerald-500 text-white', labelKey: 'running' },
  'session.thread_status_terminated': { bg: 'bg-gray-500 text-white', labelKey: 'ended' },

  // Span events — gray (Model)
  'span.model_request_start': { bg: 'bg-gray-500 text-white', labelKey: 'model' },
  'span.model_request_end': { bg: 'bg-gray-500 text-white', labelKey: 'model' },
  'span.outcome_evaluation_start': { bg: 'bg-gray-500 text-white', labelKey: 'eval' },
  'span.outcome_evaluation_ongoing': { bg: 'bg-gray-500 text-white', labelKey: 'eval' },
  'span.outcome_evaluation_end': { bg: 'bg-gray-500 text-white', labelKey: 'eval' },

  // Short names (backend returns without prefix)
  thinking: { bg: 'bg-pink-500 text-white', labelKey: 'thinking' },
  text: { bg: 'bg-blue-600 text-white', labelKey: 'agent' },
  tool_use: { bg: 'bg-gray-700 text-white', labelKey: 'tool' },
  tool_result: { bg: 'bg-gray-600 text-white', labelKey: 'result' },
  model_request_start: { bg: 'bg-gray-500 text-white', labelKey: 'model' },
  model_request_end: { bg: 'bg-gray-500 text-white', labelKey: 'model' },
}

export function RoleBadge({ eventType }: { eventType: string; toolName?: string }) {
  const { t } = useTranslation()
  const style = roleStyles[eventType]
  const label = style?.labelKey
    ? t(`managed.sessions.roles.${style.labelKey}`)
    : eventType.split('.').pop() || eventType

  return (
    <span
      className={cn(
        'inline-flex min-w-[52px] shrink-0 items-center justify-center rounded px-2 py-0.5 text-[11px] font-medium',
        style?.bg || 'bg-gray-500 text-white',
      )}
    >
      {label}
    </span>
  )
}
