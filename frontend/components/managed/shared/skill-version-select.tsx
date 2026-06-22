'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { managedGet } from '@/lib/api-client'
import { stripIdPrefix } from '@/lib/managed/id'
import { useTranslation } from '@/lib/i18n'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { SkillVersionRecord } from '@/types/managed'

interface SkillVersionSelectProps {
  /** Skill id (may include the "skill_" prefix). */
  skillId: string
  /** The currently selected version keyword or semver string. */
  value: string
  onChange: (next: string) => void
  /** Whether the version list should be fetched. Defaults to true. */
  enabled?: boolean
  /** Optional className for the trigger. */
  className?: string
}

/**
 * Per-skill version selector. Options:
 * - "latest" → latest published version (resolved by backend)
 * - each published "x.y.z"
 * - "draft" → current mutable working copy
 *
 * Keeps the displayed value valid even if `value` doesn't match a published
 * version (renders the raw value as a one-off entry).
 */
export function SkillVersionSelect({ skillId, value, onChange, enabled = true, className }: SkillVersionSelectProps) {
  const { t } = useTranslation()

  const { data } = useQuery({
    queryKey: ['skill-versions', skillId],
    queryFn: () => managedGet<{ data: SkillVersionRecord[] }>(
      `/skills/${stripIdPrefix(skillId)}/versions?limit=50`,
    ),
    enabled: enabled && !!skillId,
    staleTime: 30_000,
  })

  const versions = useMemo(() => data?.data || [], [data])

  const knownValues = useMemo(
    () => new Set(['latest', 'draft', ...versions.map((v) => v.version)]),
    [versions],
  )

  return (
    <Select value={value || 'latest'} onValueChange={onChange}>
      <SelectTrigger className={className || 'h-7 w-40 text-xs'}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="latest">{t('managed.skills.version.latest', 'Latest published')}</SelectItem>
        {versions.map((v) => (
          <SelectItem key={v.id} value={v.version}>
            v{v.version}
          </SelectItem>
        ))}
        <SelectItem value="draft">{t('managed.skills.version.draft', 'Draft (working copy)')}</SelectItem>
        {/* If the agent already references a version no longer in the published list, keep it selectable */}
        {value && !knownValues.has(value) && (
          <SelectItem value={value}>v{value} (missing)</SelectItem>
        )}
      </SelectContent>
    </Select>
  )
}
