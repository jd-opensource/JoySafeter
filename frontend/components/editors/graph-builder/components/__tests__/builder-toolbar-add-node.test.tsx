import React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { BuilderToolbar } from '../BuilderToolbar'

const permissionState = vi.hoisted(() => ({
  canEdit: true,
  canAdmin: true,
}))

const executionState = vi.hoisted(() => ({
  showPanel: true,
}))

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}))

vi.mock('@/components/ui/dropdown-menu', () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children, onClick, disabled }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) => (
    <button type="button" onClick={onClick} disabled={disabled}>
      {children}
    </button>
  ),
  DropdownMenuSeparator: () => <hr />,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/components/ui/popover', () => {
  const PopoverContext = React.createContext<{
    open: boolean
    setOpen: (open: boolean) => void
  } | null>(null)

  return {
    Popover: ({
      open,
      onOpenChange,
      children,
    }: {
      open?: boolean
      onOpenChange?: (open: boolean) => void
      children: React.ReactNode
    }) => {
      const [internalOpen, setInternalOpen] = React.useState(false)
      const actualOpen = open ?? internalOpen
      const setOpen = (nextOpen: boolean) => {
        onOpenChange?.(nextOpen)
        if (open === undefined) {
          setInternalOpen(nextOpen)
        }
      }

      return (
        <PopoverContext.Provider value={{ open: actualOpen, setOpen }}>
          <div>{children}</div>
        </PopoverContext.Provider>
      )
    },
    PopoverTrigger: ({ children }: { children: React.ReactElement<{ onClick?: () => void }> }) => {
      const context = React.useContext(PopoverContext)
      return React.cloneElement(children, {
        onClick: () => {
          children.props.onClick?.()
          context?.setOpen(true)
        },
      })
    },
    PopoverContent: ({ children }: { children: React.ReactNode }) => {
      const context = React.useContext(PopoverContext)
      return context?.open ? <div data-testid="add-node-popover">{children}</div> : null
    },
  }
})

vi.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/hooks/queries/agentVersions', () => ({
  versionKeys: { all: () => ['versions'] },
}))

vi.mock('@/lib/i18n', () => ({
  useTranslation: () => ({
    t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key,
  }),
}))

vi.mock('@/providers/workspace-permissions-provider', () => ({
  useUserPermissionsContext: () => permissionState,
}))

vi.mock('@/providers/workspace-provider', () => ({
  useCurrentWorkspace: () => ({ workspaceId: 'workspace-1' }),
}))

vi.mock('../../services/deploymentAdapter', () => ({
  deploymentAdapter: { deploy: vi.fn() },
}))

vi.mock('../../stores/builderStore', () => ({
  useBuilderStore: Object.assign(
    (selector: (state: { deployedAt: null; setDeployedAt: () => void }) => unknown) =>
      selector({ deployedAt: null, setDeployedAt: vi.fn() }),
    { getState: () => ({ versionId: 'version-1' }) },
  ),
}))

vi.mock('../../stores/execution/executionStore', () => ({
  useExecutionStore: () => ({
    isExecuting: false,
    stopExecution: vi.fn(),
    showPanel: executionState.showPanel,
    togglePanel: vi.fn(),
  }),
}))

vi.mock('../AddNodePalette', () => ({
  AddNodePalette: ({ onSelect }: { onSelect: (node: { type: string; label: string }) => void }) => (
    <button type="button" onClick={() => onSelect({ type: 'agent', label: 'Agent' })}>
      Select Agent
    </button>
  ),
}))

vi.mock('../ApiAccessDialog', () => ({
  ApiAccessDialog: () => null,
}))

vi.mock('../DeploymentHistoryPanel', () => ({
  DeploymentHistoryPanel: () => null,
}))

const renderToolbar = (onAddNode = vi.fn()) =>
  render(
    <BuilderToolbar
      onImport={vi.fn()}
      onExport={vi.fn()}
      onRunClick={vi.fn()}
      agentId="agent-1"
      nodesCount={1}
      onAddNode={onAddNode}
    />,
  )

const renderStudioToolbar = ({
  onOpenTestLab = vi.fn(),
  onOpenRelease = vi.fn(),
}: {
  onOpenTestLab?: () => void
  onOpenRelease?: () => void
} = {}) =>
  render(
    <BuilderToolbar
      onImport={vi.fn()}
      onExport={vi.fn()}
      onRunClick={vi.fn()}
      agentId="agent-1"
      nodesCount={1}
      onAddNode={vi.fn()}
      studioMode
      onOpenTestLab={onOpenTestLab}
      onOpenRelease={onOpenRelease}
    />,
  )

describe('BuilderToolbar add node palette', () => {
  it('does not render Add for read-only users', () => {
    permissionState.canEdit = false

    renderToolbar()

    expect(screen.queryByText('Add')).not.toBeInTheDocument()
  })

  it('closes the Add popover after selecting a node', () => {
    permissionState.canEdit = true
    const onAddNode = vi.fn()

    renderToolbar(onAddNode)
    fireEvent.click(screen.getByText('Add'))
    expect(screen.getByTestId('add-node-popover')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Select Agent'))

    expect(onAddNode).toHaveBeenCalledWith({ type: 'agent', label: 'Agent' })
    expect(screen.queryByTestId('add-node-popover')).not.toBeInTheDocument()
  })

  it('uses lifecycle navigation instead of direct run and publish in Studio mode', () => {
    permissionState.canEdit = true
    permissionState.canAdmin = true
    executionState.showPanel = false
    const onOpenTestLab = vi.fn()
    const onOpenRelease = vi.fn()

    renderStudioToolbar({ onOpenTestLab, onOpenRelease })

    expect(screen.queryByText('Run Draft')).not.toBeInTheDocument()
    expect(screen.queryByText('Publish')).not.toBeInTheDocument()
    expect(screen.queryByText('workspace.deploymentHistory')).not.toBeInTheDocument()
    expect(screen.queryByText('Access API')).not.toBeInTheDocument()
    expect(screen.queryByText('workspace.showExecutionPanel')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('Test Lab'))
    fireEvent.click(screen.getByText('Release'))

    expect(onOpenTestLab).toHaveBeenCalledTimes(1)
    expect(onOpenRelease).toHaveBeenCalledTimes(1)
    executionState.showPanel = true
  })
})
