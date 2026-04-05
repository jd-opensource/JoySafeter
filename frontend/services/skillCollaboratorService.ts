import { apiGet, apiPost, apiPut, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export type CollaboratorRole = 'viewer' | 'editor' | 'publisher' | 'admin'

export interface SkillCollaborator {
  id: string
  skillId: string
  userId: string
  role: CollaboratorRole
  invitedBy: string
  createdAt: string | null
}

// ---------- Normalizer ----------

/** Raw collaborator shape from the API before normalization */
interface BackendCollaborator {
  id: string
  skill_id: string
  user_id: string
  role: CollaboratorRole
  invited_by: string
  created_at: string | null
  [key: string]: unknown
}

function normalizeCollaborator(raw: BackendCollaborator): SkillCollaborator {
  return {
    id: raw.id,
    skillId: raw.skill_id,
    userId: raw.user_id,
    role: raw.role,
    invitedBy: raw.invited_by,
    createdAt: raw.created_at ?? null,
  }
}

// ---------- Service ----------

export const skillCollaboratorService = {
  async listCollaborators(skillId: string): Promise<SkillCollaborator[]> {
    const data = await apiGet<BackendCollaborator[]>(`skills/${skillId}/collaborators`)
    return (Array.isArray(data) ? data : []).map(normalizeCollaborator)
  },

  async addCollaborator(skillId: string, payload: { user_id: string; role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPost<BackendCollaborator>(`skills/${skillId}/collaborators`, payload)
    return normalizeCollaborator(data)
  },

  async updateRole(skillId: string, userId: string, payload: { role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPut<BackendCollaborator>(`skills/${skillId}/collaborators/${userId}`, payload)
    return normalizeCollaborator(data)
  },

  async removeCollaborator(skillId: string, userId: string): Promise<void> {
    await apiDelete<void>(`skills/${skillId}/collaborators/${userId}`)
  },

  async transferOwnership(skillId: string, payload: { new_owner_id: string }): Promise<void> {
    await apiPost<void>(`skills/${skillId}/transfer`, payload)
  },
}
