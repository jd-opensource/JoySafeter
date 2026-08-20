import { describe, expect, it } from 'vitest'

import { deriveQuickstartLaunchAssurance } from './quickstart-launch-assurance'

describe('deriveQuickstartLaunchAssurance', () => {
  it('reports enforced and ready controls without overstating optional authorization', () => {
    expect(
      deriveQuickstartLaunchAssurance({
        hasRuntime: true,
        hasModelConnection: true,
        hasEnvironment: true,
        hasExternalToolAuthorization: true,
      }),
    ).toEqual({
      runtime: 'ready',
      modelConnection: 'ready',
      environment: 'enforced',
      externalTools: 'ready',
      audit: 'automatic',
      needsHardening: false,
    })
  })

  it('distinguishes recommended hardening from tools that are not authorized', () => {
    expect(
      deriveQuickstartLaunchAssurance({
        hasRuntime: true,
        hasModelConnection: true,
        hasEnvironment: false,
        hasExternalToolAuthorization: false,
      }),
    ).toEqual({
      runtime: 'ready',
      modelConnection: 'ready',
      environment: 'recommended',
      externalTools: 'not_authorized',
      audit: 'automatic',
      needsHardening: true,
    })
  })
})
