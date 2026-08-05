import { vi } from 'vitest'
import '@testing-library/jest-dom/vitest'

function createMemoryStorage(): Storage {
  const entries = new Map<string, string>()
  return {
    get length() {
      return entries.size
    },
    clear: () => entries.clear(),
    getItem: (key) => entries.get(key) ?? null,
    key: (index) => Array.from(entries.keys())[index] ?? null,
    removeItem: (key) => entries.delete(key),
    setItem: (key, value) => entries.set(key, String(value)),
  }
}

if (typeof globalThis.localStorage === 'undefined' || !globalThis.localStorage?.setItem) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: createMemoryStorage(),
  })
}

if (typeof globalThis.sessionStorage === 'undefined' || !globalThis.sessionStorage?.setItem) {
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: createMemoryStorage(),
  })
}

// jsdom does not implement scrollIntoView (or it is not a function)
if (typeof Element !== 'undefined') {
  Element.prototype.scrollIntoView = vi.fn()
}
