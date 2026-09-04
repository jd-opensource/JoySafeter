import { describe, expect, it } from 'vitest'

import { AGENT_ID, ENVIRONMENT_ID, SESSION_ID, VAULT_ID } from '@/test-utils/entity-ids'

import { QUICKSTART_STEP } from './quickstart-flow'
import {
  isQuickstartCreatedResourceStep,
  parseQuickstartResourceId,
  quickstartResourceApiPath,
  quickstartResourceEndpoint,
} from './quickstart-resource-contract'

describe('quickstart resource contract', () => {
  it.each([
    [QUICKSTART_STEP.AGENT, 'agents', '/agents', AGENT_ID],
    [QUICKSTART_STEP.ENVIRONMENT, 'environments', '/environments', ENVIRONMENT_ID],
    [QUICKSTART_STEP.CREDENTIAL_GROUP, 'credential-groups', '/credential-groups', VAULT_ID],
    [QUICKSTART_STEP.SESSION, 'sessions', '/sessions', SESSION_ID],
  ] as const)('maps step %s to one API and ID contract', (step, apiPath, endpoint, resourceId) => {
    expect(quickstartResourceApiPath(step)).toBe(apiPath)
    expect(quickstartResourceEndpoint(step)).toBe(endpoint)
    expect(parseQuickstartResourceId(step, resourceId)).toBe(resourceId)
  })

  it('distinguishes durable setup resources from the trial session', () => {
    expect(isQuickstartCreatedResourceStep(QUICKSTART_STEP.AGENT)).toBe(true)
    expect(isQuickstartCreatedResourceStep(QUICKSTART_STEP.ENVIRONMENT)).toBe(true)
    expect(isQuickstartCreatedResourceStep(QUICKSTART_STEP.CREDENTIAL_GROUP)).toBe(true)
    expect(isQuickstartCreatedResourceStep(QUICKSTART_STEP.SESSION)).toBe(false)
  })
})
