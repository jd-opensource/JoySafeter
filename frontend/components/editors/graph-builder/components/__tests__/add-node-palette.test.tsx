import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AddNodePalette } from '../AddNodePalette'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}))

vi.mock('../../services/nodeRegistry', () => ({
  nodeRegistry: {
    getGrouped: () => ({
      Core: [
        {
          type: 'agent',
          label: 'Agent',
          subLabel: 'LLM Process',
          icon: () => <span data-testid="agent-icon" />,
          style: { color: '', bg: '' },
        },
        {
          type: 'code_agent',
          label: 'Code Agent',
          subLabel: 'Python',
          icon: () => <span data-testid="code-icon" />,
          style: { color: '', bg: '' },
        },
      ],
    }),
  },
}))

describe('AddNodePalette', () => {
  it('filters nodes by query and selects the requested node', () => {
    const onSelect = vi.fn()
    render(<AddNodePalette onSelect={onSelect} />)

    fireEvent.change(screen.getByPlaceholderText('Search nodes...'), {
      target: { value: 'code' },
    })

    expect(screen.queryByText('Agent')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Code Agent'))

    expect(onSelect).toHaveBeenCalledWith({
      type: 'code_agent',
      label: 'Code Agent',
    })
  })
})
