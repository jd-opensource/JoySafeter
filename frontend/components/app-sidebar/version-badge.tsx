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
          <p className="text-center text-[10px] text-[var(--text-muted)] cursor-default select-none">
            v{data.version}
          </p>
        </TooltipTrigger>
        <TooltipContent side="right">
          <div className="text-xs space-y-0.5">
            <p>Version: {data.version}</p>
            <p>Commit: {data.git_sha}</p>
            <p>Env: {data.environment}</p>
          </div>
        </TooltipContent>
      </Tooltip>
    </div>
  )
}
