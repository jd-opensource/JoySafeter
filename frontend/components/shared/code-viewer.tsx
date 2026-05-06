'use client'

interface CodeViewerProps {
  code: string
  language?: string
  className?: string
  filename?: string
  maxHeight?: string
}

export default function CodeViewer({
  code,
  language,
  className,
  filename,
  maxHeight,
}: CodeViewerProps) {
  return (
    <div
      className={`flex flex-col overflow-hidden rounded ${className || ''}`}
      style={maxHeight ? { maxHeight } : undefined}
    >
      {filename && (
        <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--surface-3)] px-3 py-1.5 font-mono text-xs text-[var(--text-muted)]">
          {filename}
        </div>
      )}
      <pre className="flex-1 overflow-auto bg-[var(--surface-2)] p-3 text-sm">
        <code className={language ? `language-${language}` : ''}>{code}</code>
      </pre>
    </div>
  )
}
