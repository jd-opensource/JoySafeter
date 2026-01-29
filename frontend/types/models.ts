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
  is_enabled: boolean
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
 * Create model credential request
 */
export interface CreateCredentialRequest {
  provider_name: string
  credentials: Record<string, any>
  workspaceId?: string
  validate?: boolean
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
  workspaceId?: string
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
}

// ==================== Test Model Output ====================

/**
 * Test model output request
 */
export interface TestModelOutputRequest {
  model_name: string
  input: string
  workspaceId?: string
}

/**
 * Test model output response
 */
export interface TestModelOutputResponse {
  output: string
}
