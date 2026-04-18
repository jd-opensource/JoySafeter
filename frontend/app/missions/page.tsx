'use client'

import { Kanban, List, Loader2, Plus, Target } from 'lucide-react'
import { useSearchParams, useRouter } from 'next/navigation'
import { useCallback, useMemo, useState } from 'react'

import { MissionBoard } from '@/components/missions/mission-board'
import { MissionCreateDialog } from '@/components/missions/mission-create-dialog'
import { MissionDetailPanel } from '@/components/missions/mission-detail-panel'
import { MissionListView } from '@/components/missions/mission-list-view'
import { Button } from '@/components/ui/button'
import { useAgentProfiles } from '@/hooks/queries/agentProfiles'
import { useMissions } from '@/hooks/queries/missions'
import { useWorkspaces } from '@/hooks/queries/workspaces'
import { cn } from '@/lib/utils'

type ViewMode = 'board' | 'list'

export default function MissionsPage() {
  const [viewMode, setViewMode] = useState<ViewMode>('board')
  const searchParams = useSearchParams()
  const router = useRouter()
  const selectedMissionId = searchParams.get('mission')

  const setSelectedMissionId = useCallback(
    (id: string | null) => {
      const params = new URLSearchParams(searchParams.toString())
      if (id) {
        params.set('mission', id)
      } else {
        params.delete('mission')
      }
      router.replace(`/missions?${params.toString()}`, { scroll: false })
    },
    [searchParams, router],
  )

  const { data: workspaces = [], isLoading: isWorkspacesLoading } = useWorkspaces()
  const workspaceId = workspaces[0]?.id ?? ''

  const { data: missions = [], isLoading: isMissionsLoading } = useMissions(workspaceId)
  const { data: agents = [] } = useAgentProfiles(workspaceId, { enabled: Boolean(workspaceId) })

  const agentsMap = useMemo(
    () => Object.fromEntries(agents.map((a) => [a.id, a.name])),
    [agents],
  )

  const isLoading = isWorkspacesLoading || isMissionsLoading

  return (
    <div className="flex h-full flex-col bg-[var(--bg)]">
      <div className="border-b border-[var(--border)] bg-[var(--surface-elevated)] px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Target className="h-5 w-5 text-[var(--skill-brand-600)]" />
            <h1 className="text-lg font-semibold text-[var(--text-primary)]">Missions</h1>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-0.5">
              <button
                type="button"
                onClick={() => setViewMode('board')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  viewMode === 'board'
                    ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                )}
                aria-label="Board view"
              >
                <Kanban className="h-3.5 w-3.5" />
                Board
              </button>
              <button
                type="button"
                onClick={() => setViewMode('list')}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  viewMode === 'list'
                    ? 'bg-[var(--surface-5)] text-[var(--text-primary)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text-secondary)]',
                )}
                aria-label="List view"
              >
                <List className="h-3.5 w-3.5" />
                List
              </button>
            </div>

            {workspaceId && (
              <MissionCreateDialog
                workspaceId={workspaceId}
                trigger={
                  <Button size="sm">
                    <Plus className="h-4 w-4" />
                    New Mission
                  </Button>
                }
              />
            )}
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        {isLoading ? (
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[var(--text-muted)]" />
          </div>
        ) : viewMode === 'board' ? (
          <MissionBoard missions={missions} workspaceId={workspaceId} agentsMap={agentsMap} onSelectMission={setSelectedMissionId} />
        ) : (
          <MissionListView missions={missions} agentsMap={agentsMap} onSelectMission={setSelectedMissionId} />
        )}
      </div>

      {selectedMissionId && workspaceId && (
        <MissionDetailPanel
          missionId={selectedMissionId}
          workspaceId={workspaceId}
          onClose={() => setSelectedMissionId(null)}
        />
      )}
    </div>
  )
}
