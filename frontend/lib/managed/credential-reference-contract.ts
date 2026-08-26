export const CREDENTIAL_REFERENCE_KEYS = {
  modelCredentialId: 'model_credential_id',
  environmentCredentialIds: 'environment_credential_ids',
  credentialRef: 'credential_ref',
  credentialField: 'credential_field',
} as const

export const CREDENTIAL_REFERENCE_NORMALIZATION = {
  injectType: 'trim_lowercase',
} as const

export const CREDENTIAL_SNAPSHOT_SCHEMAS = {
  v2: 'joysafeter.agent_execution_snapshot.v2',
} as const
