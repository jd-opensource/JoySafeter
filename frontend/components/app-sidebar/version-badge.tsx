'use client'

import { useQuery } from '@tanstack/react-query'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { versionService } from '@/services/versionService'

interface VersionBadgeProps {
  isCollapsed?: boolean
}

export function VersionBadge({ isCollapsed = false }: VersionBadgeProps) {
  const { data } = useQuery({
    queryKey: ['app-version'],
    queryFn: () => versionService.getVersion(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })

  if (!data || isCollapsed) return null

  return (
    <div className="px-2 pb-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <p className="cursor-default select-none text-center text-sm text-[var(--text-muted)]">
            v{data.version}
          </p>
        </TooltipTrigger>
        <TooltipContent side="right">
          <div className="space-y-0.5 text-xs">
            <p>Version: {data.version}</p>
            <p>Commit: {data.git_sha}</p>
            <p>Env: {data.environment}</p>
          </div>
        </TooltipContent>
      </Tooltip>
    </div>
  )
}
