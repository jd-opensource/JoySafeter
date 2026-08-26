import { describe, expect, it } from 'vitest'

import {
  deriveQuickstartCapabilityEvidence,
  filterQuickstartSkillReferences,
  isMcpServerAuthorized,
  normalizeMcpServerUrl,
  quickstartAuthorizedMcpServerUrls,
  toQuickstartAvailableSkills,
} from './quickstart-capabilities'

const SKILL_ID = 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111'
const OTHER_SKILL_ID = 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f222'

describe('toQuickstartAvailableSkills', () => {
  it('exposes every published skill regardless of current runtime eligibility', () => {
    expect(
      toQuickstartAvailableSkills([
        {
          id: SKILL_ID,
          name: 'secure-review',
          display_title: 'Secure Review',
          description: 'Review code safely',
          latest_version: '1.2.0',
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

describe('normalizeMcpServerUrl', () => {
  it('trims whitespace and a single trailing slash so equivalent URLs match', () => {
    expect(normalizeMcpServerUrl('  HTTPS://MCP.example.com:443/  ')).toBe(
      'https://mcp.example.com',
    )
    expect(normalizeMcpServerUrl('https://mcp.example.com')).toBe('https://mcp.example.com')
  })

  it('returns empty string for missing or non-string values', () => {
    expect(normalizeMcpServerUrl(undefined)).toBe('')
    expect(normalizeMcpServerUrl(null)).toBe('')
    expect(normalizeMcpServerUrl('   ')).toBe('')
  })
})

describe('quickstartAuthorizedMcpServerUrls', () => {
  it('collects normalized URLs from active members only', () => {
    const set = quickstartAuthorizedMcpServerUrls([
      { mcp_server_url: 'https://mcp.example.com/' },
      { mcp_server_url: 'https://archived.example.com', archived_at: '2026-08-01T00:00:00Z' },
      { mcp_server_url: '' },
      { mcp_server_url: '  https://second.example.com  ' },
    ])
    expect(set).toEqual(new Set(['https://mcp.example.com', 'https://second.example.com']))
  })
})

describe('isMcpServerAuthorized', () => {
  const authorized = new Set(['https://mcp.example.com'])

  it('matches an agent MCP server URL against the authorized set after normalization', () => {
    expect(isMcpServerAuthorized('https://mcp.example.com/', authorized)).toBe(true)
  })

  it('does not authorize an unmatched or empty URL', () => {
    expect(isMcpServerAuthorized('https://other.example.com', authorized)).toBe(false)
    expect(isMcpServerAuthorized('', authorized)).toBe(false)
  })
})

describe('deriveQuickstartCapabilityEvidence', () => {
  it('summarizes only observable environment, authorization, tool, and MCP evidence', () => {
    expect(
      deriveQuickstartCapabilityEvidence({
        responseReceived: true,
        environmentId: 'env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f031',
        externalToolsAuthorized: true,
        configuredSkills: ['Secure Review'],
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
      configuredSkills: ['Secure Review'],
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
        externalToolsAuthorized: false,
        events: [],
      }),
    ).toEqual({
      responseReceived: false,
      environmentAttached: false,
      externalToolsAuthorized: false,
      configuredSkills: [],
      observedTools: [],
      observedMcpTools: [],
      auditEventsAvailable: false,
    })
  })
})
