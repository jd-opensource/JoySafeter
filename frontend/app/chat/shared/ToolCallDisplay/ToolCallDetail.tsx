'use client'

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
  const display = formatToolDisplay(name, args)
  const duration = startTime && endTime ? ((endTime - startTime) / 1000).toFixed(1) : null

  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-gray-900">{display.label}</h3>
        <span className={`rounded-full px-2 py-0.5 text-xs ${
          status === 'completed' ? 'bg-green-100 text-green-700' :
          status === 'failed' ? 'bg-red-100 text-red-700' :
          'bg-blue-100 text-blue-700'
        }`}>
          {status}
        </span>
      </div>

      {display.detail && (
        <p className="font-mono text-xs text-gray-500">{display.detail}</p>
      )}

      {duration && (
        <p className="text-xs text-gray-400">{duration}s</p>
      )}

      {Object.keys(args).length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-gray-500 hover:text-gray-700">Arguments</summary>
          <pre className="mt-1 max-h-[200px] overflow-auto rounded bg-gray-50 p-2 text-gray-600">
            {JSON.stringify(args, null, 2)}
          </pre>
        </details>
      )}

      {result !== undefined && (
        <details className="text-xs">
          <summary className="cursor-pointer text-gray-500 hover:text-gray-700">Result</summary>
          <pre className="mt-1 max-h-[300px] overflow-auto rounded bg-gray-50 p-2 text-gray-600">
            {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
          </pre>
        </details>
      )}
    </div>
  )
}
