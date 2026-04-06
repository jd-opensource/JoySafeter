import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { skillKeys } from './skills'
import { skillCollaboratorService } from '@/services/skillCollaboratorService'
import type { SkillCollaborator, SkillOwnerInfo, CollaboratorRole } from '@/services/skillCollaboratorService'

export { type SkillCollaborator, type SkillOwnerInfo, type CollaboratorRole } from '@/services/skillCollaboratorService'

export const skillCollaboratorKeys = {
  all: ['skill-collaborators'] as const,
  list: (skillId: string) => [...skillCollaboratorKeys.all, 'list', skillId] as const,
}

export function useSkillCollaborators(skillId: string) {
  return useQuery({
    queryKey: skillCollaboratorKeys.list(skillId),
    queryFn: () => skillCollaboratorService.listCollaborators(skillId),
    enabled: !!skillId,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useAddCollaborator(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { email: string; role: CollaboratorRole }) =>
      skillCollaboratorService.addCollaborator(skillId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useUpdateCollaboratorRole(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: CollaboratorRole }) =>
      skillCollaboratorService.updateRole(skillId, userId, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useRemoveCollaborator(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) =>
      skillCollaboratorService.removeCollaborator(skillId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
    },
  })
}

export function useTransferOwnership(skillId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (newOwnerId: string) =>
      skillCollaboratorService.transferOwnership(skillId, { new_owner_id: newOwnerId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: skillCollaboratorKeys.list(skillId) })
      queryClient.invalidateQueries({ queryKey: skillKeys.all })
    },
  })
}
