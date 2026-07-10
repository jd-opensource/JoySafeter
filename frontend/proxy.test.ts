import { NextRequest } from 'next/server'
import { describe, expect, it } from 'vitest'

import { proxy } from './proxy'

describe('proxy callback URL validation', () => {
  it('removes same-prefix callback URLs that are not on an allowed path boundary', async () => {
    const request = new NextRequest('http://localhost/signin?callbackUrl=/dashboardevil')

    const response = await proxy(request)

    expect(response.status).toBeGreaterThanOrEqual(300)
    expect(response.status).toBeLessThan(400)
    const location = response.headers.get('location')
    expect(location).toBe('http://localhost/signin')
  })
})
