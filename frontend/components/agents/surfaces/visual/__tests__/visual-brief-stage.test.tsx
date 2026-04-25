import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

const replaceMock = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: replaceMock }),
  useSearchParams: () => new URLSearchParams(),
}))
vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? _key,
  }),
}))

import { VisualBriefStage } from '../visual-brief-stage'

const baseProps = {
  agent: { id: 'a-1', name: 'My Agent', description: 'test goal' } as any,
  version: null,
  workspaceId: 'ws-1',
  navigateToStage: vi.fn(),
}

describe('VisualBriefStage', () => {
  it('renders the brief form with goal pre-filled from agent description', () => {
    render(<VisualBriefStage {...baseProps} />)
    const goalTextarea = screen.getByDisplayValue('test goal')
    expect(goalTextarea).toBeInTheDocument()
  })

  it('has Generate and Build manually buttons', () => {
    render(<VisualBriefStage {...baseProps} />)
    expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /build manually/i })).toBeInTheDocument()
  })

  it('navigates to build stage on skip', () => {
    render(<VisualBriefStage {...baseProps} />)
    fireEvent.click(screen.getByRole('button', { name: /build manually/i }))
    expect(baseProps.navigateToStage).toHaveBeenCalledWith('build')
  })
})
