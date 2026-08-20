import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/lib/i18n/config'

import { QuickstartAgentBlueprintReview } from './quickstart-agent-blueprint'

afterEach(() => cleanup())

describe('QuickstartAgentBlueprintReview', () => {
  it('renders the professional agent contract as the primary review surface', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartAgentBlueprintReview
        agentConfig={{
          blueprint: {
            mission: 'Review code changes before release.',
            responsibilities: ['Find correctness and security risks'],
            workflow: ['Inspect the diff', 'Rank findings'],
            boundaries: ['Do not modify production systems'],
            tool_plan: ['Read-only repository access'],
            escalation_conditions: ['Escalate when credentials are exposed'],
            output_contract: ['Return severity, evidence, and remediation'],
            success_criteria: ['Every finding includes evidence'],
            acceptance_test: {
              message: 'Review the authentication change.',
              checks: ['Ranks findings by severity'],
            },
          },
        }}
        generationStatus="complete"
        onShowAdvanced={() => undefined}
      />,
    )

    expect(screen.getByText('Mission')).toBeInTheDocument()
    expect(screen.getByText('Responsibilities')).toBeInTheDocument()
    expect(screen.getByText('Workflow')).toBeInTheDocument()
    expect(screen.getByText('Boundaries')).toBeInTheDocument()
    expect(screen.getByText('Tools & permissions')).toBeInTheDocument()
    expect(screen.getByText('Escalation conditions')).toBeInTheDocument()
    expect(screen.getByText('Output contract')).toBeInTheDocument()
    expect(screen.getByText('Success criteria')).toBeInTheDocument()
    expect(screen.getByText('Acceptance test')).toBeInTheDocument()
    expect(screen.getByText('Review the authentication change.')).toBeInTheDocument()
  })

  it('keeps partial blueprint output useful while generation is still running', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartAgentBlueprintReview
        agentConfig={{
          description: 'Investigate production incidents.',
          blueprint: { workflow: ['Assess impact'] },
        }}
        generationStatus="generating"
        onShowAdvanced={() => undefined}
      />,
    )

    expect(screen.getByText('Investigate production incidents.')).toBeInTheDocument()
    expect(screen.getByText('Assess impact')).toBeInTheDocument()
    expect(screen.getByText('Building the remaining blueprint sections...')).toBeInTheDocument()
  })

  it('offers advanced configuration when no blueprint is available', async () => {
    await i18n.changeLanguage('en')
    const onShowAdvanced = vi.fn()
    render(
      <QuickstartAgentBlueprintReview
        agentConfig={{ name: 'Legacy Agent' }}
        generationStatus="idle"
        onShowAdvanced={onShowAdvanced}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'View advanced configuration' }))
    expect(onShowAdvanced).toHaveBeenCalledTimes(1)
  })
})
