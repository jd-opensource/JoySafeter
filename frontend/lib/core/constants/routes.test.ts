import { describe, expect, it } from 'vitest'

import { isPublicRoute } from './routes'

describe('isPublicRoute', () => {
  it('matches public routes by path segment boundary only', () => {
    expect(isPublicRoute('/signin')).toBe(true)
    expect(isPublicRoute('/signin/help')).toBe(true)
    expect(isPublicRoute('/signin-admin')).toBe(false)
    expect(isPublicRoute('/verify-anything')).toBe(false)
  })
})
