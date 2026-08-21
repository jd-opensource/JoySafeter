import { describe, expect, it } from 'vitest'

import nextConfig from './next.config'

describe('management route redirects', () => {
  it('does not preserve the removed top-level member-management route', async () => {
    const redirects = await nextConfig.redirects?.()

    expect(redirects).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ source: '/managed/members' })]),
    )
    expect(redirects).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ source: '/managed/settings/members' })]),
    )
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
