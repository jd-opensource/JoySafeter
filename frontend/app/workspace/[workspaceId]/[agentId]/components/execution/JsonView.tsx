'use client'

import React from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

/**
 * Format JSON to better display string values containing newlines
 */
function formatJsonWithNewlines(data: any): string {
  try {
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

export const JsonView = React.memo(function JsonView({
  data,
  label,
}: {
  data: any
  label?: string
}) {
  if (!data) return null

  return (
    <div className="space-y-1">
      {label && (
        <div className="px-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
          {label}
        </div>
      )}
      <SyntaxHighlighter
        language="json"
        style={oneLight}
        PreTag="div"
        codeTagProps={{
          style: {
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            overflowWrap: 'break-word',
          },
        }}
        customStyle={{
          margin: 0,
          padding: '0.75rem',
          background: 'var(--surface-2)',
          fontSize: '11px',
          lineHeight: '1.6',
          fontFamily: 'JetBrains Mono, monospace',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          overflowWrap: 'break-word',
          maxWidth: '100%',
          borderRadius: '6px',
          border: '1px solid var(--border)',
        }}
        wrapLongLines={true}
      >
        {formatJsonWithNewlines(data)}
      </SyntaxHighlighter>
    </div>
  )
})

export function FormattedView({ data, label }: { data: any; label?: string }) {
  if (!data) return null

  if (typeof data === 'string') {
    return (
      <div className="space-y-1">
        {label && (
          <div className="px-1 text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
            {label}
          </div>
        )}
        <div className="whitespace-pre-wrap rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 font-mono text-xs leading-relaxed text-[var(--text-secondary)]">
          {data}
        </div>
      </div>
    )
  }

  return <JsonView data={data} label={label} />
}
