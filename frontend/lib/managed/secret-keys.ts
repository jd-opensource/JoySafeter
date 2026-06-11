export const SECRET_KEY_GROUPS = [
  {
    provider: 'Anthropic',
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
    icon: 'O',
    bgColor: '#22c55e',
    keys: [
      'OPENAI_API_KEY',
      'OPENAI_BASE_URL',
    ],
  },
]

export const SECRET_KEY_OPTIONS = SECRET_KEY_GROUPS.flatMap((g) => g.keys)

export const MODEL_OPTIONS = [
  'claude-opus-4-20250514',
  'claude-sonnet-4-20250514',
  'claude-haiku-4-20250414',
  'Claude-Opus-4.6',
  'Claude-Sonnet-4.6',
]
