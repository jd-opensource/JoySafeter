'use client'

import { Search, Loader2 } from 'lucide-react'
import React from 'react'

import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'
import { Skill } from '@/types'

import { SkillListItem } from './SkillListItem'

interface SkillListSidebarProps {
  searchQuery: string
  onSearchChange: (query: string) => void
  loading: boolean
  filteredSkills: Skill[]
  selectedSkillId: string | undefined
  onSelectSkill: (skill: Skill) => void
  onDeleteSkill: (id: string) => void
}

export function SkillListSidebar({
  searchQuery,
  onSearchChange,
  loading,
  filteredSkills,
  selectedSkillId,
  onSelectSkill,
  onDeleteSkill,
}: SkillListSidebarProps) {
  const { t } = useTranslation()

  return (
    <>
      <div className="border-b border-[var(--border-muted)] bg-[var(--surface-2)] p-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" size={14} />
          <Input
            placeholder={t('skills.searchCapabilities')}
            className="h-9 border-[var(--border)] bg-[var(--surface-1)] pl-9 text-xs"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>
      </div>

      <div className="custom-scrollbar flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="flex justify-center p-8">
            <Loader2 className="animate-spin text-[var(--text-subtle)]" />
          </div>
        ) : (
          <div className="space-y-1">
            {filteredSkills.map((skill) => (
              <SkillListItem
                key={skill.id}
                skill={skill}
                isSelected={selectedSkillId === skill.id}
                onSelect={onSelectSkill}
                onDelete={onDeleteSkill}
              />
            ))}
          </div>
        )}
      </div>
    </>
  )
}
