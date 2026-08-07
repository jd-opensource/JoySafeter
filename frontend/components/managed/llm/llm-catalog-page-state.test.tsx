import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

import { LlmCatalogPageState } from './llm-catalog-page-state'

describe('LlmCatalogPageState', () => {
  it('shows a loading state without implying that no configurations exist', () => {
    render(<LlmCatalogPageState state="loading" />)

    expect(screen.getByText('managed.llm.loadingCatalog')).toBeInTheDocument()
    expect(screen.queryByText('managed.secrets.empty')).not.toBeInTheDocument()
  })

  it('keeps catalog failures actionable with an inline retry', () => {
    const onRetry = vi.fn()
    render(<LlmCatalogPageState state="error" onRetry={onRetry} />)

    expect(screen.getByText('managed.llm.catalogLoadFailed')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })
})
