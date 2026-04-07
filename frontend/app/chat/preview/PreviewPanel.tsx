'use client'

import { X, FolderTree, Wrench } from 'lucide-react'
import React, { useState, useMemo } from 'react'

import { useChatState } from '../ChatProvider'
import ArtifactPanel from '../components/ArtifactPanel'
import { ToolCallDetail } from '../shared/ToolCallDisplay'


export default function PreviewPanel() {
  const { state, dispatch } = useChatState()
  const { preview, ui, threadId } = state
  const [activeTab, setActiveTab] = useState<'files' | 'tool'>('files')

  const fileKeys = useMemo(() => Object.keys(preview.fileTree), [preview.fileTree])
  const hasFiles = fileKeys.length > 0
  const hasTool = !!ui.selectedTool

  return (
    <div className="flex h-full flex-col bg-[var(--surface-elevated)]">
      {/* Header with tabs */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex gap-1">
          {hasFiles && (
            <button
              onClick={() => setActiveTab('files')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-all duration-200 ${
                activeTab === 'files'
                  ? 'bg-[var(--surface-3)] font-medium'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
              }`}
            >
              <FolderTree size={14} />
              Files ({fileKeys.length})
            </button>
          )}
          {hasTool && (
            <button
              onClick={() => setActiveTab('tool')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm transition-all duration-200 ${
                activeTab === 'tool'
                  ? 'bg-[var(--surface-3)] font-medium'
                  : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]'
              }`}
            >
              <Wrench size={14} />
              {ui.selectedTool?.name}
            </button>
          )}
        </div>
        <button
          onClick={() => dispatch({ type: 'HIDE_PREVIEW' })}
          className="rounded-md p-1 text-[var(--text-muted)] hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {activeTab === 'files' && threadId && (
          <ArtifactPanel threadId={threadId} fileTree={preview.fileTree} />
        )}
        {activeTab === 'tool' && ui.selectedTool && (
          <div className="overflow-auto">
            <ToolCallDetail
              name={ui.selectedTool.name}
              args={ui.selectedTool.args}
              status={ui.selectedTool.status}
              result={ui.selectedTool.result}
              startTime={ui.selectedTool.startTime}
              endTime={ui.selectedTool.endTime}
            />
          </div>
        )}
      </div>
    </div>
  )
}
