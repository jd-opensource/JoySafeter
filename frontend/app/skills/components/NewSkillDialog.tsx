import { Wand2, FileCode, FolderOpen } from 'lucide-react'
import React from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useTranslation } from '@/lib/i18n'

interface NewSkillDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelectOption: (option: 'ai' | 'manual' | 'import') => void
}

export function NewSkillDialog({ open, onOpenChange, onSelectOption }: NewSkillDialogProps) {
  const { t } = useTranslation()

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md md:max-w-xl">
        <DialogHeader className="mb-4">
          <DialogTitle className="text-xl">{t('skills.newSkill', 'Create New Skill')}</DialogTitle>
          <DialogDescription>
            {t('skills.chooseCreationMethod', 'Choose how you want to build your new skill.')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-3">
          {/* AI Create */}
          <button
            onClick={() => {
              onSelectOption('ai')
              onOpenChange(false)
            }}
            className="group flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-transparent bg-[var(--skill-brand-50)] p-6 text-center transition-all hover:border-[var(--skill-brand)] hover:shadow-md"
          >
            <div className="rounded-full bg-[var(--skill-brand-100)] p-4 text-[var(--skill-brand-600)] transition-transform group-hover:scale-110">
              <Wand2 size={32} />
            </div>
            <div>
              <h3 className="font-semibold text-[var(--skill-brand-700)]">{t('skills.aiCreate', 'AI Create')}</h3>
              <p className="mt-1 text-xs text-[var(--skill-brand-600)] opacity-80">
                {t('skills.aiCreateDesc', 'Generate automatically via chat.')}
              </p>
            </div>
          </button>

          {/* Manual Entry */}
          <button
            onClick={() => {
              onSelectOption('manual')
              onOpenChange(false)
            }}
            className="group flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6 text-center shadow-sm transition-all hover:border-blue-500 hover:shadow-md"
          >
            <div className="rounded-full bg-[var(--surface-1)] p-4 text-[var(--text-tertiary)] transition-transform group-hover:scale-110 group-hover:bg-blue-50 group-hover:text-blue-500">
              <FileCode size={32} />
            </div>
            <div>
              <h3 className="font-semibold text-[var(--text-primary)]">{t('skills.manual', 'Blank Template')}</h3>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {t('skills.manualDesc', 'Start from scratch with a basic Markdown template.')}
              </p>
            </div>
          </button>

          {/* Local Import */}
          <button
            onClick={() => {
              onSelectOption('import')
              onOpenChange(false)
            }}
            className="group flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6 text-center shadow-sm transition-all hover:border-orange-500 hover:shadow-md"
          >
            <div className="rounded-full bg-[var(--surface-1)] p-4 text-[var(--text-tertiary)] transition-transform group-hover:scale-110 group-hover:bg-orange-50 group-hover:text-orange-500">
              <FolderOpen size={32} />
            </div>
            <div>
              <h3 className="font-semibold text-[var(--text-primary)]">{t('skills.importFromLocal', 'Import Folder')}</h3>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                {t('skills.importDesc', 'Upload an existing folder of skill files.')}
              </p>
            </div>
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
