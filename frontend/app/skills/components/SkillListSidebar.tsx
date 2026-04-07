'use client'

import { Loader2 } from 'lucide-react'
import React from 'react'

import { SearchInput } from '@/components/ui/search-input'
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
        <SearchInput
          placeholder={t('skills.searchCapabilities')}
          className="h-9 border-[var(--border)] bg-[var(--surface-1)] text-xs"
          value={searchQuery}
          onValueChange={onSearchChange}
        />
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
