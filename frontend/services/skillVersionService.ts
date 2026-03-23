import { apiGet, apiPost, apiDelete } from '@/lib/api-client'

// ---------- Types ----------

export interface SkillVersionSummary {
  version: string
  releaseNotes: string | null
  publishedById: string
  publishedAt: string | null
}

export interface SkillVersionFile {
  id: string
  versionId: string
  path: string
  fileName: string
  fileType: string
  content: string | null
  storageType: string
  storageKey: string | null
  size: number
}

export interface SkillVersion {
  id: string
  skillId: string
  version: string
  releaseNotes: string | null
  skillName: string
  skillDescription: string
  content: string
  tags: string[]
  metadata: Record<string, unknown>
  allowedTools: string[]
  compatibility: string | null
  license: string | null
  publishedById: string
  publishedAt: string | null
  createdAt: string | null
  files: SkillVersionFile[] | null
}

// ---------- Normalizers ----------

function normalizeVersionSummary(raw: any): SkillVersionSummary {
  return {
    version: raw.version,
    releaseNotes: raw.release_notes ?? null,
    publishedById: raw.published_by_id,
    publishedAt: raw.published_at ?? null,
  }
}

function normalizeVersion(raw: any): SkillVersion {
  return {
    id: raw.id,
    skillId: raw.skill_id,
    version: raw.version,
    releaseNotes: raw.release_notes ?? null,
    skillName: raw.skill_name,
    skillDescription: raw.skill_description,
    content: raw.content,
    tags: raw.tags ?? [],
    metadata: raw.metadata ?? {},
    allowedTools: raw.allowed_tools ?? [],
    compatibility: raw.compatibility ?? null,
    license: raw.license ?? null,
    publishedById: raw.published_by_id,
    publishedAt: raw.published_at ?? null,
    createdAt: raw.created_at ?? null,
    files: raw.files?.map((f: any) => ({
      id: f.id,
      versionId: f.version_id,
      path: f.path,
      fileName: f.file_name,
      fileType: f.file_type,
      content: f.content ?? null,
      storageType: f.storage_type,
      storageKey: f.storage_key ?? null,
      size: f.size ?? 0,
    })) ?? null,
  }
}

// ---------- Service ----------

export const skillVersionService = {
  async listVersions(skillId: string): Promise<SkillVersionSummary[]> {
    const data = await apiGet<any[]>(`skills/${skillId}/versions`)
    return (Array.isArray(data) ? data : []).map(normalizeVersionSummary)
  },

  async getVersion(skillId: string, version: string): Promise<SkillVersion> {
    const data = await apiGet<any>(`skills/${skillId}/versions/${version}`)
    return normalizeVersion(data)
  },

  async getLatestVersion(skillId: string): Promise<SkillVersion> {
    const data = await apiGet<any>(`skills/${skillId}/versions/latest`)
    return normalizeVersion(data)
  },

  async publishVersion(skillId: string, payload: { version: string; release_notes?: string }): Promise<SkillVersion> {
    const data = await apiPost<any>(`skills/${skillId}/versions`, payload)
    return normalizeVersion(data)
  },

  async deleteVersion(skillId: string, version: string): Promise<void> {
    await apiDelete<any>(`skills/${skillId}/versions/${version}`)
  },

  async restoreDraft(skillId: string, payload: { version: string }): Promise<any> {
    return await apiPost<any>(`skills/${skillId}/restore`, payload)
  },
}
