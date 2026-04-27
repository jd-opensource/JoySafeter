import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/hooks/queries/models', () => ({
  useAvailableModels: () => ({
    data: [
      {
        is_available: true,
        provider_name: 'openai',
        name: 'gpt-5',
        display_name: 'GPT-5',
        provider_display_name: 'OpenAI',
      },
    ],
  }),
}))

import { useModelSelector } from '../use-model-selector'

describe('useModelSelector', () => {
  it('materializes the first available model as an actual selection', async () => {
    const { result } = renderHook(() => useModelSelector())

    await waitFor(() => {
      expect(result.current.selectedProviderName).toBe('openai')
      expect(result.current.selectedModelName).toBe('gpt-5')
      expect(result.current.selectedModel).toBe('openai:gpt-5')
    })
  })
})
