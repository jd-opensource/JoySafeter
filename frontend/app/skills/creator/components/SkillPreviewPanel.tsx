'use client'

import { Save, RefreshCw, AlertTriangle, CheckCircle2, PackageOpen, FileCode, Loader2 } from 'lucide-react'
import { ArtifactPanel } from '@/app/chat/components/ArtifactPanel'
import { Button } from '@/components/ui/button'

import type { SkillPreviewData } from '../page'


// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillPreviewPanelProps {
  previewData: SkillPreviewData | null
  fileTree?: Record<string, { action: string; size?: number; timestamp?: number }>
  threadId: string | null
  isProcessing: boolean
  onSave: () => void
  onRegenerate: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SkillPreviewPanel({
  previewData,
  fileTree,
  threadId,
  isProcessing,
  onSave,
  onRegenerate,
}: SkillPreviewPanelProps) {
  const validation = previewData?.validation
  const fileKeys = fileTree ? Object.keys(fileTree) : []
  const hasFiles = threadId && fileKeys.length > 0
  const fileCount = hasFiles ? fileKeys.length : (previewData?.files.length ?? 0)

  // ---- Empty state: no files and no previewData ----
  if (!previewData && !hasFiles) {
    return (
      <div className="flex h-full flex-col bg-[var(--surface-2)]">
        <div className="flex flex-1 items-center justify-center">
          <div className="px-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--surface-3)]">
              <PackageOpen size={22} className="text-[var(--text-muted)]" />
            </div>
            <h4 className="mb-1 text-sm font-medium text-[var(--text-secondary)]">No preview yet</h4>
            <p className="max-w-[220px] text-xs leading-relaxed text-[var(--text-muted)]">
              Start a conversation to generate skill files. The preview will appear here.
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ---- Preview content ----
  return (
    <div className="flex h-full flex-col bg-[var(--surface-2)]">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-[var(--border-muted)] px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileCode size={16} className="flex-shrink-0 text-[var(--skill-brand-600)]" />
          <h3 className="truncate text-sm font-semibold text-[var(--text-primary)]">
            {previewData?.skill_name || 'Generating...'}
          </h3>
          {fileCount > 0 && (
            <span className="flex-shrink-0 text-[10px] text-[var(--text-muted)]">
              {fileCount} file{fileCount !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {/* Validation takes priority over in-progress indicator */}
        {validation ? (
          validation.valid ? (
            <span className="flex flex-shrink-0 items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-[10px] text-green-600">
              <CheckCircle2 size={10} />
              Valid
            </span>
          ) : (
            <span className="flex flex-shrink-0 items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[10px] text-red-600">
              <AlertTriangle size={10} />
              {validation.errors.length} error{validation.errors.length !== 1 ? 's' : ''}
            </span>
          )
        ) : isProcessing ? (
          <span className="flex flex-shrink-0 items-center gap-1 rounded-full bg-[var(--surface-3)] px-2 py-0.5 text-[10px] text-[var(--text-muted)]">
            <Loader2 size={10} className="animate-spin" />
            Writing...
          </span>
        ) : null}
      </div>

      {/* Validation errors / warnings */}
      {validation && (!validation.valid || validation.warnings.length > 0) && (
        <div className="flex-shrink-0 space-y-1 border-b border-[var(--border-muted)] px-4 py-2">
          {validation.errors.map((err, i) => (
            <div key={`e-${i}`} className="flex items-center gap-1.5 text-[10px] text-red-600">
              <AlertTriangle size={10} className="flex-shrink-0" />
              <span>{err}</span>
            </div>
          ))}
          {validation.warnings.map((w, i) => (
            <div key={`w-${i}`} className="flex items-center gap-1.5 text-[10px] text-amber-600">
              <AlertTriangle size={10} className="flex-shrink-0" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* File browser via ArtifactPanel */}
      {hasFiles ? (
        <ArtifactPanel
          threadId={threadId}
          fileTree={fileTree}
          className="min-h-0 flex-1"
          autoPreview
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-xs text-[var(--text-muted)]">
          {isProcessing ? 'Waiting for files...' : 'No files yet'}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-[var(--border-muted)] bg-[var(--surface-2)] px-4 py-3">
        <Button
          variant="outline"
          size="sm"
          onClick={onRegenerate}
          disabled={isProcessing}
          className="gap-1.5 text-xs"
        >
          <RefreshCw size={12} />
          Regenerate
        </Button>
        <Button
          size="sm"
          onClick={onSave}
          disabled={isProcessing || !previewData || validation?.valid === false}
          className="ml-auto gap-1.5 bg-[var(--skill-brand-600)] text-xs text-white hover:bg-[var(--skill-brand-700)]"
        >
          <Save size={12} />
          Save to Library
        </Button>
      </div>
    </div>
  )
}
