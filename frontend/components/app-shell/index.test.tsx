import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('next/navigation', () => ({ usePathname: () => '/managed/credentials' }))
vi.mock('@/components/app-sidebar', () => ({ AppSidebar: () => <aside /> }))
vi.mock('@/lib/core/constants/routes', () => ({ isPublicRoute: () => false }))
vi.mock('@/stores/sidebar/store', () => ({
  useSidebarStore: (selector: (state: { isCollapsed: boolean }) => boolean) =>
    selector({ isCollapsed: false }),
}))

import { AppShell } from './index'

describe('AppShell responsive layout', () => {
  it('reserves only the compact rail width on mobile', () => {
    const { getByRole } = render(
      <AppShell>
        <div>content</div>
      </AppShell>,
    )

    expect(getByRole('main')).toHaveClass('ml-[52px]', 'sm:ml-[220px]')
  })
})
