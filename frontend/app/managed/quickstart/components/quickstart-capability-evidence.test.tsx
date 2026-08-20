import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '@/lib/i18n/config'

import { QuickstartCapabilityEvidence } from './quickstart-capability-evidence'

afterEach(() => cleanup())

describe('QuickstartCapabilityEvidence', () => {
  it('shows observed capabilities without claiming absent controls', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartCapabilityEvidence
        evidence={{
          responseReceived: true,
          environmentAttached: false,
          externalToolsAuthorized: true,
          configuredSkills: ['Secure Review'],
          observedTools: ['Read'],
          observedMcpTools: ['github.search'],
          auditEventsAvailable: true,
        }}
      />,
    )

    expect(screen.getByText('Capability evidence')).toBeInTheDocument()
    expect(screen.getByText('Response observed')).toBeInTheDocument()
    expect(screen.getByText('No custom environment attached')).toBeInTheDocument()
    expect(screen.getByText('External tools authorized')).toBeInTheDocument()
    expect(screen.getByText(/Skills attached: Secure Review/)).toBeInTheDocument()
    expect(screen.getByText(/Tool calls observed: Read/)).toBeInTheDocument()
    expect(screen.getByText(/MCP calls observed: github\.search/)).toBeInTheDocument()
    expect(screen.queryByText('Network policy enforced')).not.toBeInTheDocument()
  })
})
