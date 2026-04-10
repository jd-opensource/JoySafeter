'use client'

import { Loader2, Check, Search, X, Sparkles, Tag } from 'lucide-react'
import { useState, useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useSkills } from '@/hooks/queries/skills'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

interface SkillsFieldProps {
  value: unknown
  onChange: (val: unknown) => void
}

interface SkillOption {
  id: string
  name: string
  description: string
  tags: string[]
}

export function SkillsField({ value, onChange }: SkillsFieldProps) {
  const { t } = useTranslation()

  const [searchQuery, setSearchQuery] = useState('')

  // Use React Query hook for skills (with caching and request deduplication)
  const { data: skillsData = [], isLoading } = useSkills(true)

  // Value is an array of skill IDs
  const selectedSkillIds = useMemo(() => {
    if (Array.isArray(value)) {
      return value.filter((v): v is string => typeof v === 'string')
    }
    return []
  }, [value])

  // Convert Skill[] to SkillOption[]
  const availableSkills: SkillOption[] = useMemo(() => {
    return (skillsData || []).map((s) => ({
      id: s.id,
      name: s.name,
      description: s.description,
      tags: s.tags || [],
    }))
  }, [skillsData])

  const toggleSkill = (skillId: string) => {
    const current = new Set(selectedSkillIds)
    if (current.has(skillId)) {
      current.delete(skillId)
    } else {
      current.add(skillId)
    }
    onChange(Array.from(current))
  }

  const removeSkill = (skillId: string) => {
    const filtered = selectedSkillIds.filter((id) => id !== skillId)
    onChange(filtered)
  }

  const filteredSkills = useMemo(() => {
    if (!searchQuery.trim()) return availableSkills
    const q = searchQuery.toLowerCase()
    return availableSkills.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        s.description?.toLowerCase().includes(q) ||
        s.tags.some((tag) => tag.toLowerCase().includes(q)),
    )
  }, [availableSkills, searchQuery])

  const getSkillName = (id: string) => availableSkills.find((s) => s.id === id)?.name || id

  return (
    <div className="space-y-2">
      {/* 1. Selected Skills Tags */}
      {selectedSkillIds.length > 0 && (
        <div className="mb-2.5 flex flex-wrap gap-1.5">
          {selectedSkillIds.map((id) => (
            <Badge
              key={id}
              variant="secondary"
              className="gap-1 border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] py-0.5 pl-2 pr-1 text-2xs text-[var(--skill-brand-700)] shadow-sm"
            >
              <Sparkles size={10} className="shrink-0" />
              {getSkillName(id)}
              <button
                onClick={() => removeSkill(id)}
                className="ml-0.5 rounded-full p-0.5 transition-colors hover:bg-[var(--skill-brand-200)]"
              >
                <X size={10} />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* 2. Search Area */}
      <div className="group relative">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] transition-colors group-focus-within:text-[var(--skill-brand)]"
        />
        <Input
          placeholder={t('workspace.searchSkills', { defaultValue: 'Search skills...' })}
          className="h-8 border-[var(--border)] bg-[var(--surface-elevated)] pl-8 text-app-xs shadow-none focus-visible:ring-[var(--skill-brand-100)]"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* 3. Available Skills List */}
      <div className="custom-scrollbar mt-1 max-h-[200px] divide-y divide-[var(--border-muted)] overflow-y-auto rounded-lg border border-[var(--border-muted)] bg-[var(--surface-2)]">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center gap-2 p-4 text-[var(--text-muted)]">
            <Loader2 size={14} className="animate-spin text-[var(--skill-brand)]" />
            <span className="text-2xs font-medium tracking-tight">
              {t('workspace.loadingSkills', { defaultValue: 'Loading skills...' })}
            </span>
          </div>
        ) : filteredSkills.length === 0 ? (
          <div className="p-6 text-center text-2xs italic text-[var(--text-muted)]">
            {searchQuery
              ? t('workspace.noMatchingSkills', { defaultValue: 'No matching skills found' })
              : t('workspace.noSkillsAvailable', { defaultValue: 'No skills available' })}
          </div>
        ) : (
          filteredSkills.map((skill) => {
            const isSelected = selectedSkillIds.includes(skill.id)

            return (
              <div
                key={skill.id}
                onClick={() => toggleSkill(skill.id)}
                className={cn(
                  'group flex cursor-pointer items-start justify-between p-2.5 transition-all hover:bg-[var(--surface-elevated)]',
                  isSelected ? 'bg-[var(--surface-elevated)]' : '',
                )}
              >
                <div className="flex min-w-0 flex-1 flex-col pr-2">
                  <div className="flex items-center gap-1.5">
                    <Sparkles
                      size={11}
                      className={isSelected ? 'text-[var(--skill-brand)]' : 'text-[var(--text-subtle)]'}
                    />
                    <span
                      className={cn(
                        'truncate text-app-xs font-medium',
                        isSelected ? 'text-[var(--skill-brand-700)]' : 'text-[var(--text-secondary)]',
                      )}
                    >
                      {skill.name}
                    </span>
                  </div>
                  {skill.description && (
                    <p className="mt-0.5 line-clamp-2 truncate pl-4 text-micro text-[var(--text-muted)]">
                      {skill.description}
                    </p>
                  )}
                  {skill.tags.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1 pl-4">
                      {skill.tags.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex items-center gap-0.5 rounded bg-[var(--surface-3)] px-1.5 py-0.5 text-xxs text-[var(--text-tertiary)]"
                        >
                          <Tag size={8} />
                          {tag}
                        </span>
                      ))}
                      {skill.tags.length > 3 && (
                        <span className="text-xxs text-[var(--text-muted)]">+{skill.tags.length - 3}</span>
                      )}
                    </div>
                  )}
                </div>
                <div
                  className={cn(
                    'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border shadow-sm transition-all',
                    isSelected
                      ? 'border-[var(--skill-brand-600)] bg-[var(--skill-brand)] text-white'
                      : 'border-[var(--border)] bg-[var(--surface-elevated)] group-hover:border-[var(--border-strong)]',
                  )}
                >
                  {isSelected && <Check size={10} strokeWidth={3} />}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* 4. Info text */}
      <p className="mt-1 text-micro italic text-[var(--text-muted)]">
        {t('workspace.skillsHint', {
          defaultValue:
            'Skills provide specialized instructions. The agent can load skill content on-demand.',
        })}
      </p>
    </div>
  )
}
