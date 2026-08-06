'use client'

import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { managedGet } from '@/lib/api-client'
import { apiResourceSubpath } from '@/lib/managed/api-paths'
import { useTranslation } from '@/lib/i18n'
import {
  hasManagedRequestScope,
  managedRequestOptions,
  useManagedRequestScope,
} from '@/lib/managed/request-scope'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
 *
 * Agents may only reference *published* skill versions — the mutable
 * "draft (working copy)" is intentionally NOT offered here, so an agent
 * can never be pinned to an unpublished, still-changing revision.
 *
 */
export function SkillVersionSelect({
  skillId,
  value,
  onChange,
  enabled = true,
  className,
}: SkillVersionSelectProps) {
  const { t } = useTranslation()
  const managedScope = useManagedRequestScope()

  const { data } = useQuery({
    queryKey: ['skill-versions', managedScope.key, skillId],
    queryFn: () =>
      managedGet<{ data: SkillVersionRecord[] }>(
        apiResourceSubpath('skills', skillId, ['versions'], { limit: 50 }),
        managedRequestOptions(managedScope),
      ),
    enabled: enabled && !!skillId && hasManagedRequestScope(managedScope),
    staleTime: 30_000,
  })

  const versions = useMemo(() => data?.data || [], [data])

  return (
    <Select value={value || 'latest'} onValueChange={onChange}>
      <SelectTrigger className={className || 'h-7 w-40 text-xs'}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="latest">
          {t('managed.skills.version.latest', 'Latest published')}
        </SelectItem>
        {versions.map((v) => (
          <SelectItem key={v.id} value={v.version}>
            v{v.version}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
