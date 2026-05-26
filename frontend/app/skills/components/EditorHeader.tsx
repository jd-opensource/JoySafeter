'use client'

import { Save, Loader2, Globe, Lock, ChevronRight, Terminal } from 'lucide-react'
import React from 'react'

import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

type TabValue = 'editor' | 'versions' | 'collaborators'

interface EditorHeaderProps {
  skillName: string
  activeFilePath: string | null
  activeTab: TabValue
  onTabChange: (tab: TabValue) => void
  isPublic: boolean
  onPublicChange: (checked: boolean) => void
  isSaving: boolean
  onSave: (e?: React.MouseEvent) => void
  hasSelectedSkill: boolean
  onShowApiAccess: () => void
}

export function EditorHeader({
  skillName,
  activeFilePath,
  activeTab,
  onTabChange,
  isPublic,
  onPublicChange,
  isSaving,
  onSave,
  hasSelectedSkill,
  onShowApiAccess,
}: EditorHeaderProps) {
  const { t } = useTranslation()

  return (
    <>
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-2)] px-4 lg:px-6">
        <div className="flex items-center gap-4 lg:gap-6">
          <div className="flex flex-col">
            <h1
              className="line-clamp-1 max-w-[200px] text-sm font-bold leading-tight text-[var(--text-primary)]"
              title={skillName}
            >
              {skillName}
            </h1>
            <div className="flex items-center gap-1.5 font-mono text-xs text-[var(--text-muted)]">
              <ChevronRight size={10} />{' '}
              <span className="max-w-[180px] truncate">{activeFilePath || 'No file selected'}</span>
            </div>
          </div>

          {/* Pill Tab Bar integrated in header */}
          <div className="hidden items-center space-x-1 rounded-lg bg-[var(--surface-3)] p-1 lg:flex">
            {(['editor', 'versions', 'collaborators'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => onTabChange(tab)}
                className={cn(
                  'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                  activeTab === tab
                    ? 'bg-[var(--surface-elevated)] text-[var(--text-primary)] shadow-sm'
                    : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
                )}
              >
                {tab === 'editor' && t('skills.editor')}
                {tab === 'versions' && t('skillVersions.title')}
                {tab === 'collaborators' && t('skillCollaborators.title')}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3 lg:gap-4">
          {/* Access API Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={onShowApiAccess}
            disabled={!hasSelectedSkill}
            className="h-8 gap-1.5 px-3 text-xs"
          >
            <Terminal size={14} />
            <span className="hidden lg:inline">
              {t('skills.accessApi', { defaultValue: 'Access API' })}
            </span>
            <span className="lg:hidden">API</span>
          </Button>

          {/* Publish Toggle */}
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1.5 lg:px-3">
            {isPublic ? (
              <Globe size={14} className="text-[var(--skill-brand)]" />
            ) : (
              <Lock size={14} className="text-[var(--text-muted)]" />
            )}
            <span className="hidden text-xs text-[var(--text-secondary)] lg:inline">
              {t('skills.publishToStore')}
            </span>
            <Switch
              checked={isPublic}
              onCheckedChange={onPublicChange}
              className="scale-75 data-[state=checked]:bg-[var(--skill-brand)] lg:scale-100"
            />
          </div>

          <Button
            onClick={onSave}
            disabled={isSaving}
            className="h-8 gap-1.5 bg-[var(--skill-brand-600)] px-3 text-xs shadow-sm hover:bg-[var(--skill-brand-700)] disabled:cursor-not-allowed disabled:opacity-50 lg:gap-2 lg:px-4"
          >
            {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            <span className="hidden lg:inline">{t('skills.saveChanges')}</span>
            <span className="lg:hidden">Save</span>
          </Button>
        </div>
      </div>

      {/* Fallback Tab Bar for smaller screens within the pane */}
      <div className="hide-scrollbar flex overflow-x-auto border-b border-[var(--border)] px-2 lg:hidden">
        {(['editor', 'versions', 'collaborators'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => onTabChange(tab)}
            className={cn(
              'whitespace-nowrap px-3 py-2 text-xs font-medium transition-colors',
              activeTab === tab
                ? 'border-b-2 border-[var(--brand-500)] text-[var(--brand-600)]'
                : 'text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
            )}
          >
            {tab === 'editor' && t('skills.editor')}
            {tab === 'versions' && t('skillVersions.title')}
            {tab === 'collaborators' && t('skillCollaborators.title')}
          </button>
        ))}
      </div>
    </>
  )
}
