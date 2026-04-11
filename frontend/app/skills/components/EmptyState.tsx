'use client'

import { ShieldCheck, Wand2, FileCode, FolderOpen } from 'lucide-react'
import Link from 'next/link'
import React from 'react'

import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/i18n'

interface EmptyStateProps {
  onNewSkillManual: () => void
  onImportLocal: () => void
}

export function EmptyState({ onNewSkillManual, onImportLocal }: EmptyStateProps) {
  const { t } = useTranslation()

  return (
    <div className="flex flex-1 flex-col items-center justify-center bg-[var(--surface-1)] text-[var(--text-muted)]">
      <div className="mb-6 rounded-full border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-8 shadow-xl">
        <ShieldCheck size={48} className="text-[var(--skill-brand-200)]" />
      </div>
      <h3 className="text-sm font-bold text-[var(--text-primary)]">{t('skills.chooseCreationMethod')}</h3>
      <p className="mt-1 text-xs text-[var(--text-muted)]">{t('skills.populateSkillsLibrary')}</p>
      <div className="mt-8 flex max-w-lg flex-wrap justify-center gap-3">
        <Link href="/skills/creator">
          <Button className="gap-2 bg-[var(--skill-brand-600)] text-white shadow-sm hover:bg-[var(--skill-brand-700)]">
            <Wand2 size={16} /> {t('skills.aiCreate', 'AI Create')}
          </Button>
        </Link>
        <Button variant="outline" onClick={onNewSkillManual} className="gap-2">
          <FileCode size={16} /> {t('skills.manual')}
        </Button>
        <Button
          onClick={onImportLocal}
          variant="outline"
          className="gap-2 hover:bg-[var(--surface-2)]"
        >
          <FolderOpen size={16} /> {t('skills.importFromLocal')}
        </Button>
      </div>

      {/* Skill Structure Info */}
      <div className="mt-12 max-w-md rounded-xl border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6 text-left shadow-sm">
        <h4 className="mb-3 text-xs font-bold text-[var(--text-secondary)]">Skill Structure</h4>
        <pre className="font-mono text-xs leading-relaxed text-[var(--text-tertiary)]">
          {`skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description)
│   └── Markdown instructions
└── Any files/folders (optional)
    └── Organize as you like!`}
        </pre>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          You can use any directory structure. Only SKILL.md is required.
        </p>
      </div>
    </div>
  )
}
