export const SECRET_PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'custom', label: 'Custom' },
]

export const SECRET_PROTOCOL_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic Messages' },
  { value: 'openai_compatible', label: 'OpenAI Compatible' },
  { value: 'custom', label: 'Custom' },
]

export const SECRET_KEY_GROUPS = [
  {
    provider: 'Anthropic',
    providerValue: 'anthropic',
    icon: 'A',
    bgColor: '#f97316',
    keys: [
      'ANTHROPIC_API_KEY',
      'ANTHROPIC_MODEL',
      'ANTHROPIC_BASE_URL',
      'ANTHROPIC_AUTH_TOKEN',
    ],
  },
  {
    provider: 'OpenAI',
    providerValue: 'openai',
    icon: 'O',
    bgColor: '#22c55e',
    keys: [
      'OPENAI_API_KEY',
      'OPENAI_BASE_URL',
      'OPENAI_MODEL',
    ],
  },
]

export const SECRET_KEY_OPTIONS = SECRET_KEY_GROUPS.flatMap((g) => g.keys)

export function getDefaultSecretPairs(provider: string, protocol: string) {
  if (provider === 'anthropic' && protocol === 'anthropic') {
    return [
      { key: 'ANTHROPIC_API_KEY', value: '' },
      { key: 'ANTHROPIC_MODEL', value: 'claude-opus-4-20250514' },
    ]
  }
  if (protocol === 'openai_compatible') {
    return [
      { key: provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY', value: '' },
      { key: provider === 'anthropic' ? 'ANTHROPIC_BASE_URL' : 'OPENAI_BASE_URL', value: '' },
      { key: provider === 'anthropic' ? 'ANTHROPIC_MODEL' : 'OPENAI_MODEL', value: '' },
    ]
  }
  if (provider === 'openai') {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'OPENAI_MODEL', value: '' },
    ]
  }
  return [{ key: '', value: '' }]
}

export const MODEL_OPTIONS = [
  'claude-opus-4-20250514',
  'claude-sonnet-4-20250514',
  'claude-haiku-4-20250414',
  'Claude-Opus-4.6',
  'Claude-Sonnet-4.6',
]
