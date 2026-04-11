'use client'

import { ShieldCheck, Trash2, Folder, Globe } from 'lucide-react'
import React from 'react'

import { Badge } from '@/components/ui/badge'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'
import { Skill } from '@/types'

interface SkillListItemProps {
  skill: Skill
  isSelected: boolean
  onSelect: (skill: Skill) => void
  onDelete: (id: string) => void
}

export const SkillListItem = React.memo(function SkillListItem({
  skill,
  isSelected,
  onSelect,
  onDelete,
}: SkillListItemProps) {
  const { t } = useTranslation()

  return (
    <div
      onClick={() => onSelect(skill)}
      className={cn(
        'group min-w-0 cursor-pointer rounded-xl border p-3 transition-all',
        isSelected
          ? 'border-[var(--skill-brand-100)] bg-[var(--surface-elevated)] shadow-sm ring-1 ring-[var(--skill-brand-50)]'
          : 'border-transparent hover:border-[var(--border)] hover:bg-[var(--surface-elevated)]',
      )}
    >
      <div className="mb-1 flex min-w-0 items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <ShieldCheck size={12} className="shrink-0 text-[var(--skill-brand-600)]" />
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger className="min-w-0 truncate text-left text-sm font-semibold text-[var(--text-primary)]">
                {skill.name}
              </TooltipTrigger>
              <TooltipContent side="top">{skill.name}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          {skill.is_public && (
            <Badge
              variant="outline"
              className="h-3.5 shrink-0 border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] px-1 py-0 text-2xs text-[var(--skill-brand-600)]"
            >
              <Globe size={8} className="mr-0.5" />
              {t('skills.published')}
            </Badge>
          )}
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDelete(skill.id)
          }}
          className="shrink-0 p-1 text-[var(--text-muted)] opacity-0 transition-opacity hover:text-[var(--status-error)] group-hover:opacity-100"
          aria-label="Delete skill"
        >
          <Trash2 size={12} />
        </button>
      </div>
      <p className="line-clamp-2 min-w-0 text-xs text-[var(--text-tertiary)]">
        {skill.description}
      </p>
      {skill.files && skill.files.length > 0 && (
        <div className="mt-1.5 flex items-center gap-1 text-xs text-[var(--text-muted)]">
          <Folder size={10} />
          <span>{skill.files.length} files</span>
        </div>
      )}
    </div>
  )
})
