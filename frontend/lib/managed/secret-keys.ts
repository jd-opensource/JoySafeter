export interface SecretKeyGroup {
  id: string
  label: string
  labelKey: string
  icon: string
  bgColor: string
  keys: string[]
}

export const SECRET_KEY_GROUPS: SecretKeyGroup[] = [
  {
    id: 'anthropic',
    label: 'Anthropic',
    labelKey: 'managed.secrets.keyGroups.claude',
    icon: 'C',
    bgColor: '#f97316',
    keys: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL'],
  },
  {
    id: 'openai',
    label: 'OpenAI-compatible',
    labelKey: 'managed.secrets.keyGroups.codex',
    icon: 'C',
    bgColor: '#111827',
    keys: ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'OPENAI_REASONING_EFFORT'],
  },
]

export const SECRET_KEY_OPTIONS = [...new Set(SECRET_KEY_GROUPS.flatMap((g) => g.keys))]

const SECRET_KEY_GROUP_IDS_BY_PROVIDER: Record<string, string[]> = {
  anthropic: ['anthropic'],
  openai: ['openai'],
  deepseek: ['openai'],
}

export function getSecretKeyGroups(provider?: string | null, protocol?: string | null) {
  const normalizedProvider = (provider || '').toLowerCase()
  const groupIds = SECRET_KEY_GROUP_IDS_BY_PROVIDER[normalizedProvider]

  if (groupIds) {
    return SECRET_KEY_GROUPS.filter((group) => groupIds.includes(group.id))
  }

  if (protocol === 'anthropic_messages') {
    return SECRET_KEY_GROUPS.filter((group) => group.id === 'anthropic')
  }

  if (protocol === 'openai_responses' || protocol === 'chat_completions') {
    return SECRET_KEY_GROUPS.filter((group) => group.id === 'openai')
  }

  const seen = new Set<string>()
  return SECRET_KEY_GROUPS.map((group) => {
    const keys = group.keys.filter((key) => {
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    return { ...group, keys }
  }).filter((group) => group.keys.length > 0)
}

function normalizeSecretKey(key: string) {
  return key
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[^a-zA-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase()
}

export function isSecretValueMaskedKey(key: string) {
  const normalized = normalizeSecretKey(key)
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

export const MODEL_OPTIONS = [
  'GPT-5.5',
  'gpt-5.3-codex',
  'Claude-Opus-4.6',
  'Claude-Opus-4.7',
  'Claude-Opus-4.8',
]
