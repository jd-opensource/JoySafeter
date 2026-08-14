import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

import { ConfirmDialog } from './confirm-dialog'

describe('ConfirmDialog', () => {
  it('does not report confirmation as cancellation', async () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Archive Agent"
        description="Archive this agent?"
        confirmLabel="Archive"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Archive' }))

    await waitFor(() => expect(onConfirm).toHaveBeenCalledTimes(1))
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('reports an explicit cancellation once', async () => {
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Archive Agent"
        description="Archive this agent?"
        confirmLabel="Archive"
        onConfirm={vi.fn()}
        onCancel={onCancel}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }))

    await waitFor(() => expect(onCancel).toHaveBeenCalledTimes(1))
  })
})
