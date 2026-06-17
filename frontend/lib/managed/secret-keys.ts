export const SECRET_PROVIDER_OPTIONS = [
  { value: 'anthropic', label: 'Anthropic' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'codex', label: 'Codex' },
  { value: 'native', label: 'Native' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'custom', label: 'Custom' },
]

export const SECRET_PROTOCOL_OPTIONS = [
  { value: 'anthropic_messages', label: 'Anthropic Messages API' },
  { value: 'openai_responses', label: 'OpenAI Responses API' },
  { value: 'chat_completions', label: 'Chat Completions API' },
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
  {
    provider: 'Codex',
    providerValue: 'codex',
    icon: 'C',
    bgColor: '#111827',
    keys: [
      'OPENAI_API_KEY',
      'CODEX_BASE_URL',
      'CODEX_MODEL',
      'CODEX_REASONING_EFFORT',
    ],
  },
]

export const SECRET_KEY_OPTIONS = SECRET_KEY_GROUPS.flatMap((g) => g.keys)

export function getDefaultProtocol(provider: string) {
  if (provider === 'anthropic' || provider === 'native') return 'anthropic_messages'
  if (provider === 'openai') return 'openai_responses'
  if (provider === 'codex') return 'openai_responses'
  return 'chat_completions'
}

export function getDefaultSecretPairs(provider: string, protocol: string) {
  if ((provider === 'anthropic' || provider === 'native') && protocol === 'anthropic_messages') {
    return [
      { key: 'ANTHROPIC_API_KEY', value: '' },
      { key: 'ANTHROPIC_MODEL', value: 'claude-opus-4-20250514' },
    ]
  }
  if (provider === 'openai') {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'OPENAI_MODEL', value: '' },
      ...(protocol === 'chat_completions' ? [{ key: 'OPENAI_BASE_URL', value: '' }] : []),
    ]
  }
  if (provider === 'codex') {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'CODEX_BASE_URL', value: '' },
      { key: 'CODEX_MODEL', value: 'gpt-5.3-codex' },
      { key: 'CODEX_REASONING_EFFORT', value: 'high' },
    ]
  }
  if (provider === 'deepseek') {
    return [
      { key: 'OPENAI_API_KEY', value: '' },
      { key: 'OPENAI_BASE_URL', value: 'https://api.deepseek.com' },
      { key: 'OPENAI_MODEL', value: 'deepseek-chat' },
    ]
  }
  return [{ key: '', value: '' }]
}

export function isModelKey(key: string) {
  return key === 'ANTHROPIC_MODEL' || key === 'OPENAI_MODEL' || key === 'CODEX_MODEL'
}

export const MODEL_OPTIONS = [
  'GPT-5.5',
  'gpt-5.3-codex',
  'Claude-Opus-4.6',
  'Claude-Opus-4.7',
  'Claude-Opus-4.8',
  'deepseek-v4-pro',
]
