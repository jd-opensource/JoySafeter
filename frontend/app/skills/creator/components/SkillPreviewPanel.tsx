'use client'

import {
  Save,
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  PackageOpen,
  FileCode,
} from 'lucide-react'
import React, { useState, useMemo } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/core/utils/cn'

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

const SkillPreviewPanel: React.FC<SkillPreviewPanelProps> = ({
  previewData,
  isProcessing,
  onSave,
  onRegenerate,
}) => {
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
      <div className="flex flex-col h-full bg-gray-50/50">
        <div className="flex items-center justify-center flex-1">
          <div className="text-center px-6">
            <div className="w-12 h-12 rounded-2xl bg-gray-100 flex items-center justify-center mx-auto mb-3">
              <PackageOpen size={22} className="text-gray-400" />
            </div>
            <h4 className="text-sm font-medium text-gray-600 mb-1">No preview yet</h4>
            <p className="text-xs text-gray-400 max-w-[220px] leading-relaxed">
              Start a conversation to generate skill files. The preview will appear here.
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ---- Preview content ----
  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode size={16} className="text-emerald-600 flex-shrink-0" />
          <h3 className="text-sm font-semibold text-gray-800 truncate">
            {previewData.skill_name || 'Unnamed Skill'}
          </h3>
          <span className="text-[10px] text-gray-400 flex-shrink-0">
            {previewData.files.length} file{previewData.files.length !== 1 ? 's' : ''}
          </span>
        </div>

        {/* Validation badge */}
        {validation && (
          <div className="flex-shrink-0">
            {validation.valid ? (
              <span className="flex items-center gap-1 text-[10px] text-green-600 bg-green-50 px-2 py-0.5 rounded-full">
                <CheckCircle2 size={10} />
                Valid
              </span>
            ) : (
              <span className="flex items-center gap-1 text-[10px] text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
                <AlertTriangle size={10} />
                {validation.errors.length} error{validation.errors.length !== 1 ? 's' : ''}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Validation errors / warnings */}
      {validation && (!validation.valid || validation.warnings.length > 0) && (
        <div className="px-4 py-2 border-b border-gray-100 space-y-1 flex-shrink-0">
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
      <div className="flex flex-1 min-h-0">
        {/* File tree sidebar */}
        <div className="w-[180px] border-r border-gray-100 flex flex-col flex-shrink-0 overflow-hidden">
          <div className="px-3 py-2 border-b border-gray-50">
            <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">
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
        <div className="flex-1 flex flex-col min-w-0">
          <SkillFileViewer file={activeFile} />
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 px-4 py-3 border-t border-gray-100 flex-shrink-0 bg-gray-50/50">
        <Button
          variant="outline"
          size="sm"
          onClick={onRegenerate}
          disabled={isProcessing}
          className="text-xs gap-1.5"
        >
          <RefreshCw size={12} />
          Regenerate
        </Button>
        <Button
          size="sm"
          onClick={onSave}
          disabled={isProcessing || (validation ? !validation.valid : false)}
          className="text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white ml-auto"
        >
          <Save size={12} />
          Save to Library
        </Button>
      </div>
    </div>
  )
}

export default SkillPreviewPanel
