import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { CreateAgentDialog } from '../agent-form-dialog'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

function TestHarness() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <CreateAgentDialog
        open={open}
        onOpenChange={setOpen}
        onSubmit={vi.fn()}
      />
    </>
  )
}

describe('CreateAgentDialog', () => {
  it('resets form state after closing and reopening', async () => {
    const user = userEvent.setup()

    render(<TestHarness />)

    await user.click(screen.getByRole('button', { name: 'Open dialog' }))

    const nameInput = screen.getByLabelText('Name *')
    await user.type(nameInput, 'CLI Agent')
    await user.click(screen.getByRole('radio', { name: /OpenClaw/i }))

    expect(screen.getByRole('radio', { name: /OpenClaw/i })).toHaveAttribute('aria-checked', 'true')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))

    expect(screen.getByLabelText('Name *')).toHaveValue('')
    expect(screen.getByRole('radio', { name: /Graph/i })).toHaveAttribute('aria-checked', 'true')
  })
})
