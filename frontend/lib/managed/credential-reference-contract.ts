export const CREDENTIAL_REFERENCE_KEYS = {
  modelCredentialId: 'model_credential_id',
  environmentCredentialIds: 'environment_credential_ids',
  serviceCredentialId: 'service_credential_id',
  credentialField: 'credential_field',
  secretRef: 'secret_ref',
  secretRefs: 'secret_refs',
  credentialRef: 'credential_ref',
  secretKey: 'secret_key',
} as const

export const CREDENTIAL_REFERENCE_NORMALIZATION = {
  injectType: 'trim_lowercase',
} as const

export const CREDENTIAL_SNAPSHOT_SCHEMAS = {
  legacy_v0: null,
  v1: 'joysafeter.agent_execution_snapshot.v1',
  v2: 'joysafeter.agent_execution_snapshot.v2',
} as const

export const LEGACY_SNAPSHOT_REFERENCE_PATHS = [
  '$.environment.config.secret_refs[*]',
  '$.environment.config.egress_services[*].credential_ref',
  '$.environment.config.egress_services[*].inject.secret_key',
  '$.secret_ref',
  '$.secret_refs[*]',
] as const
