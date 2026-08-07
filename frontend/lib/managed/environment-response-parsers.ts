import { parseEnvironmentId, parseStorageVolumeId } from '@/types/entity-id'
import type { Environment, EnvironmentConfig, EnvironmentStorageVolume } from '@/types/managed'

type RawEnvironmentStorageVolume = Omit<EnvironmentStorageVolume, 'volume_id'> & {
  volume_id?: string
}

type RawEnvironmentConfig = Omit<EnvironmentConfig, 'storage_volumes'> & {
  storage_volumes?: RawEnvironmentStorageVolume[]
}

type RawEnvironment = Omit<Environment, 'id' | 'config'> & {
  id: string
  config?: RawEnvironmentConfig
}

export function parseEnvironmentResponse(response: unknown): Environment {
  const raw = response as RawEnvironment
  return {
    ...raw,
    id: parseEnvironmentId(raw.id),
    config: raw.config
      ? {
          ...raw.config,
          storage_volumes: raw.config.storage_volumes?.map((volume) => ({
            ...volume,
            volume_id:
              volume.volume_id === undefined ? undefined : parseStorageVolumeId(volume.volume_id),
          })),
        }
      : undefined,
  }
}

export function parseEnvironmentListResponse(response: RawEnvironment[]): Environment[] {
  return response.map(parseEnvironmentResponse)
}
