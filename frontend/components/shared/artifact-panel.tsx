'use client'

import { FileText, Image, Code } from 'lucide-react'
import { Card } from '@/components/ui/card'

interface Artifact {
  type: string
  title?: string
  content: string
  language?: string
}

interface ArtifactPanelProps {
  // Simple artifact list mode
  artifacts?: Artifact[]
  files?: Array<{ path: string; content: string }>
  // File browser mode (used by SkillPreviewPanel)
  threadId?: string | null
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
  className?: string
  autoPreview?: boolean
}

export function ArtifactPanel({
  artifacts,
  files,
  threadId: _threadId,
  fileTree,
  className,
  autoPreview: _autoPreview,
}: ArtifactPanelProps) {
  // File browser mode: render fileTree entries
  if (fileTree) {
    const entries = Object.entries(fileTree)
    if (!entries.length) return null
    return (
      <div className={`overflow-y-auto ${className || ''}`}>
        <div className="space-y-1 p-2">
          {entries.map(([path, meta]) => (
            <div
              key={path}
              className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-[var(--surface-3)]"
            >
              <Code className="h-3.5 w-3.5 flex-shrink-0 text-[var(--text-muted)]" />
              <span className="min-w-0 flex-1 truncate font-mono text-[var(--text-secondary)]">
                {path}
              </span>
              {meta.size != null && (
                <span className="flex-shrink-0 text-[var(--text-muted)]">
                  {(meta.size / 1024).toFixed(1)}k
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Simple artifact list mode
  const items =
    artifacts ||
    files?.map((f) => ({ type: 'file', title: f.path, content: f.content })) ||
    []

  if (!items.length) return null

  return (
    <div className={`space-y-2 ${className || ''}`}>
      {items.map((artifact, i) => (
        <Card key={i} className="p-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            {artifact.type === 'image' ? (
              <Image className="h-4 w-4" />
            ) : artifact.type === 'code' || artifact.type === 'file' ? (
              <Code className="h-4 w-4" />
            ) : (
              <FileText className="h-4 w-4" />
            )}
            {artifact.title || `Artifact ${i + 1}`}
          </div>
          {artifact.type === 'code' || artifact.type === 'file' ? (
            <pre className="mt-2 overflow-x-auto rounded bg-[var(--surface-2)] p-2 text-xs">
              <code>{artifact.content}</code>
            </pre>
          ) : (
            <p className="mt-1 text-sm text-[var(--text-muted)]">{artifact.content}</p>
          )}
        </Card>
      ))}
    </div>
  )
}
