import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { BuildStepper } from '../build-stepper'
import { BUILD_STAGES } from '../agent-build-types'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}))

describe('BuildStepper', () => {
  const onNavigate = vi.fn()

  it('renders all 5 stages', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="brief" onNavigate={onNavigate} />)
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(5)
  })

  it('marks active stage with aria-current', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="build" onNavigate={onNavigate} />)
    const activeButton = screen.getByRole('button', { current: 'step' })
    expect(activeButton).toBeInTheDocument()
  })

  it('calls onNavigate when clicking a stage', () => {
    render(<BuildStepper stages={BUILD_STAGES} activeStage="brief" onNavigate={onNavigate} />)
    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[2]) // test-lab
    expect(onNavigate).toHaveBeenCalledWith('test-lab')
  })
})
