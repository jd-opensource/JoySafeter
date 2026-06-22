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
    ],
  },
]

export const SECRET_PROVIDER_OPTIONS = SECRET_PROVIDER_GROUPS.flatMap((group) => group.options)

export function normalizeSecretProvider(provider?: string) {
  const normalized = (provider || '').toLowerCase()
  if (normalized === 'claude' || normalized === 'anthropic') return 'claude'
  if (normalized === 'codex') return 'codex'
  if (normalized === 'native') return 'native'
  return 'custom'
}

export function getSecretProviderLabel(provider?: string) {
  const normalized = normalizeSecretProvider(provider)
  if (normalized === 'claude') return 'Claude Code'
  if (normalized === 'codex') return 'Codex'
  if (normalized === 'native') return 'Native'
  return 'Custom'
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
    keys: [
      'ANTHROPIC_API_KEY',
      'ANTHROPIC_AUTH_TOKEN',
      'ANTHROPIC_MODEL',
      'ANTHROPIC_BASE_URL',
    ],
  },
  {
    id: 'codex',
    label: 'Codex',
    labelKey: 'managed.secrets.keyGroups.codex',
    icon: 'C',
    bgColor: '#111827',
    keys: [
      'OPENAI_API_KEY',
      'OPENAI_MODEL',
      'OPENAI_BASE_URL',
      'OPENAI_REASONING_EFFORT',
    ],
  },
  {
    id: 'native',
    label: 'Native',
    labelKey: 'managed.secrets.keyGroups.native',
    icon: 'N',
    bgColor: '#2563eb',
    keys: [
      'ANTHROPIC_API_KEY',
      'ANTHROPIC_AUTH_TOKEN',
      'ANTHROPIC_MODEL',
      'ANTHROPIC_BASE_URL',
    ],
  },
]

export const SECRET_KEY_OPTIONS = [...new Set(SECRET_KEY_GROUPS.flatMap((g) => g.keys))]

const SECRET_KEY_GROUP_IDS_BY_PROVIDER: Record<string, string[]> = {
  claude: ['claude'],
  anthropic: ['claude'],
  native: ['native'],
  codex: ['codex'],
}

export function getSecretKeyGroups(provider?: string, protocol?: string) {
  const normalizedProvider = (provider || '').toLowerCase()
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
  if (provider === 'claude' || provider === 'anthropic' || provider === 'native') return 'anthropic_messages'
  if (provider === 'codex') return 'openai_responses'
  return 'chat_completions'
}

export function getDefaultSecretPairs(provider: string, protocol: string) {
  if ((provider === 'claude' || provider === 'anthropic' || provider === 'native') && protocol === 'anthropic_messages') {
    return [
      { key: 'ANTHROPIC_API_KEY', value: '' },
      { key: 'ANTHROPIC_MODEL', value: 'claude-opus-4-20250514' },
    ]
  }
  if (provider === 'codex') {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'OPENAI_MODEL', value: 'gpt-5.3-codex' },
      { key: 'OPENAI_BASE_URL', value: '' },
    ]
  }
  return [{ key: '', value: '' }]
}

export function isModelKey(key: string) {
  return key === 'ANTHROPIC_MODEL' || key === 'OPENAI_MODEL'
}

export const MODEL_OPTIONS = [
  'GPT-5.5',
  'gpt-5.3-codex',
  'Claude-Opus-4.6',
  'Claude-Opus-4.7',
  'Claude-Opus-4.8',
]
