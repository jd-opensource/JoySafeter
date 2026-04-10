import { apiGet } from '@/lib/api-client'

export interface VersionInfo {
  version: string
  git_sha: string
  environment: string
}

export const versionService = {
  getVersion: () => apiGet<VersionInfo>('version'),
}
