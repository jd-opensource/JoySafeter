import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { useSessionSkillUsageRefresh } from './use-session-skill-usage-refresh'

describe('useSessionSkillUsageRefresh', () => {
  it('invalidates skill usage after a session run finishes', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { rerender } = renderHook(
      ({ isRunning }) =>
        useSessionSkillUsageRefresh({
          isRunning,
          sessionScope: 'sess-a:org-a:project-a',
        }),
      { initialProps: { isRunning: false }, wrapper },
    )

    rerender({ isRunning: true })
    expect(invalidateQueries).not.toHaveBeenCalled()

    rerender({ isRunning: false })

    await waitFor(() =>
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: ['session-skill-usage', 'sess-a:org-a:project-a'],
      }),
    )
  })
})
