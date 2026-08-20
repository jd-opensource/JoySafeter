import { fireEvent, render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
  DialogHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h1>{children}</h1>,
}))

import { CredentialKindChooser } from './credential-kind-chooser'

describe('CredentialKindChooser', () => {
  it('emits the chosen kind and closes', () => {
    const onChoose = vi.fn()
    const onOpenChange = vi.fn()
    const { getByText } = render(<CredentialKindChooser open onOpenChange={onOpenChange} onChoose={onChoose} />)
    fireEvent.click(getByText('managed.credentials.chooser.credentialGroup'))
    expect(onChoose).toHaveBeenCalledWith('credential-group')
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
