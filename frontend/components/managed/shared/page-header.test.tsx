import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PageHeader } from './page-header'

describe('PageHeader', () => {
  it('stacks the primary action below the title on narrow screens', () => {
    const view = render(
      <PageHeader title="Members" subtitle="Organization scope" action={<button>Invite</button>} />,
    )

    expect(view.getByTestId('page-header')).toHaveClass('flex-col', 'sm:flex-row')
    expect(view.getByTestId('page-header-action')).toHaveClass(
      'w-full',
      'sm:w-auto',
      '[&>*]:w-full',
      'sm:[&>*]:w-auto',
    )
  })

  it('renders icon tile when icon prop is provided', () => {
    const view = render(<PageHeader title="Project A" icon={<svg data-testid="test-icon" />} />)

    const iconTile = view.getByTestId('page-header-icon')
    expect(iconTile).toBeInTheDocument()
    expect(iconTile).toHaveClass('size-10', 'rounded-lg', 'bg-muted')
    expect(view.getByTestId('test-icon')).toBeInTheDocument()
  })

  it('renders breadcrumb with separator when provided', () => {
    const view = render(
      <PageHeader
        title="Agent Detail"
        breadcrumb={[
          { label: 'Agents', to: '/agents' },
          { label: 'Current Agent' },
        ]}
      />,
    )

    const breadcrumb = view.container.querySelector('nav')
    expect(breadcrumb).toBeInTheDocument()
    expect(breadcrumb).toHaveTextContent('Agents')
    expect(breadcrumb).toHaveTextContent('Current Agent')
    expect(breadcrumb).toHaveTextContent('/')
    expect(view.getByRole('heading', { level: 1 })).toHaveTextContent('Agent Detail')
  })

  it('does not render icon tile when icon prop is omitted', () => {
    const view = render(<PageHeader title="Plain Title" />)
    expect(view.queryByTestId('page-header-icon')).not.toBeInTheDocument()
  })
})
