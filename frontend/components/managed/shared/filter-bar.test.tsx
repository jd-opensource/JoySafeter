import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

import { FilterBar } from './filter-bar'

describe('FilterBar responsive layout', () => {
  it('uses full-width controls on narrow screens', () => {
    const view = render(
      <FilterBar
        searchPlaceholder="Search organizations"
        searchValue=""
        onSearchChange={vi.fn()}
        filters={[
          {
            key: 'created',
            label: 'Created',
            value: 'all',
            onChange: vi.fn(),
            options: [{ value: 'all', label: 'All Time' }],
          },
        ]}
        showArchived={false}
        onArchivedChange={vi.fn()}
      />,
    )

    expect(view.getByTestId('filter-bar')).toHaveClass('flex-col', 'sm:flex-row')
    expect(view.getByPlaceholderText('Search organizations')).toHaveClass('w-full', 'sm:w-[240px]')
    expect(view.getByRole('combobox')).toHaveClass('w-full', 'sm:w-auto')
    expect(view.getByText('managed.filters.showArchived').closest('label')).toHaveClass(
      'w-full',
      'sm:w-auto',
    )
  })
})
