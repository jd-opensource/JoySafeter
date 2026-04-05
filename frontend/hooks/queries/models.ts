/**
 * Model Provider & Credential Queries
 *
 * Follow project standards:
 * - Use camelCase for types
 * - API response: { success: true, data: {...} }
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'

import { apiGet, apiPost, apiDelete, apiPatch } from '@/lib/api-client'
import { createLogger } from '@/lib/logs/console/logger'
import type {
  ModelProvider,
  ModelCredential,
  ModelInstance,
  AvailableModel,
  CreateCredentialRequest,
  CreateCustomProviderRequest,
  CreateCustomProviderResponse,
  CreateModelInstanceRequest,
  UpdateModelInstanceRequest,
  UpdateProviderDefaultsRequest,
  ModelsOverview,
  ModelUsageStats,
} from '@/types/models'

import { STALE_TIME } from './constants'

// Re-export types for convenience
export type {
  ModelProvider,
  ModelCredential,
  ModelInstance,
  AvailableModel,
  CreateCredentialRequest,
  CreateCustomProviderRequest,
  CreateCustomProviderResponse,
  CreateModelInstanceRequest,
  UpdateModelInstanceRequest,
  UpdateProviderDefaultsRequest,
  ModelsOverview,
  ModelUsageStats,
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
  overview: () => [...modelKeys.all, 'overview'] as const,
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

export function useModelCredentials() {
  return useQuery({
    queryKey: modelKeys.credentials(),
    queryFn: async (): Promise<ModelCredential[]> => {
      return await apiGet<ModelCredential[]>(MODEL_CREDENTIALS_PATH)
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.STANDARD,
    placeholderData: keepPreviousData,
  })
}

/** Max length for validation_error tooltip to avoid huge title attributes */
const VALIDATION_ERROR_TOOLTIP_MAX_LEN = 200

/**
 * Build credentials map by provider_name; when multiple credentials exist for the same
 * provider, prefer the one with is_valid === true for display.
 */
function buildCredentialsByProvider(credentials: ModelCredential[]): Map<string, ModelCredential> {
  const map = new Map<string, ModelCredential>()
  for (const cred of credentials) {
    const existing = map.get(cred.provider_name)
    if (!existing || (cred.is_valid && !existing.is_valid)) {
      map.set(cred.provider_name, cred)
    }
  }
  return map
}

export interface ModelProvidersByConfigResult {
  credentialsByProvider: Map<string, ModelCredential>
  configuredProviders: ModelProvider[]
  notConfiguredProviders: ModelProvider[]
  noValidCredential: boolean
}

/**
 * Derive configured/unconfigured provider lists and credential map from providers and credentials.
 * "Configured" = has at least one credential record; "no valid credential" = none or all invalid.
 */
export function useModelProvidersByConfig(
  providers: ModelProvider[],
  credentials: ModelCredential[],
): ModelProvidersByConfigResult {
  const credentialsByProvider = useMemo(
    () => buildCredentialsByProvider(credentials),
    [credentials],
  )

  const [configuredProviders, notConfiguredProviders] = useMemo(() => {
    const configured: ModelProvider[] = []
    const notConfigured: ModelProvider[] = []

    for (const provider of providers) {
      if (provider.is_template) continue
      if (credentialsByProvider.has(provider.provider_name)) {
        configured.push(provider)
      } else {
        notConfigured.push(provider)
      }
    }

    const sortProviders = (a: ModelProvider, b: ModelProvider) => {
      if (a.provider_type !== b.provider_type) return a.provider_type === 'custom' ? 1 : -1
      return a.display_name.localeCompare(b.display_name)
    }

    configured.sort(sortProviders)
    notConfigured.sort(sortProviders)

    return [configured, notConfigured]
  }, [providers, credentialsByProvider])

  const noValidCredential =
    configuredProviders.length === 0 ||
    configuredProviders.every((p) => !credentialsByProvider.get(p.provider_name)?.is_valid)

  return {
    credentialsByProvider,
    configuredProviders,
    notConfiguredProviders,
    noValidCredential,
  }
}

export function truncateValidationError(
  error: string | undefined,
  maxLen = VALIDATION_ERROR_TOOLTIP_MAX_LEN,
): string {
  if (!error) return ''
  return error.length <= maxLen ? error : `${error.slice(0, maxLen)}…`
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

export function useAvailableModels(modelType: string = 'chat', options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: modelKeys.available(modelType),
    queryFn: async (): Promise<AvailableModel[]> => {
      const params = new URLSearchParams({ model_type: modelType })
      return await apiGet<AvailableModel[]>(`${MODELS_PATH}?${params.toString()}`)
    },
    enabled: options?.enabled !== false, // defaults to true, but can be set to false
    retry: false,
    staleTime: STALE_TIME.SHORT,
    placeholderData: keepPreviousData,
  })
}

export function useModelInstances() {
  return useQuery({
    queryKey: modelKeys.instances(),
    queryFn: async (): Promise<ModelInstance[]> => {
      return await apiGet<ModelInstance[]>(`${MODELS_PATH}/instances`)
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
}

export function useModels(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: modelKeys.chat(),
    queryFn: async (): Promise<ModelOption[]> => {
      // apiGet automatically unwraps response.data
      const models = await apiGet<
        Array<{
          id: string
          name: string
          model_type: string
          provider_display_name: string
          provider_name: string
          is_available: boolean
        }>
      >('models?model_type=chat')
      return (models || []).map((model) => ({
        id: model.id,
        label: model.name,
        provider: model.provider_display_name,
        provider_name: model.provider_name,
        isAvailable: model.is_available,
      }))
    },
    enabled: options?.enabled !== false, // defaults to true, but can be set to false
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
        validate: request.validate !== false,
      })
      logger.info(`Created credential for provider: ${request.provider_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      // credential changes affect model availability
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
    },
  })
}

export function useCreateCustomProvider() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (request: CreateCustomProviderRequest) => {
      const data = await apiPost<CreateCustomProviderResponse>(
        `${MODEL_PROVIDERS_PATH}/custom`,
        request,
      )
      logger.info(`Created custom provider with model: ${request.model_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
    },
  })
}

export function useValidateCredential() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (credentialId: string) => {
      const data = await apiPost<{ is_valid: boolean; error?: string }>(
        `${MODEL_CREDENTIALS_PATH}/${credentialId}/validate`,
      )
      logger.info(`Validated credential: ${credentialId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      // validation result affects model availability
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
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
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      // clearing credentials affects model availability
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
    },
  })
}

export function useDeleteModelProvider() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (providerName: string) => {
      await apiDelete(`${MODEL_PROVIDERS_PATH}/${providerName}`)
      logger.info(`Deleted model provider: ${providerName}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      queryClient.invalidateQueries({ queryKey: modelKeys.credentials() })
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
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
      })
      logger.info(`Created model instance: ${request.model_name}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
    },
  })
}

export function useModelsOverview() {
  return useQuery({
    queryKey: modelKeys.overview(),
    queryFn: async (): Promise<ModelsOverview> => {
      return await apiGet<ModelsOverview>(`${MODELS_PATH}/overview`)
    },
    enabled: true,
    retry: false,
    staleTime: STALE_TIME.SHORT,
  })
}

export function useUpdateModelInstance() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      instanceId,
      request,
    }: {
      instanceId: string
      request: UpdateModelInstanceRequest
    }) => {
      const data = await apiPatch<ModelInstance>(
        `${MODELS_PATH}/instances/${instanceId}`,
        request,
      )
      logger.info(`Updated model instance: ${instanceId}`)
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.instances() })
      queryClient.invalidateQueries({ queryKey: [...modelKeys.all, 'available'] })
      queryClient.invalidateQueries({ queryKey: modelKeys.overview() })
    },
  })
}

export function useModelUsageStats(params: {
  period?: string
  granularity?: string
  providerName?: string
  modelName?: string
  enabled?: boolean
}) {
  const { period = '24h', granularity = 'hour', providerName, modelName, enabled = true } = params
  return useQuery({
    queryKey: [...modelKeys.all, 'usage-stats', period, granularity, providerName, modelName] as const,
    queryFn: async (): Promise<ModelUsageStats> => {
      const p = new URLSearchParams({ period, granularity })
      if (providerName) p.set('provider_name', providerName)
      if (modelName) p.set('model_name', modelName)
      return await apiGet<ModelUsageStats>(`${MODELS_PATH}/usage/stats?${p.toString()}`)
    },
    enabled,
    retry: false,
    staleTime: STALE_TIME.SHORT,
  })
}

export function useUpdateProviderDefaults() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async ({
      providerName,
      request,
    }: {
      providerName: string
      request: UpdateProviderDefaultsRequest
    }) => {
      const data = await apiPatch<ModelProvider>(
        `${MODEL_PROVIDERS_PATH}/${providerName}/defaults`,
        request,
      )
      logger.info(`Updated provider defaults: ${providerName}`)
      return data
    },
    onSuccess: (_, { providerName }) => {
      queryClient.invalidateQueries({ queryKey: modelKeys.providers() })
      queryClient.invalidateQueries({ queryKey: modelKeys.provider(providerName) })
    },
  })
}
