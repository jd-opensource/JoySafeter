import { describe, expect, it } from 'vitest'

import {
  deriveQuickstartCapabilityEvidence,
  filterQuickstartSkillReferences,
  toQuickstartAvailableSkills,
} from './quickstart-capabilities'

const SKILL_ID = 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111'
const OTHER_SKILL_ID = 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f222'

describe('toQuickstartAvailableSkills', () => {
  it('only exposes published runtime-eligible skills to generation', () => {
    expect(
      toQuickstartAvailableSkills([
        {
          id: SKILL_ID,
          name: 'secure-review',
          display_title: 'Secure Review',
          description: 'Review code safely',
          latest_version: '1.2.0',
          runtime_eligibility: { usable: true },
        },
        {
          id: OTHER_SKILL_ID,
          name: 'draft-skill',
          description: 'Not published',
          latest_version: null,
        },
      ]),
    ).toEqual([
      {
        id: SKILL_ID,
        name: 'secure-review',
        display_title: 'Secure Review',
        description: 'Review code safely',
        latest_version: '1.2.0',
      },
    ])
  })
})

describe('filterQuickstartSkillReferences', () => {
  it('drops model-generated skill ids that are outside the supplied catalog', () => {
    expect(
      filterQuickstartSkillReferences(
        [
          { type: 'custom', skill_id: SKILL_ID, version: 'latest' },
          { type: 'custom', skill_id: OTHER_SKILL_ID, version: 'latest' },
        ],
        new Set([SKILL_ID]),
      ),
    ).toEqual([{ type: 'custom', skill_id: SKILL_ID, version: 'latest' }])
  })
})

describe('deriveQuickstartCapabilityEvidence', () => {
  it('summarizes only observable environment, authorization, tool, and MCP evidence', () => {
    expect(
      deriveQuickstartCapabilityEvidence({
        responseReceived: true,
        environmentId: 'env_1',
        credentialGroupId: 'credgrp_1',
        events: [
          { type: 'agent.tool_use', tool_name: 'Read' },
          { type: 'agent.mcp_tool_use', tool_name: 'github.search' },
          { type: 'session.status_idle' },
        ],
      }),
    ).toEqual({
      responseReceived: true,
      environmentAttached: true,
      externalToolsAuthorized: true,
      observedTools: ['Read'],
      observedMcpTools: ['github.search'],
      auditEventsAvailable: true,
    })
  })

  it('does not claim controls or calls that were not observed', () => {
    expect(
      deriveQuickstartCapabilityEvidence({
        responseReceived: false,
        environmentId: null,
        credentialGroupId: null,
        events: [],
      }),
    ).toEqual({
      responseReceived: false,
      environmentAttached: false,
      externalToolsAuthorized: false,
      observedTools: [],
      observedMcpTools: [],
      auditEventsAvailable: false,
    })
  })
})
