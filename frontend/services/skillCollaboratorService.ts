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

function normalizeCollaborator(raw: any): SkillCollaborator {
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
    const data = await apiGet<any[]>(`skills/${skillId}/collaborators`)
    return (Array.isArray(data) ? data : []).map(normalizeCollaborator)
  },

  async addCollaborator(skillId: string, payload: { user_id: string; role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPost<any>(`skills/${skillId}/collaborators`, payload)
    return normalizeCollaborator(data)
  },

  async updateRole(skillId: string, userId: string, payload: { role: CollaboratorRole }): Promise<SkillCollaborator> {
    const data = await apiPut<any>(`skills/${skillId}/collaborators/${userId}`, payload)
    return normalizeCollaborator(data)
  },

  async removeCollaborator(skillId: string, userId: string): Promise<void> {
    await apiDelete<any>(`skills/${skillId}/collaborators/${userId}`)
  },

  async transferOwnership(skillId: string, payload: { new_owner_id: string }): Promise<void> {
    await apiPost<any>(`skills/${skillId}/transfer`, payload)
  },
}
