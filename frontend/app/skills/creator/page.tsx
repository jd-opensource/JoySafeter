'use client'

import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import React from 'react'

import { Button } from '@/components/ui/button'
import { useSkillCreatorRun } from '@/hooks/use-skill-creator-run'

import SkillCreatorChat from './components/SkillCreatorChat'
import SkillPreviewPanel from './components/SkillPreviewPanel'
import SkillSaveDialog from './components/SkillSaveDialog'

export interface SkillPreviewData {
  skill_name: string
  files: Array<{
    path: string
    content: string
    file_type: string
    size: number
  }>
  validation: {
    valid: boolean
    errors: string[]
    warnings: string[]
  }
}

export default function SkillCreatorPage() {
  const {
    messages,
    isProcessing,
    isSubmitting,
    threadId,
    previewData,
    fileTree,
    graphReady,
    graphError,
    effectiveEditSkillId,
    hasRunState,
    showSaveDialog,
    setShowSaveDialog,
    sendMessage,
    stopMessage,
    handleRegenerate,
    handleSaved,
  } = useSkillCreatorRun()

  return (
    <div className="flex h-screen flex-col bg-[var(--bg)]">
      <div className="flex flex-shrink-0 items-center gap-3 border-b border-[var(--border-muted)] px-4 py-2.5">
        <Link href="/skills">
          <Button variant="ghost" size="sm" className="gap-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
            <ArrowLeft size={14} />
            <span className="text-xs">Skills</span>
          </Button>
        </Link>
        <div className="h-4 w-px bg-[var(--border)]" />
        <h1 className="text-sm font-semibold text-[var(--text-primary)]">
          {effectiveEditSkillId ? 'Edit Skill' : 'Create Skill'}
        </h1>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col border-r border-[var(--border-muted)]">
          {graphError && !hasRunState ? (
            <div className="flex flex-1 items-center justify-center text-sm text-red-500">
              {graphError}
            </div>
          ) : !graphReady && !hasRunState ? (
            <div className="flex flex-1 items-center justify-center text-sm text-[var(--text-muted)]">
              Initializing Skill Creator...
            </div>
          ) : (
            <SkillCreatorChat
              messages={messages}
              isProcessing={isProcessing}
              isSubmitting={isSubmitting}
              inputDisabled={!graphReady}
              onSendMessage={sendMessage}
              onStop={stopMessage}
            />
          )}
        </div>

        <div className="flex w-[480px] flex-shrink-0 flex-col">
          <SkillPreviewPanel
            previewData={previewData}
            fileTree={fileTree}
            threadId={threadId}
            isProcessing={isProcessing}
            onSave={() => setShowSaveDialog(true)}
            onRegenerate={handleRegenerate}
          />
        </div>
      </div>

      <SkillSaveDialog
        open={showSaveDialog}
        onOpenChange={setShowSaveDialog}
        previewData={previewData}
        fileTree={fileTree}
        threadId={threadId}
        editSkillId={effectiveEditSkillId}
        onSaved={handleSaved}
      />
    </div>
  )
}
