import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/lib/i18n/config'

import { QuickstartGenerationStatus } from './quickstart-generation-status'

afterEach(() => cleanup())

describe('QuickstartGenerationStatus', () => {
  it('shows semantic progress, elapsed time, partial output, and cancel', async () => {
    await i18n.changeLanguage('en')
    const onCancel = vi.fn()
    render(
      <QuickstartGenerationStatus
        state={{
          status: 'generating',
          phase: 'boundaries',
          elapsedSeconds: 12,
          hasPartialConfig: true,
        }}
        onCancel={onCancel}
        onRetry={() => undefined}
      />,
    )

    expect(screen.getByText('Defining safety boundaries')).toBeInTheDocument()
    expect(screen.getByText('12s elapsed')).toBeInTheDocument()
    expect(screen.getByText('Partial draft saved')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel generation' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  it('does not show a noisy zero-second timer before five seconds', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartGenerationStatus
        state={{
          status: 'generating',
          phase: 'understanding',
          elapsedSeconds: 4,
          hasPartialConfig: false,
        }}
        onCancel={() => undefined}
        onRetry={() => undefined}
      />,
    )

    expect(screen.queryByText('4s elapsed')).not.toBeInTheDocument()
    expect(screen.getByText('Understanding your goal')).toBeInTheDocument()
  })

  it('lets the user retry a cancelled generation', async () => {
    await i18n.changeLanguage('en')
    const onRetry = vi.fn()
    render(
      <QuickstartGenerationStatus
        state={{
          status: 'cancelled',
          phase: 'tools',
          elapsedSeconds: 8,
          hasPartialConfig: true,
        }}
        onCancel={() => undefined}
        onRetry={onRetry}
      />,
    )

    expect(screen.getByText('Generation cancelled')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledTimes(1)
  })
})
