import { vi } from 'vitest'
import '@testing-library/jest-dom/vitest'

// jsdom does not implement scrollIntoView (or it is not a function)
if (typeof Element !== 'undefined') {
  Element.prototype.scrollIntoView = vi.fn()
}
