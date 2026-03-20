'use client'

import { Save, RefreshCw, AlertTriangle, CheckCircle2, PackageOpen, FileCode } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'

import type { SkillPreviewData } from '../page'

import { ArtifactPanel } from '@/app/chat/components/ArtifactPanel'

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

  // ---- Empty state ----
  if (!previewData) {
    return (
      <div className="flex h-full flex-col bg-gray-50/50">
        <div className="flex flex-1 items-center justify-center">
          <div className="px-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-gray-100">
              <PackageOpen size={22} className="text-gray-400" />
            </div>
            <h4 className="mb-1 text-sm font-medium text-gray-600">No preview yet</h4>
            <p className="max-w-[220px] text-xs leading-relaxed text-gray-400">
              Start a conversation to generate skill files. The preview will appear here.
            </p>
          </div>
        </div>
      </div>
    )
  }

  const fileCount =
    fileTree && Object.keys(fileTree).length > 0
      ? Object.keys(fileTree).length
      : previewData.files.length

  // ---- Preview content ----
  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-gray-100 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileCode size={16} className="flex-shrink-0 text-emerald-600" />
          <h3 className="truncate text-sm font-semibold text-gray-800">
            {previewData.skill_name || 'Unnamed Skill'}
          </h3>
          <span className="flex-shrink-0 text-[10px] text-gray-400">
            {fileCount} file{fileCount !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Validation badge */}
        {validation && (
          <div className="flex-shrink-0">
            {validation.valid ? (
              <span className="flex items-center gap-1 rounded-full bg-green-50 px-2 py-0.5 text-[10px] text-green-600">
                <CheckCircle2 size={10} />
                Valid
              </span>
            ) : (
              <span className="flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[10px] text-red-600">
                <AlertTriangle size={10} />
                {validation.errors.length} error{validation.errors.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Validation errors / warnings */}
      {validation && (!validation.valid || validation.warnings.length > 0) && (
        <div className="flex-shrink-0 space-y-1 border-b border-gray-100 px-4 py-2">
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
      {threadId && Object.keys(fileTree || {}).length > 0 ? (
        <ArtifactPanel
          threadId={threadId}
          fileTree={fileTree}
          className="min-h-0 flex-1"
        />
      ) : (
        <div className="flex flex-1 items-center justify-center text-xs text-gray-400">
          No files yet
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-gray-100 bg-gray-50/50 px-4 py-3">
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
          disabled={isProcessing || (validation ? !validation.valid : false)}
          className="ml-auto gap-1.5 bg-emerald-600 text-xs text-white hover:bg-emerald-700"
        >
          <Save size={12} />
          Save to Library
        </Button>
      </div>
    </div>
  )
}
