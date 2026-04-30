import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { VersionFormDialog } from '../version-form-dialog'

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@/hooks/queries/agentVersions', () => ({
  useCreateVersion: () => ({
    isPending: false,
    mutate: vi.fn(),
  }),
}))

vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string
    onValueChange: (value: string) => void
    children: React.ReactNode
  }) => {
    const options: Array<{ value: string; label: React.ReactNode }> = []

    function collect(node: React.ReactNode): void {
      if (!node) return
      if (Array.isArray(node)) {
        node.forEach(collect)
        return
      }
      if (typeof node !== 'object') return
      if (!('props' in node)) return

      const element = node as {
        type?: unknown
        props?: { value?: string; children?: React.ReactNode }
      }

      if (typeof element.props?.value === 'string') {
        options.push({ value: element.props.value, label: element.props.children })
      }

      collect(element.props?.children)
    }

    collect(children)

    return (
      <select
        aria-label="definition-kind"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    )
  },
  SelectTrigger: ({ children }: { children?: React.ReactNode }) => children,
  SelectValue: () => null,
  SelectContent: ({ children }: { children?: React.ReactNode }) => children,
  SelectItem: ({ children }: { children?: React.ReactNode }) => children,
}))

function TestHarness() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      <VersionFormDialog
        open={open}
        onOpenChange={setOpen}
        agentId="agent-1"
        workspaceId="workspace-1"
      />
    </>
  )
}

describe('VersionFormDialog', () => {
  it('resets form state after closing and reopening', async () => {
    const user = userEvent.setup()

    render(<TestHarness />)

    await user.click(screen.getByRole('button', { name: 'Open dialog' }))
    await user.selectOptions(screen.getByLabelText('definition-kind'), 'openclaw')
    await user.type(screen.getByPlaceholderText('agents.detail.changelogPlaceholder'), 'draft note')

    expect(screen.getByLabelText('definition-kind')).toHaveValue('openclaw')
    expect(screen.getByPlaceholderText('agents.detail.changelogPlaceholder')).toHaveValue('draft note')

    await user.click(screen.getByRole('button', { name: 'agents.cancel' }))
    await user.click(screen.getByRole('button', { name: 'Open dialog' }))

    expect(screen.getByLabelText('definition-kind')).toHaveValue('langgraph_visual')
    expect(screen.getByPlaceholderText('agents.detail.changelogPlaceholder')).toHaveValue('')
  })
})
