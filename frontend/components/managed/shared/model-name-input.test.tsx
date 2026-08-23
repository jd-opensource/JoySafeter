import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { JSDOM } from 'jsdom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'

const previousHTMLElement = globalThis.HTMLElement
if (previousHTMLElement) {
  Object.defineProperty(previousHTMLElement.prototype, 'attachEvent', {
    configurable: true,
    value: () => {},
  })
  Object.defineProperty(previousHTMLElement.prototype, 'detachEvent', {
    configurable: true,
    value: () => {},
  })
}
Object.defineProperty(Object.prototype, 'attachEvent', {
  configurable: true,
  value: () => {},
})
Object.defineProperty(Object.prototype, 'detachEvent', {
  configurable: true,
  value: () => {},
})

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost' })
globalThis.window = dom.window as unknown as Window & typeof globalThis
globalThis.document = dom.window.document
globalThis.navigator = dom.window.navigator
globalThis.HTMLElement = dom.window.HTMLElement
globalThis.localStorage = dom.window.localStorage
Object.defineProperty(globalThis.HTMLElement.prototype, 'attachEvent', {
  configurable: true,
  value: () => {},
})
Object.defineProperty(globalThis.HTMLElement.prototype, 'detachEvent', {
  configurable: true,
  value: () => {},
})

describe('ModelNameInput dropdown lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('does not let an older blur timer close a dropdown that was reopened by focus', async () => {
    const modelNameInputModulePath = './model-name-input.tsx?dropdown-lifecycle-test'
    const { ModelNameInput } = await import(modelNameInputModulePath)
    function ControlledModelNameInput() {
      const [value, setValue] = useState('')
      return <ModelNameInput value={value} onChange={setValue} placeholder="model" />
    }

    const { getByPlaceholderText, getByText } = render(<ControlledModelNameInput />)
    const input = getByPlaceholderText('model')

    await act(async () => {
      fireEvent.focus(input)
    })

    expect(getByText('GPT-5.5')).toBeTruthy()

    await act(async () => {
      fireEvent.blur(input)
      vi.advanceTimersByTime(60)
      fireEvent.focus(input)
    })

    expect(getByText('GPT-5.5')).toBeTruthy()

    await act(async () => {
      vi.advanceTimersByTime(70)
    })

    expect(getByText('GPT-5.5')).toBeTruthy()
  })
})
