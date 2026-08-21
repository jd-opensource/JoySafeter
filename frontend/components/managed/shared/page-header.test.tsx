import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PageHeader } from './page-header'

describe('PageHeader responsive actions', () => {
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
})
