import { parseCredentialId, parseEnvironmentId, parseStorageVolumeId } from '@/types/entity-id'
import type {
  Environment,
  EnvironmentConfig,
  EnvironmentEgressService,
  EnvironmentStorageVolume,
} from '@/types/managed'

type RawEnvironmentStorageVolume = Omit<EnvironmentStorageVolume, 'volume_id'> & {
  volume_id?: string
}

type RawEnvironmentEgressService = Omit<EnvironmentEgressService, 'service_credential_id'> & {
  service_credential_id: string
}

type RawEnvironmentConfig = Omit<
  EnvironmentConfig,
  'secret_refs' | 'egress_services' | 'storage_volumes'
> & {
  secret_refs?: string[]
  egress_services?: RawEnvironmentEgressService[]
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
          secret_refs: raw.config.secret_refs?.map(parseCredentialId),
          egress_services: raw.config.egress_services?.map((service) => ({
            ...service,
            service_credential_id: parseCredentialId(service.service_credential_id),
          })),
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
