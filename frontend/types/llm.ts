export type LlmCredentialFieldType = 'secret' | 'text' | 'url' | 'select'

export interface LlmCredentialField {
  key: string
  label: string
  type: LlmCredentialFieldType
  required: boolean
  placeholder: string | null
  help_text: string | null
  options: string[]
  advanced: boolean
}

export interface LlmCredentialProfile {
  id: string
  fields: LlmCredentialField[]
  required_any_of: string[][]
  base_url_key: string | null
  model_key: string | null
}

export interface LlmProviderProtocolBinding {
  protocol_id: string
  credential_profile_id: string
  default_base_url: string | null
  model_suggestions: string[]
}

export interface LlmEngineCapability {
  id: string
  display_name: string
  enabled: boolean
  supported_protocol_ids: string[]
  preferred_protocol_ids: string[]
}

export interface LlmProtocolDefinition {
  id: string
  display_name: string
  description: string
}

export interface LlmProviderDefinition {
  id: string
  display_name: string
  enabled: boolean
  protocol_bindings: LlmProviderProtocolBinding[]
}

export interface LlmCatalog {
  version: string
  engines: LlmEngineCapability[]
  protocols: LlmProtocolDefinition[]
  providers: LlmProviderDefinition[]
  credential_profiles: LlmCredentialProfile[]
}

export interface LlmProviderProtocolOption {
  providerId: string
  protocolId: string
  provider: LlmProviderDefinition
  protocol: LlmProtocolDefinition
  binding: LlmProviderProtocolBinding
  credentialProfile: LlmCredentialProfile
}

export interface StableConnectionFingerprintInput {
  providerId: string
  protocolId: string
  values: Record<string, string>
}
