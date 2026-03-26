import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { agentService } from '@/app/workspace/[workspaceId]/[agentId]/services/agentService'
import { runService, type AgentListResponse, type RunListResponse, type RunSummary } from '@/services/runService'

import { STALE_TIME } from './constants'
import { useWorkspaces } from './workspaces'

export const runKeys = {
  all: ['runs'] as const,
  list: (filters?: { runType?: string; agentName?: string; status?: string; search?: string; limit?: number }) =>
    [
      ...runKeys.all,
      'list',
      filters?.runType || '',
      filters?.agentName || '',
      filters?.status || '',
      filters?.search || '',
      filters?.limit || 50,
    ] as const,
  agents: () => [...runKeys.all, 'agents'] as const,
  activeSkillCreator: (workspaceId: string) =>
    [...runKeys.all, 'active-skill-creator', workspaceId] as const,
}

const SKILL_CREATOR_GRAPH_NAME = 'Skill Creator'

async function findSkillCreatorGraphId(workspaceId: string): Promise<string | null> {
  const graphs = await agentService.listGraphs(workspaceId)
  const match = graphs.find((graph) => graph.name === SKILL_CREATOR_GRAPH_NAME)
  return match?.id || null
}

export function useActiveSkillCreatorRun() {
  const { data: workspaces = [], isLoading: workspacesLoading } = useWorkspaces()
  const personalWorkspace = workspaces.find((workspace) => workspace.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const query = useQuery<RunSummary | null>({
    queryKey: runKeys.activeSkillCreator(workspaceId),
    enabled: Boolean(workspaceId),
    queryFn: async () => {
      const graphId = await findSkillCreatorGraphId(workspaceId)
      if (!graphId) {
        return null
      }
      return runService.findActiveRun({ agentName: 'skill_creator', graphId })
    },
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  })

  return {
    ...query,
    isLoading: workspacesLoading || query.isLoading,
  }
}

export function useAgents() {
  return useQuery<AgentListResponse>({
    queryKey: runKeys.agents(),
    queryFn: () => runService.listAgents(),
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  })
}

export function useRuns(filters?: {
  runType?: string
  agentName?: string
  status?: string
  search?: string
  limit?: number
}) {
  return useQuery<RunListResponse>({
    queryKey: runKeys.list(filters),
    queryFn: () =>
      runService.listRuns({
        runType: filters?.runType,
        agentName: filters?.agentName,
        status: filters?.status,
        search: filters?.search,
        limit: filters?.limit,
      }),
    staleTime: STALE_TIME.SHORT,
    refetchInterval: 15000,
    refetchOnWindowFocus: true,
  })
}

export function useCancelRun() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (runId: string) => runService.cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: runKeys.all })
    },
  })
}
