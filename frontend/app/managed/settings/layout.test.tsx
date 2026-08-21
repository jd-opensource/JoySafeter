import { render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement

describe('OrganizationSettingsLayout', () => {
  it('keeps the organization collection free of entity-scoped tabs', async () => {
    const { default: OrganizationSettingsLayout } = await import('./layout')
    const view = render(
      <OrganizationSettingsLayout>
        <div>settings-content</div>
      </OrganizationSettingsLayout>,
    )

    expect(view.getByText('settings-content')).toBeTruthy()
    expect(view.container.querySelector('nav')).toBeNull()
  })
})
