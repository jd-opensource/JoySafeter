'use client'

/**
 * Agent run artifacts service.
 *
 * List runs, list files, and get download URLs for artifact files
 * produced during an agent run.
 */

import { API_BASE, apiFetch, apiDelete } from '@/lib/api-client'

// ==================== Types ====================

export interface RunInfo {
  run_id: string
  thread_id: string
  user_id: string
  path: string
  started_at?: string
  completed_at?: string
  status?: string
  agent_type?: string
  graph_id?: string
  file_count: number
}

export interface FileInfo {
  name: string
  path: string
  type: 'file' | 'directory'
  size?: number
  content_type?: string
  children?: FileInfo[]
}

export interface ArtifactsRunsResponse {
  runs: RunInfo[]
  success?: boolean
  data?: RunInfo[]
}

export interface ArtifactsFilesResponse {
  files: FileInfo[]
  success?: boolean
  data?: FileInfo[]
}

// ==================== Helpers ====================

function artifactsPath(threadId: string, runId?: string, filePath?: string): string {
  const base = `artifacts/${encodeURIComponent(threadId)}`
  if (!runId) return base
  const run = `${base}/${encodeURIComponent(runId)}`
  if (!filePath) return run
  return `${run}/download/${filePath.split('/').map(encodeURIComponent).join('/')}`
}

/** Build full URL for artifact file download (use with fetch or <a href> with credentials) */
export function getArtifactDownloadUrl(threadId: string, runId: string, filePath: string): string {
  const path = artifactsPath(threadId, runId, filePath)
  return `${API_BASE}/${path}`
}

// ==================== Service ====================

export const artifactService = {
  /**
   * List all runs for a thread (current user's artifacts).
   */
  async listRuns(threadId: string): Promise<RunInfo[]> {
    const url = `${API_BASE}/${artifactsPath(threadId)}/runs`
    const json = await apiFetch<RunInfo[] | ArtifactsRunsResponse>(url)
    // apiFetch auto-unwraps { success, data } → data (the array itself)
    if (Array.isArray(json)) return json
    return json.runs ?? json.data ?? []
  },

  /**
   * List files (tree) for a run.
   */
  async listRunFiles(threadId: string, runId: string): Promise<FileInfo[]> {
    const url = `${API_BASE}/${artifactsPath(threadId, runId)}/files`
    const json = await apiFetch<FileInfo[] | ArtifactsFilesResponse>(url)
    // apiFetch auto-unwraps { success, data } → data (the array itself)
    if (Array.isArray(json)) return json
    return json.files ?? json.data ?? []
  },

  /**
   * Download a file as blob (for preview or save).
   * Uses raw fetch since apiFetch parses JSON; downloads need blob response.
   */
  async downloadFile(threadId: string, runId: string, filePath: string): Promise<Blob> {
    const url = getArtifactDownloadUrl(threadId, runId, filePath)
    const res = await fetch(url, { credentials: 'include' })
    if (!res.ok) throw new Error(`Download failed: ${res.statusText}`)
    return res.blob()
  },

  /**
   * Delete all artifacts for a run.
   */
  async deleteRun(threadId: string, runId: string): Promise<void> {
    const path = artifactsPath(threadId, runId)
    await apiDelete(`${API_BASE}/${path}`)
  },

  getDownloadUrl: getArtifactDownloadUrl,
}
