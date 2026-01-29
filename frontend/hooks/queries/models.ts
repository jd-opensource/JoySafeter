/**
 * Model Provider & Credential Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiGet, apiPost, apiDelete, apiPatch } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import type {
  ModelProvider,
  ModelCredential,
  ModelInstance,
  AvailableModel,
  CreateCredentialRequest,
  CreateModelInstanceRequest,
  UpdateModelInstanceDefaultRequest,
} from '@/types/models'

import { STALE_TIME } from './constants'


// Re-export types for convenience
export type {
  ModelProvider,
  ModelCredential,
  ModelInstance,
  AvailableModel,
  CreateCredentialRequest,
  CreateModelInstanceRequest,
  UpdateModelInstanceDefaultRequest,
}

const logger = createLogger('ModelQueries')

// API path constants (apiGet/apiPost automatically adds /api/v1 prefix)
const MODEL_PROVIDERS_PATH = 'model-providers'
const MODEL_CREDENTIALS_PATH = 'model-credentials'
const MODELS_PATH = 'models'

// ==================== Query Keys ====================

export const modelKeys = {
  all: ['models'] as const,
  providers: () => [...modelKeys.all, 'providers'] as const,
  provider: (name: string) => [...modelKeys.providers(), name] as const,
  credentials: () => [...modelKeys.all, 'credentials'] as const,
  credential: (id: string) => [...modelKeys.credentials(), id] as const,
  instances: () => [...modelKeys.all, 'instances'] as const,
  available: (type?: string) => [...modelKeys.all, 'available', type] as const,
  chat: () => [...modelKeys.all, 'chat'] as const,
}

// ==================== Query Hooks ====================

export function useModelProviders() {
  return useQuery({
    queryKey: modelKeys.providers(),
    queryFn: async (): Promise<ModelProvider[]> => {
      return await apiGet<ModelProvider[]>(MODEL_PROVIDERS_PATH)
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

export function useModelProvider(providerName: string) {
  return useQuery({
    queryKey: modelKeys.provider(providerName),
    queryFn: async (): Promise<ModelProvider> => {
      return await apiGet<ModelProvider>(`${MODEL_PROVIDERS_PATH}/${providerName}`)
    },
    enabled: !!providerName,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useModelCredentials(workspaceId?: string) {
  return useQuery({
    queryKey: [...modelKeys.credentials(), workspaceId],
    queryFn: async (): Promise<ModelCredential[]> => {
      const params = workspaceId ? `?workspaceId=${workspaceId}` : ''
      return await apiGet<ModelCredential[]>(`${MODEL_CREDENTIALS_PATH}${params}`)
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

export function useModelCredential(credentialId: string) {
  return useQuery({
    queryKey: modelKeys.credential(credentialId),
    queryFn: async (): Promise<ModelCredential> => {
      return await apiGet<ModelCredential>(`${MODEL_CREDENTIALS_PATH}/${credentialId}`)
    },
    enabled: !!credentialId,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
  })
}

export function useAvailableModels(
  modelType: string = 'chat',
  workspaceId?: string,
  options?: { enabled?: boolean }
) {
  return useQuery({
    queryKey: modelKeys.available(modelType),
    queryFn: async (): Promise<AvailableModel[]> => {
      const params = new URLSearchParams({ model_type: modelType })
      if (workspaceId) params.append('workspaceId', workspaceId)
      return await apiGet<AvailableModel[]>(`${MODELS_PATH}?${params.toString()}`)
    },
    enabled: options?.enabled !== false, // 默认 true，但可以设置为 false
    retry: false,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

export function useModelInstances(workspaceId?: string) {
  return useQuery({
    queryKey: [...modelKeys.instances(), workspaceId],
    queryFn: async (): Promise<ModelInstance[]> => {
      const params = workspaceId ? `?workspaceId=${workspaceId}` : ''
      return await apiGet<ModelInstance[]>(`${MODELS_PATH}/instances${params}`)
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

/**
 * Hook to get chat models (simplified interface for agent builder)
 * This is a convenience hook that returns models in a simplified format
 */
export interface ModelOption {
  id: string
  label: string
  provider: string
  provider_name: string
  isAvailable?: boolean
  isDefault?: boolean
}

export function useModels(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: modelKeys.chat(),
    queryFn: async (): Promise<ModelOption[]> => {
      // apiGet automatically unwraps response.data
      const models = await apiGet<Array<{
        id: string
        name: string
        model_type: string
        provider_display_name: string
        provider_name: string
        is_available: boolean
        is_default: boolean
      }>>('models?model_type=chat')
      return (models || []).map((model) => ({
        id: model.id,
        label: model.name,
        provider: model.provider_display_name,
        provider_name: model.provider_name,
        isAvailable: model.is_available,
        isDefault: model.is_default,
      }))
    },
    enabled: options?.enabled !== false, // 默认 true，但可以设置为 false
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

// ==================== Mutation Hooks ====================


export function useCreateCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateCredentialRequest) => {
      const data = await apiPost<ModelCredential>(MODEL_CREDENTIALS_PATH, {
        provider_name: request.provider_name,
        credentials: request.credentials,
        workspaceId: request.workspaceId,
        validate: request.validate !== false,
      })
      logger.info(`Created credential for provider: ${request.provider_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.available() })
    },
  })
}

export function useValidateCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (credentialId: string) => {
      const data = await apiPost<{ is_valid: boolean; error?: string }>(
        `${MODEL_CREDENTIALS_PATH}/${credentialId}/validate`
      )
      logger.info(`Validated credential: ${credentialId}`)
      return data
    },
    onSuccess: (_, credentialId) => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credential(credentialId) })
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.available() })
    },
  })
}

export function useDeleteCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (credentialId: string) => {
      await apiDelete(`${MODEL_CREDENTIALS_PATH}/${credentialId}`)
      logger.info(`Deleted credential: ${credentialId}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.available() })
    },
  })
}

export function useCreateModelInstance() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateModelInstanceRequest) => {
      const data = await apiPost<ModelInstance>(`${MODELS_PATH}/instances`, {
        provider_name: request.provider_name,
        model_name: request.model_name,
        model_type: request.model_type || 'chat',
        model_parameters: request.model_parameters,
        workspaceId: request.workspaceId,
        is_default: request.is_default,
      })
      logger.info(`Created model instance: ${request.model_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
      queryClient.invalidateQueries({ queryKey: modelKeys.available() })
    },
  })
}

export function useUpdateModelInstanceDefault() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: UpdateModelInstanceDefaultRequest) => {
      const data = await apiPatch<ModelInstance>(
        `${MODELS_PATH}/instances/default`,
        {
          provider_name: request.provider_name,
          model_name: request.model_name,
          is_default: request.is_default,
        }
      )
      logger.info(`Updated model instance default status: ${request.model_name} -> ${request.is_default}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
      // Invalidate all available queries (including queries with different modelType)
      queryClient.invalidateQueries({ queryKey: [...modelKeys.all, 'available'] })
    },
  })
}
