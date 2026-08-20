import { describe, expect, it } from 'vitest'

import {
  normalizeQuickstartAgentBlueprint,
  quickstartBlueprintMetadata,
} from './quickstart-agent-blueprint'

describe('normalizeQuickstartAgentBlueprint', () => {
  it('normalizes a complete professional blueprint', () => {
    const blueprint = normalizeQuickstartAgentBlueprint({
      description: 'Fallback mission',
      blueprint: {
        mission: '  Audit application code safely  ',
        responsibilities: ['Find vulnerabilities', '  Explain impact  ', 42],
        workflow: ['Inspect context', 'Validate evidence'],
        boundaries: ['Do not invent evidence'],
        capability_plan: {
          skills: [
            {
              name: 'Secure Code Review',
              purpose: 'Apply the approved review workflow',
              when_used: 'Before ranking findings',
              skill_id: 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
            },
          ],
          tools: [
            {
              name: 'Read',
              purpose: 'Inspect repository files',
              when_used: 'During evidence collection',
            },
          ],
          mcp_servers: [
            {
              name: 'GitHub',
              purpose: 'Read pull request context',
              when_used: 'When a pull request URL is supplied',
              server_url: 'https://api.github.com/mcp',
            },
          ],
        },
        tool_plan: ['Read repository files before making claims'],
        escalation_conditions: ['Authentication design is unclear'],
        output_contract: ['Severity', 'Evidence', 'Fix'],
        success_criteria: ['Every finding includes evidence'],
        acceptance_test: {
          message: 'Review the authentication module.',
          checks: ['Ranks findings by severity', 'Includes a concrete fix'],
        },
      },
    })

    expect(blueprint).toEqual({
      mission: 'Audit application code safely',
      responsibilities: ['Find vulnerabilities', 'Explain impact'],
      workflow: ['Inspect context', 'Validate evidence'],
      boundaries: ['Do not invent evidence'],
      capabilityPlan: {
        skills: [
          {
            name: 'Secure Code Review',
            purpose: 'Apply the approved review workflow',
            whenUsed: 'Before ranking findings',
            skillId: 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
            serverUrl: '',
          },
        ],
        tools: [
          {
            name: 'Read',
            purpose: 'Inspect repository files',
            whenUsed: 'During evidence collection',
            skillId: '',
            serverUrl: '',
          },
        ],
        mcpServers: [
          {
            name: 'GitHub',
            purpose: 'Read pull request context',
            whenUsed: 'When a pull request URL is supplied',
            skillId: '',
            serverUrl: 'https://api.github.com/mcp',
          },
        ],
      },
      toolPlan: ['Read repository files before making claims'],
      escalationConditions: ['Authentication design is unclear'],
      outputContract: ['Severity', 'Evidence', 'Fix'],
      successCriteria: ['Every finding includes evidence'],
      acceptanceTest: {
        message: 'Review the authentication module.',
        checks: ['Ranks findings by severity', 'Includes a concrete fix'],
      },
    })
  })

  it('uses agent description as a mission while partial output is streaming', () => {
    expect(
      normalizeQuickstartAgentBlueprint({
        description: 'Investigate production incidents',
        blueprint: { workflow: ['Assess impact'] },
      }),
    ).toMatchObject({
      mission: 'Investigate production incidents',
      workflow: ['Assess impact'],
      boundaries: [],
      capabilityPlan: { skills: [], tools: [], mcpServers: [] },
      acceptanceTest: { message: '', checks: [] },
    })
  })

  it('returns a safe empty blueprint for malformed model output', () => {
    expect(
      normalizeQuickstartAgentBlueprint({
        blueprint: 'not-an-object',
        description: { nested: true },
      }),
    ).toEqual({
      mission: '',
      responsibilities: [],
      workflow: [],
      boundaries: [],
      capabilityPlan: { skills: [], tools: [], mcpServers: [] },
      toolPlan: [],
      escalationConditions: [],
      outputContract: [],
      successCriteria: [],
      acceptanceTest: { message: '', checks: [] },
    })
  })
})

describe('quickstartBlueprintMetadata', () => {
  it('serializes the normalized blueprint into string metadata', () => {
    const metadata = quickstartBlueprintMetadata({
      description: 'Audit code',
      blueprint: {
        mission: 'Audit code',
        acceptance_test: {
          message: 'Review this diff.',
          checks: ['Includes evidence'],
        },
      },
    })

    expect(metadata.quickstart_blueprint_version).toBe('1')
    expect(metadata.quickstart_acceptance_message).toBe('Review this diff.')
    expect(JSON.parse(metadata.quickstart_blueprint)).toMatchObject({
      mission: 'Audit code',
      acceptanceTest: { checks: ['Includes evidence'] },
    })
  })
})
