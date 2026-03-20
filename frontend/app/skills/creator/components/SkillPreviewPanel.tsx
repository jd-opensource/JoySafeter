'use client'

import { Save, RefreshCw, AlertTriangle, CheckCircle2, PackageOpen, FileCode } from 'lucide-react'
import React, { useState, useMemo } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import type { SkillPreviewData } from '../page'

import SkillFileTree from './SkillFileTree'
import type { PreviewFile } from './SkillFileTree'
import SkillFileViewer from './SkillFileViewer'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SkillPreviewPanelProps {
  previewData: SkillPreviewData | null
  isProcessing: boolean
  onSave: () => void
  onRegenerate: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SkillPreviewPanel({
  previewData,
  isProcessing,
  onSave,
  onRegenerate,
}: SkillPreviewPanelProps) {
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null)

  // Auto-select SKILL.md when preview data arrives
  React.useEffect(() => {
    if (previewData && previewData.files.length > 0) {
      const skillMd = previewData.files.find((f) => f.path === 'SKILL.md')
      setActiveFilePath(skillMd ? 'SKILL.md' : previewData.files[0].path)
    } else {
      setActiveFilePath(null)
    }
  }, [previewData])

  const activeFile: PreviewFile | null = useMemo(() => {
    if (!previewData || !activeFilePath) return null
    return previewData.files.find((f) => f.path === activeFilePath) || null
  }, [previewData, activeFilePath])

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
            {previewData.files.length} file{previewData.files.length !== 1 ? 's' : ''}
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

      {/* Main content: file tree + viewer */}
      <div className="flex min-h-0 flex-1">
        {/* File tree sidebar */}
        <div className="flex w-[180px] flex-shrink-0 flex-col overflow-hidden border-r border-gray-100">
          <div className="border-b border-gray-50 px-3 py-2">
            <span className="text-[10px] font-medium uppercase tracking-wider text-gray-400">
              Files
            </span>
          </div>
          <SkillFileTree
            files={previewData.files}
            activeFilePath={activeFilePath}
            onSelectFile={setActiveFilePath}
          />
        </div>

        {/* File content viewer */}
        <div className="flex min-w-0 flex-1 flex-col">
          <SkillFileViewer file={activeFile} />
        </div>
      </div>

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
