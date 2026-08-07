export const SECRET_PROVIDER_GROUPS = [
  {
    label: 'Agent engines',
    labelKey: 'managed.secrets.providerGroups.agentEngines',
    icon: 'E',
    bgColor: '#111827',
    options: [
      { value: 'claude', label: 'Claude Code' },
      { value: 'codex', label: 'Codex' },
      { value: 'native', label: 'Native' },
      { value: 'pi', label: 'Pi' },
    ],
  },
]

export const SECRET_PROVIDER_OPTIONS = SECRET_PROVIDER_GROUPS.flatMap((group) => group.options)

export function normalizeSecretProvider(provider?: string) {
  const normalized = (provider || '').toLowerCase()
  if (normalized === 'claude' || normalized === 'anthropic') return 'claude'
  if (normalized === 'codex') return 'codex'
  if (normalized === 'native') return 'native'
  if (normalized === 'pi') return 'pi'
  return 'custom'
}

export function getSecretProviderLabel(provider?: string) {
  const normalized = normalizeSecretProvider(provider)
  if (normalized === 'claude') return 'Claude Code'
  if (normalized === 'codex') return 'Codex'
  if (normalized === 'native') return 'Native'
  if (normalized === 'pi') return 'Pi'
  return 'Custom'
}

export function isCustomSecretProvider(provider?: string) {
  return normalizeSecretProvider(provider) === 'custom'
}

export const SECRET_PROTOCOL_OPTIONS = [
  { value: 'anthropic_messages', label: 'Anthropic Messages API' },
  { value: 'openai_responses', label: 'OpenAI Responses API' },
  { value: 'chat_completions', label: 'Chat Completions API' },
]

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
    id: 'claude',
    label: 'Claude Code',
    labelKey: 'managed.secrets.keyGroups.claude',
    icon: 'C',
    bgColor: '#f97316',
    keys: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL'],
  },
  {
    id: 'codex',
    label: 'Codex',
    labelKey: 'managed.secrets.keyGroups.codex',
    icon: 'C',
    bgColor: '#111827',
    keys: ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'OPENAI_REASONING_EFFORT'],
  },
  {
    id: 'native',
    label: 'Native',
    labelKey: 'managed.secrets.keyGroups.native',
    icon: 'N',
    bgColor: '#2563eb',
    keys: ['ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL'],
  },
  {
    id: 'native_openai',
    label: 'Native (OpenAI)',
    labelKey: 'managed.secrets.keyGroups.nativeOpenai',
    icon: 'N',
    bgColor: '#2563eb',
    keys: ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_BASE_URL', 'OPENAI_REASONING_EFFORT'],
  },
]

export const SECRET_KEY_OPTIONS = [...new Set(SECRET_KEY_GROUPS.flatMap((g) => g.keys))]

const SECRET_KEY_GROUP_IDS_BY_PROVIDER: Record<string, string[]> = {
  claude: ['claude'],
  anthropic: ['claude'],
  // native is protocol-aware — resolved below
  codex: ['codex'],
}

export function getSecretKeyGroups(provider?: string, protocol?: string) {
  const normalizedProvider = (provider || '').toLowerCase()

  // Native and pi engines are multi-provider: key group depends on protocol.
  if (normalizedProvider === 'native' || normalizedProvider === 'pi') {
    if (protocol === 'openai_responses' || protocol === 'chat_completions') {
      return SECRET_KEY_GROUPS.filter((group) => group.id === 'native_openai')
    }
    // Default (anthropic_messages or unset)
    return SECRET_KEY_GROUPS.filter((group) => group.id === 'native')
  }

  const groupIds = SECRET_KEY_GROUP_IDS_BY_PROVIDER[normalizedProvider]

  if (groupIds) {
    return SECRET_KEY_GROUPS.filter((group) => groupIds.includes(group.id))
  }

  if (protocol === 'anthropic_messages') {
    return SECRET_KEY_GROUPS.filter((group) => group.id === 'claude')
  }

  if (protocol === 'openai_responses' || protocol === 'chat_completions') {
    return SECRET_KEY_GROUPS.filter((group) => group.id === 'codex')
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

export function getDefaultProtocol(provider: string) {
  if (provider === 'claude' || provider === 'anthropic' || provider === 'native' || provider === 'pi')
    return 'anthropic_messages'
  if (provider === 'codex') return 'openai_responses'
  return 'chat_completions'
}

export function getDefaultSecretPairs(provider: string, protocol: string) {
  const isOpenAIProtocol = protocol === 'openai_responses' || protocol === 'chat_completions'

  if (
    provider === 'claude' ||
    provider === 'anthropic' ||
    ((provider === 'native' || provider === 'pi') && !isOpenAIProtocol)
  ) {
    return [
      { key: 'ANTHROPIC_API_KEY', value: '' },
      { key: 'ANTHROPIC_MODEL', value: 'Claude-Opus-4.6' },
      { key: 'ANTHROPIC_BASE_URL', value: '' },
    ]
  }
  if (provider === 'codex' || ((provider === 'native' || provider === 'pi') && isOpenAIProtocol)) {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'OPENAI_MODEL', value: provider === 'codex' ? 'gpt-5.3-codex' : '' },
      { key: 'OPENAI_BASE_URL', value: '' },
    ]
  }
  return [{ key: '', value: '' }]
}

export function isModelKey(key: string) {
  return key === 'ANTHROPIC_MODEL' || key === 'OPENAI_MODEL'
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
