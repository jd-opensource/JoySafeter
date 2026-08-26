import { describe, expect, it } from 'vitest'

import {
  parseSkillAuthoringSaveResponse,
  parseSkillFileResponse,
  parseSkillLifecycleTransitionResponse,
  parseSkillResponse,
  parseSkillSecurityScanResponse,
  parseSkillUsageResponse,
  parseSkillVersionFileResponse,
  parseSkillVersionResponse,
} from './skill-response-parsers'

const SKILL_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f050'
const FILE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f051'
const VERSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f052'
const VERSION_FILE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f053'
const SCAN_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f054'
const USAGE_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f055'
const SESSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f056'
const AGENT_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f057'
const USER_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f058'
const AGENT_VERSION_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f059'
const AGENT_VERSION_REFERENCE_TYPE = ['agent', 'version'].join('_')
const TRIGGER_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f05a'
const TASK_UUID = '018f6f42-0a51-7cc4-98c8-4f6f0ca5f05b'

describe('skill response parsers', () => {
  it('brands the complete Skill identity chain', () => {
    expect(
      parseSkillResponse({
        id: `skill_${SKILL_UUID}`,
        org_version_id: `sklver_${VERSION_UUID}`,
        public_version_id: null,
        security_scan: { scan_id: `sklscan_${SCAN_UUID}` },
      }).security_scan?.scan_id,
    ).toBe(`sklscan_${SCAN_UUID}`)
    expect(
      parseSkillFileResponse({ id: `sklfile_${FILE_UUID}`, skill_id: `skill_${SKILL_UUID}` }).id,
    ).toBe(`sklfile_${FILE_UUID}`)
    expect(
      parseSkillVersionResponse({ id: `sklver_${VERSION_UUID}`, skill_id: `skill_${SKILL_UUID}` })
        .skill_id,
    ).toBe(`skill_${SKILL_UUID}`)
    expect(
      parseSkillVersionFileResponse({
        id: `sklvfile_${VERSION_FILE_UUID}`,
        version_id: `sklver_${VERSION_UUID}`,
      }).version_id,
    ).toBe(`sklver_${VERSION_UUID}`)
    expect(
      parseSkillSecurityScanResponse({
        id: `sklscan_${SCAN_UUID}`,
        skill_id: `skill_${SKILL_UUID}`,
        owner_id: `user_${USER_UUID}`,
      }).owner_id,
    ).toBe(`user_${USER_UUID}`)
    expect(
      parseSkillUsageResponse({
        id: `skluse_${USAGE_UUID}`,
        skill_id: `skill_${SKILL_UUID}`,
        skill_version_id: `sklver_${VERSION_UUID}`,
        security_scan_id: `sklscan_${SCAN_UUID}`,
        session_id: `sess_${SESSION_UUID}`,
        agent_id: `agent_${AGENT_UUID}`,
      }).id,
    ).toBe(`skluse_${USAGE_UUID}`)
    expect(
      parseSkillLifecycleTransitionResponse({
        skill_id: `skill_${SKILL_UUID}`,
        from_status: 'draft',
        to_status: 'pending_review',
      }).skill_id,
    ).toBe(`skill_${SKILL_UUID}`)
  })

  it('brands authoring save IDs and rejects invalid IDs', () => {
    expect(parseSkillAuthoringSaveResponse({ skill_id: `skill_${SKILL_UUID}` }).skill_id).toBe(
      `skill_${SKILL_UUID}`,
    )
    expect(() => parseSkillAuthoringSaveResponse({ skill_id: SKILL_UUID })).toThrow()
    expect(() =>
      parseSkillFileResponse({ id: `sklvfile_${FILE_UUID}`, skill_id: `skill_${SKILL_UUID}` }),
    ).toThrow()
  })

  it('parses every polymorphic Skill impact reference by its declared type', () => {
    const skill = parseSkillResponse({
      id: `skill_${SKILL_UUID}`,
      impact: {
        counts: { agents: 1, agent_versions: 1, triggers: 1, active_tasks: 1, total: 4 },
        references: [
          { type: 'agent', id: `agent_${AGENT_UUID}`, name: 'agent' },
          {
            type: AGENT_VERSION_REFERENCE_TYPE,
            id: `agentver_${AGENT_VERSION_UUID}`,
            name: 'version',
          },
          { type: 'trigger', id: `trig_${TRIGGER_UUID}`, name: 'trigger' },
          { type: 'active_task', id: `task_${TASK_UUID}`, name: 'task' },
        ],
      },
    })

    expect(skill.impact?.references.map((reference) => reference.id)).toEqual([
      `agent_${AGENT_UUID}`,
      `agentver_${AGENT_VERSION_UUID}`,
      `trig_${TRIGGER_UUID}`,
      `task_${TASK_UUID}`,
    ])
    expect(() =>
      parseSkillResponse({
        id: `skill_${SKILL_UUID}`,
        impact: {
          counts: { agents: 1, agent_versions: 0, triggers: 0, active_tasks: 0, total: 1 },
          references: [{ type: 'agent', id: `task_${TASK_UUID}`, name: 'wrong' }],
        },
      }),
    ).toThrow()
  })

  it('rejects a cross-entity Skill scan owner ID', () => {
    expect(() =>
      parseSkillSecurityScanResponse({
        id: `sklscan_${SCAN_UUID}`,
        skill_id: `skill_${SKILL_UUID}`,
        owner_id: `agent_${AGENT_UUID}`,
      }),
    ).toThrow()
  })
})
