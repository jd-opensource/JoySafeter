import { describe, expect, it } from 'vitest'

import nextConfig from './next.config'

describe('management route redirects', () => {
  it('routes project access-token management to projects', async () => {
    const redirects = await nextConfig.redirects?.()

    expect(redirects).toEqual(
      expect.arrayContaining([
        {
          source: '/managed/api-keys',
          destination: '/managed/projects',
          permanent: true,
        },
      ]),
    )
  })
})
