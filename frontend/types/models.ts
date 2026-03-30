/**
 * Model-related type definitions
 *
 * Unified type definitions for hooks/queries/models.ts and services/modelService.ts to share
 */

// ==================== Model Provider ====================

/**
 * Model provider
 */
export interface ModelProvider {
  provider_name: string
  display_name: string
  icon?: string
  description?: string
  supported_model_types: string[]
  credential_schema?: Record<string, any>
  config_schemas?: Record<string, any>
  model_count?: number
  default_parameters?: Record<string, unknown>
  is_enabled: boolean
  is_template?: boolean
  provider_type?: 'system' | 'custom'
  template_name?: string
  background?: string // Provider card background color
}

// ==================== Model Credential ====================

/**
 * Model credential
 */
export interface ModelCredential {
  id: string
  provider_name: string
  is_valid: boolean
  last_validated_at?: string
  validation_error?: string
  credentials?: Record<string, any> // Only returned when getting details
}

/**
 * Create model credential request.
 * When provider_name is "custom", model_name can be set to add one custom model (credential + instance) in one call.
 */
export interface CreateCredentialRequest {
  provider_name: string
  providerDisplayName?: string
  credentials: Record<string, any>
  validate?: boolean
  model_name?: string
  model_parameters?: Record<string, unknown>
}

// ==================== Model Instance ====================

/**
 * Model instance configuration
 */
export interface ModelInstance {
  id: string
  provider_name: string
  provider_display_name?: string
  model_name: string
  model_type?: string
  model_parameters?: Record<string, unknown>
  is_default: boolean
}

/**
 * Create model instance request
 */
export interface CreateModelInstanceRequest {
  provider_name: string
  model_name: string
  model_type?: string
  model_parameters?: Record<string, unknown>
  is_default?: boolean
}

/**
 * Update model instance default status request
 */
export interface UpdateModelInstanceDefaultRequest {
  provider_name: string
  model_name: string
  is_default: boolean
}

// ==================== Available Model ====================

/**
 * Available model (for selector)
 */
export interface AvailableModel {
  provider_name: string
  provider_display_name: string
  name: string
  display_name: string
  description: string
  is_available: boolean
  is_default?: boolean
  unavailable_reason?: 'no_credentials' | 'invalid_credentials' | 'model_not_found' | 'provider_error'
}

// ==================== Provider Defaults ====================

export interface UpdateProviderDefaultsRequest {
  default_parameters: Record<string, unknown>
}

// ==================== Update Model Instance ====================

export interface UpdateModelInstanceRequest {
  model_parameters?: Record<string, unknown>
  is_default?: boolean
}

// ==================== Overview ====================

export interface DefaultModelInfo {
  provider_name: string
  provider_display_name: string
  model_name: string
  model_parameters: Record<string, unknown>
}

export interface CredentialFailureInfo {
  provider_name: string
  provider_display_name: string
  error: string
  failed_at?: string
}

export interface ModelsOverview {
  total_providers: number
  healthy_providers: number
  unhealthy_providers: number
  unconfigured_providers: number
  total_models: number
  available_models: number
  default_model?: DefaultModelInfo
  recent_credential_failure?: CredentialFailureInfo
}

// ==================== Test Model Output ====================

/**
 * Test model output request
 */
export interface TestModelOutputRequest {
  model_name: string
  input: string
}

/**
 * Test model output response
 */
export interface TestModelOutputResponse {
  output: string
}

// ==================== Usage Stats ====================

export interface UsageStatsSummary {
  total_calls: number
  total_input_tokens: number
  total_output_tokens: number
  avg_response_time_ms: number
  error_rate: number
}

export interface UsageTimelinePoint {
  timestamp: string
  calls: number
  tokens: number
  avg_time_ms: number
}

export interface UsageByModel {
  model_name: string
  calls: number
  tokens: number
}

export interface ModelUsageStats {
  summary: UsageStatsSummary
  timeline: UsageTimelinePoint[]
  by_model: UsageByModel[]
}

// ==================== Test Model Stream ====================

/**
 * Streaming test request
 */
export interface TestModelStreamRequest {
  model_name: string
  input: string
  model_parameters?: Record<string, any>
}

/**
 * Performance metrics emitted at end of stream
 */
export interface TestModelStreamMetrics {
  ttft_ms: number
  total_time_ms: number
  input_tokens: number
  output_tokens: number
  tokens_per_second: number
}

/**
 * State managed by useTestModelStream
 */
export interface TestModelStreamState {
  output: string
  metrics: TestModelStreamMetrics | null
  error: string | null
  isStreaming: boolean
}
