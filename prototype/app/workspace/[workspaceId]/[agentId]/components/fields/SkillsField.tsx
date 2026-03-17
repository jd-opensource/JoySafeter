'use client'

import { Loader2, Check, Search, X, Sparkles, Tag } from 'lucide-react'
import React, { useState, useMemo } from 'react'

import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useSkills } from '@/hooks/queries/skills'
import { cn } from '@/lib/core/utils/cn'
import { useTranslation } from '@/lib/i18n'

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

export const SkillsField: React.FC<SkillsFieldProps> = ({ value, onChange }) => {
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
        s.tags.some((tag) => tag.toLowerCase().includes(q))
    )
  }, [availableSkills, searchQuery])

  const getSkillName = (id: string) =>
    availableSkills.find((s) => s.id === id)?.name || id

  return (
    <div className="space-y-2">
      {/* 1. Selected Skills Tags */}
      {selectedSkillIds.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2.5">
          {selectedSkillIds.map((id) => (
            <Badge
              key={id}
              variant="secondary"
              className="pl-2 pr-1 py-0.5 gap-1 text-[10px] bg-amber-50 text-amber-700 border-amber-200 shadow-sm"
            >
              <Sparkles size={10} className="shrink-0" />
              {getSkillName(id)}
              <button
                onClick={() => removeSkill(id)}
                className="ml-0.5 p-0.5 hover:bg-amber-200 rounded-full transition-colors"
              >
                <X size={10} />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* 2. Search Area */}
      <div className="relative group">
        <Search
          size={13}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-amber-500 transition-colors"
        />
        <Input
          placeholder={t('workspace.searchSkills', { defaultValue: 'Search skills...' })}
          className="pl-8 h-8 text-[11px] border-gray-200 bg-white shadow-none focus-visible:ring-amber-100"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>

      {/* 3. Available Skills List */}
      <div className="max-h-[200px] overflow-y-auto custom-scrollbar border border-gray-100 rounded-lg divide-y divide-gray-50 bg-gray-50/30 mt-1">
        {isLoading ? (
          <div className="p-4 flex flex-col items-center justify-center gap-2 text-gray-400">
            <Loader2 size={14} className="animate-spin text-amber-500" />
            <span className="text-[10px] font-medium tracking-tight">
              {t('workspace.loadingSkills', { defaultValue: 'Loading skills...' })}
            </span>
          </div>
        ) : filteredSkills.length === 0 ? (
          <div className="p-6 text-center text-[10px] text-gray-400 italic">
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
                  'p-2.5 flex items-start justify-between cursor-pointer transition-all hover:bg-white group',
                  isSelected ? 'bg-white' : ''
                )}
              >
                <div className="flex flex-col min-w-0 pr-2 flex-1">
                  <div className="flex items-center gap-1.5">
                    <Sparkles
                      size={11}
                      className={isSelected ? 'text-amber-500' : 'text-gray-300'}
                    />
                    <span
                      className={cn(
                        'text-[11px] font-medium truncate',
                        isSelected ? 'text-amber-700' : 'text-gray-600'
                      )}
                    >
                      {skill.name}
                    </span>
                  </div>
                  {skill.description && (
                    <p className="text-[9px] text-gray-400 truncate mt-0.5 pl-4 line-clamp-2">
                      {skill.description}
                    </p>
                  )}
                  {skill.tags.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1 pl-4">
                      {skill.tags.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="inline-flex items-center gap-0.5 text-[8px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded"
                        >
                          <Tag size={8} />
                          {tag}
                        </span>
                      ))}
                      {skill.tags.length > 3 && (
                        <span className="text-[8px] text-gray-400">
                          +{skill.tags.length - 3}
                        </span>
                      )}
                    </div>
                  )}
                </div>
                <div
                  className={cn(
                    'w-4 h-4 rounded-full border flex items-center justify-center transition-all shrink-0 shadow-sm mt-0.5',
                    isSelected
                      ? 'bg-amber-500 border-amber-600 text-white'
                      : 'border-gray-200 bg-white group-hover:border-gray-300'
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
      <p className="text-[9px] text-gray-400 italic mt-1">
        {t('workspace.skillsHint', {
          defaultValue:
            'Skills provide specialized instructions. The agent can load skill content on-demand.',
        })}
      </p>
    </div>
  )
}
