import { fireEvent, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

import { DataTable, type Column } from './data-table'

type Row = { id: string; name: string }
const columns: Column<Row>[] = [
  { key: 'name', header: 'Name', render: (r) => <span>{r.name}</span> },
]

describe('DataTable row accessibility', () => {
  it('supports an embedded presentation without a nested card border', () => {
    const { getByTestId } = render(
      <DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} variant="embedded" />,
    )

    expect(getByTestId('data-table-surface')).toHaveAttribute('data-variant', 'embedded')
    expect(getByTestId('data-table-surface')).not.toHaveClass('rounded-lg', 'border')
  })

  it('marks rows as keyboard-actionable when onRowClick is provided', () => {
    const onRowClick = vi.fn()
    const { getAllByRole } = render(
      <DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} onRowClick={onRowClick} />,
    )
    const row = getAllByRole('button').find((el) => el.tagName === 'TR')!
    expect(row.getAttribute('tabindex')).toBe('0')
  })

  it('activates onRowClick via keyboard (Enter)', () => {
    const onRowClick = vi.fn()
    const { getAllByRole } = render(
      <DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} onRowClick={onRowClick} />,
    )
    const row = getAllByRole('button').find((el) => el.tagName === 'TR')!
    fireEvent.keyDown(row, { key: 'Enter' })
    expect(onRowClick).toHaveBeenCalledWith({ id: 'a', name: 'Row A' })
  })

  it('activates onRowClick via keyboard (Space)', () => {
    const onRowClick = vi.fn()
    const { getAllByRole } = render(
      <DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} onRowClick={onRowClick} />,
    )
    const row = getAllByRole('button').find((el) => el.tagName === 'TR')!
    fireEvent.keyDown(row, { key: ' ' })
    expect(onRowClick).toHaveBeenCalledWith({ id: 'a', name: 'Row A' })
  })

  it('does not add role/tabIndex when onRowClick is absent', () => {
    const { queryAllByRole } = render(
      <DataTable columns={columns} data={[{ id: 'a', name: 'Row A' }]} />,
    )
    expect(queryAllByRole('button').filter((el) => el.tagName === 'TR')).toHaveLength(0)
  })

  it.each(['Enter', ' '])(
    'does not activate the row when an interactive child handles %s',
    (key) => {
      const onRowClick = vi.fn()
      const interactiveColumns: Column<Row>[] = [
        ...columns,
        {
          key: 'actions',
          header: 'Actions',
          render: () => <button type="button">Open actions</button>,
        },
      ]
      const { getByRole } = render(
        <DataTable
          columns={interactiveColumns}
          data={[{ id: 'a', name: 'Row A' }]}
          onRowClick={onRowClick}
        />,
      )

      fireEvent.keyDown(getByRole('button', { name: 'Open actions' }), { key })

      expect(onRowClick).not.toHaveBeenCalled()
    },
  )
})
