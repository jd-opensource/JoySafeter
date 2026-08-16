import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@/components/managed/shared/data-table', () => ({
  DataTable: ({ data, variant }: { data: Array<{ id: string }>; variant?: string }) => (
    <div data-testid="desktop-table" data-variant={variant}>
      {data.map((row) => row.id).join(',')}
    </div>
  ),
}))
vi.mock('@/components/ui/pagination', () => ({
  Pagination: () => <div data-testid="mobile-pagination" />,
}))
vi.mock('@/components/managed/shared/action-menu', () => ({
  ActionMenu: ({ items }: { items: Array<{ onClick: () => void }> }) => (
    <button type="button" onClick={items[0]?.onClick}>
      mobile-actions
    </button>
  ),
}))
vi.mock('@/components/managed/shared/copy-button', () => ({
  CopyButton: ({ value }: { value: string }) => <button type="button">copy:{value}</button>,
}))

import { CredentialIdentity } from './credential-identity'
import { CredentialListPanel } from './credential-list-panel'

const rows = [{ id: 'cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f061', name: 'Primary model' }]

function panel(
  overrides: {
    data?: typeof rows
    searchValue?: string
    createdValue?: string
    showArchived?: boolean
    onRowClick?: (row: (typeof rows)[number]) => void
  } = {},
) {
  const onCreatedChange = vi.fn()
  const onArchivedChange = vi.fn()
  const onCreate = vi.fn()
  const onClearFilters = vi.fn()
  const onRowClick = overrides.onRowClick ?? vi.fn()
  render(
    <CredentialListPanel
      data={overrides.data ?? rows}
      columns={[]}
      searchPlaceholder="Search resources"
      searchValue={overrides.searchValue ?? ''}
      onSearchChange={vi.fn()}
      filters={[
        {
          key: 'created',
          label: 'Created time',
          value: overrides.createdValue ?? 'all',
          onChange: onCreatedChange,
          options: [
            { value: 'all', label: 'All time' },
            { value: '7d', label: 'Last 7 days' },
          ],
        },
      ]}
      showArchived={overrides.showArchived ?? false}
      onArchivedChange={onArchivedChange}
      createAction={{ label: 'New model connection', onClick: onCreate }}
      emptyState={{ title: 'No resources', description: 'Create the first resource.' }}
      noResultsState={{ title: 'No matches', description: 'Change search or filters.' }}
      onClearFilters={onClearFilters}
      onRowClick={onRowClick}
      actionMenu={() => [{ label: 'Archive', onClick: vi.fn() }]}
      mobileCard={(row) => <span>{row.name}</span>}
      pagination={{
        hasNext: false,
        hasPrev: false,
        page: 1,
        pageSize: 10,
        pageSizeOptions: [10, 25, 50],
        onNext: vi.fn(),
        onPrev: vi.fn(),
        onPageChange: vi.fn(),
        onPageSizeChange: vi.fn(),
      }}
    />,
  )
  return { onCreatedChange, onArchivedChange, onCreate, onClearFilters, onRowClick }
}

describe('CredentialListPanel', () => {
  it('collapses low-frequency filters and exposes one contextual create action', async () => {
    const user = userEvent.setup()
    const { onCreate } = panel()
    expect(screen.queryByText('Last 7 days')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'New model connection' }))
    expect(onCreate).toHaveBeenCalledTimes(1)
    await user.click(screen.getByRole('button', { name: 'managed.credentials.filters.open' }))
    expect(await screen.findByText('Last 7 days')).toBeInTheDocument()
  })

  it('shows active filter chips and clears individual filters', () => {
    const { onCreatedChange, onArchivedChange } = panel({ createdValue: '7d', showArchived: true })
    expect(screen.getByText('Last 7 days')).toBeInTheDocument()
    expect(screen.getByText('managed.filters.showArchived')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'managed.credentials.filters.removeCreated' }),
    )
    expect(onCreatedChange).toHaveBeenCalledWith('all')
    fireEvent.click(
      screen.getByRole('button', { name: 'managed.credentials.filters.removeArchived' }),
    )
    expect(onArchivedChange).toHaveBeenCalledWith(false)
  })

  it('renders mobile cards with keyboard navigation and isolated nested actions', async () => {
    const user = userEvent.setup()
    const onRowClick = vi.fn()
    panel({ onRowClick })
    const cardAction = screen.getByRole('button', { name: 'Primary model' })
    const card = cardAction.closest('article')
    expect(card).not.toBeNull()
    cardAction.focus()
    await user.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledWith(rows[0])
    const nestedAction = within(card!).getByRole('button', { name: 'mobile-actions' })
    expect(cardAction.contains(nestedAction)).toBe(false)
    fireEvent.click(nestedAction)
    expect(onRowClick).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('desktop-table')).toHaveAttribute('data-variant', 'embedded')
    expect(screen.getByTestId('mobile-pagination')).toBeInTheDocument()
  })

  it('distinguishes empty collections from filtered no-results', () => {
    const { unmount } = render(
      <CredentialListPanel
        data={[]}
        columns={[]}
        searchPlaceholder="Search"
        searchValue=""
        onSearchChange={vi.fn()}
        filters={[]}
        emptyState={{ title: 'No resources', description: 'Create the first resource.' }}
        noResultsState={{ title: 'No matches', description: 'Change search or filters.' }}
        createAction={{ label: 'Create resource', onClick: vi.fn() }}
        onClearFilters={vi.fn()}
        mobileCard={() => null}
      />,
    )
    expect(screen.getByText('No resources')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create resource' })).toBeInTheDocument()
    unmount()

    const onClearFilters = vi.fn()
    render(
      <CredentialListPanel
        data={[]}
        columns={[]}
        searchPlaceholder="Search"
        searchValue="missing"
        onSearchChange={vi.fn()}
        filters={[]}
        emptyState={{ title: 'No resources', description: 'Create the first resource.' }}
        noResultsState={{ title: 'No matches', description: 'Change search or filters.' }}
        onClearFilters={onClearFilters}
        mobileCard={() => null}
      />,
    )
    expect(screen.getByText('No matches')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'managed.credentials.filters.clearAll' }))
    expect(onClearFilters).toHaveBeenCalledTimes(1)
  })

  it('shows only one clear-all action when filters produce no results', () => {
    panel({ data: [], createdValue: '7d' })

    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(
      screen.getAllByRole('button', { name: 'managed.credentials.filters.clearAll' }),
    ).toHaveLength(1)
  })
})

describe('CredentialIdentity', () => {
  it('presents the name before the public ID and isolates copy interaction', () => {
    const onParentClick = vi.fn()
    render(
      <div onClick={onParentClick}>
        <CredentialIdentity
          name="Primary model"
          publicId="cred_019ecaa6-d04f-72d1-9939-f57ae98b09e1"
          subtitle="Claude-Opus-4.6"
          badges={<span>active</span>}
        />
      </div>,
    )
    const relation = screen
      .getByText('Primary model')
      .compareDocumentPosition(screen.getByText(/cred_019ecaa6/))
    expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /copy:cred_/ }))
    expect(onParentClick).not.toHaveBeenCalled()
  })
})
