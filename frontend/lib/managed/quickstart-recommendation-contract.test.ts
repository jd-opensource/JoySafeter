import { describe, expect, it } from 'vitest'

import contract from '../../../backend/contracts/quickstart_recommendation_contract.json'

import {
  QUICKSTART_ENGINE_READINESS,
  QUICKSTART_EXTERNAL_TOOLS_REASONS,
  QUICKSTART_HOST_REASONS,
  QUICKSTART_MCP_AUTH_REQUIREMENTS,
  QUICKSTART_RECOMMENDATION_PHASES,
} from './quickstart-recommendation-contract'

describe('quickstart recommendation contract parity (FE mirror vs backend JSON)', () => {
  it('freezes the contract version', () => {
    expect(contract.contract_version).toBe('quickstart_recommendation.v4')
  })

  it('mirrors every enum from the backend contract', () => {
    expect([...QUICKSTART_RECOMMENDATION_PHASES]).toEqual(contract.phases)
    expect([...QUICKSTART_ENGINE_READINESS]).toEqual(contract.engine_readiness)
    expect([...QUICKSTART_HOST_REASONS]).toEqual(contract.host_reasons)
    expect([...QUICKSTART_EXTERNAL_TOOLS_REASONS]).toEqual(contract.external_tools_reasons)
    expect([...QUICKSTART_MCP_AUTH_REQUIREMENTS]).toEqual(contract.mcp_auth_requirements)
  })

  it('contains only recommendation phases and production-backed fields', () => {
    expect(contract.phases).toEqual(['understand', 'secure'])
    expect(JSON.stringify(contract.schema)).not.toMatch(
      /"source"|"confidence"|"controls"|"networking_type"/,
    )
  })
})
