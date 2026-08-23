export interface CredentialFieldGroup {
  id: string
  label: string
  labelKey: string
  icon: string
  bgColor: string
  keys: string[]
}

export const CREDENTIAL_FIELD_GROUPS: CredentialFieldGroup[] = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    labelKey: 'managed.credentials.resources.keyGroups.claude',
    icon: 'C',
    bgColor: '#f97316',
    // Autocomplete suggestions for the generic Service Credential key picker
    // (CredentialFieldSelect) only. These keys do NOT render editable inputs on their
    // own: the anthropic Model Connection form (ModelConnectionConfigurator) is the
    // single source of truth for anthropic rendering. It exposes ANTHROPIC_API_KEY
    // plus the auth-method switch, and hides ANTHROPIC_AUTH_TOKEN so there is no
    // second raw Auth Token box.
    keys: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL'],
  },
  {
    id: 'openai',
    label: 'OpenAI-compatible',
    labelKey: 'managed.credentials.resources.keyGroups.codex',
    icon: 'C',
    bgColor: '#111827',
    keys: ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'OPENAI_REASONING_EFFORT'],
  },
]

export const CREDENTIAL_FIELD_OPTIONS = [
  ...new Set(CREDENTIAL_FIELD_GROUPS.flatMap((group) => group.keys)),
]

const CREDENTIAL_FIELD_GROUP_IDS_BY_PROVIDER: Record<string, string[]> = {
  anthropic: ['anthropic'],
  openai: ['openai'],
  deepseek: ['openai'],
}

export function getCredentialFieldGroups(provider?: string | null, protocol?: string | null) {
  const normalizedProvider = (provider || '').toLowerCase()
  const groupIds = CREDENTIAL_FIELD_GROUP_IDS_BY_PROVIDER[normalizedProvider]

  if (groupIds) {
    return CREDENTIAL_FIELD_GROUPS.filter((group) => groupIds.includes(group.id))
  }

  if (protocol === 'anthropic_messages') {
    return CREDENTIAL_FIELD_GROUPS.filter((group) => group.id === 'anthropic')
  }

  if (protocol === 'openai_responses' || protocol === 'chat_completions') {
    return CREDENTIAL_FIELD_GROUPS.filter((group) => group.id === 'openai')
  }

  const seen = new Set<string>()
  return CREDENTIAL_FIELD_GROUPS.map((group) => {
    const keys = group.keys.filter((key) => {
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    return { ...group, keys }
  }).filter((group) => group.keys.length > 0)
}

function normalizeCredentialField(key: string) {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase()
}

export function isCredentialValueMaskedField(key: string) {
  const normalized = normalizeCredentialField(key)
  if (!normalized) return true
  return (
    normalized === 'API_KEY' ||
    normalized === 'AUTH_TOKEN' ||
    normalized === 'TOKEN' ||
    normalized === 'SECRET' ||
    normalized === 'PASSWORD' ||
    normalized === 'CLIENT_SECRET' ||
    normalized === 'REFRESH_TOKEN' ||
    normalized.endsWith('_API_KEY') ||
    normalized.endsWith('_AUTH_TOKEN') ||
    normalized.endsWith('_TOKEN') ||
    normalized.endsWith('_SECRET') ||
    normalized.endsWith('_PASSWORD')
  )
}

export const MODEL_NAME_OPTIONS = [
  'GPT-5.5',
  'gpt-5.3-codex',
  'Claude-Opus-4.6',
  'Claude-Opus-4.7',
  'Claude-Opus-4.8',
]
