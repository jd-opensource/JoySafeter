'use client'

import { useCodeEditorStore } from '../stores/codeEditorStore'

interface Props {
  onLineClick?: (line: number) => void
}

export function CodeErrorPanel({ onLineClick }: Props) {
  const errors = useCodeEditorStore((s) => s.parseErrors)

  if (errors.length === 0) return null

  return (
    <div className="border-t bg-red-50 dark:bg-red-950/20 px-4 py-2 max-h-32 overflow-y-auto text-sm">
      {errors.map((e, i) => (
        <div
          key={i}
          className="cursor-pointer hover:underline py-0.5 flex items-start gap-1.5"
          onClick={() => e.line && onLineClick?.(e.line)}
        >
          <span
            className={
              e.severity === 'error' ? 'text-red-600 dark:text-red-400' : 'text-yellow-600 dark:text-yellow-400'
            }
          >
            {e.severity === 'error' ? '\u2715' : '\u26A0'}
          </span>
          <span className="text-muted-foreground">
            {e.line ? `Line ${e.line}: ` : ''}
            {e.message}
          </span>
        </div>
      ))}
    </div>
  )
}
