import {
  parseAgentId,
  parseCredentialGroupId,
  parseEnvironmentId,
  parseEventId,
  parseFileId,
  parseOrganizationId,
  parseOrganizationMemberId,
  parseProjectId,
  parseSessionId,
  parseSessionResourceId,
  parseTaskId,
  parseTriggerId,
  parseUserId,
} from '@/types/entity-id'

export const AGENT_ID = parseAgentId('agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001')
export const OTHER_AGENT_ID = parseAgentId('agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f002')
export const CREATED_AGENT_ID = parseAgentId('agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f003')
export const SESSION_ID = parseSessionId('sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f004')
export const OTHER_SESSION_ID = parseSessionId('sess_018f6f42-0a51-7cc4-98c8-4f6f0ca5f006')
export const TASK_ID = parseTaskId('task_018f6f42-0a51-7cc4-98c8-4f6f0ca5f005')
export const TRIGGER_ID = parseTriggerId('trig_018f6f42-0a51-7cc4-98c8-4f6f0ca5f007')
export const OTHER_TRIGGER_ID = parseTriggerId('trig_018f6f42-0a51-7cc4-98c8-4f6f0ca5f008')
export const MANUAL_TRIGGER_ID = parseTriggerId('trig_018f6f42-0a51-7cc4-98c8-4f6f0ca5f009')
export const ENVIRONMENT_ID = parseEnvironmentId('env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010')
export const OTHER_ENVIRONMENT_ID = parseEnvironmentId('env_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011')
export const VAULT_ID = parseCredentialGroupId('credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f012')
export const OTHER_VAULT_ID = parseCredentialGroupId('credgrp_018f6f42-0a51-7cc4-98c8-4f6f0ca5f013')
export const FILE_ID = parseFileId('file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f014')
export const OTHER_FILE_ID = parseFileId('file_018f6f42-0a51-7cc4-98c8-4f6f0ca5f015')
export const SESSION_RESOURCE_ID = parseSessionResourceId(
  'sesrsc_018f6f42-0a51-7cc4-98c8-4f6f0ca5f016',
)
export const EVENT_ID = parseEventId('evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f017')
export const OTHER_EVENT_ID = parseEventId('evt_018f6f42-0a51-7cc4-98c8-4f6f0ca5f018')
export const USER_ID = parseUserId('user_018f6f42-0a51-7cc4-98c8-4f6f0ca5f019')
export const ORGANIZATION_ID = parseOrganizationId('org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f020')
export const PROJECT_ID = parseProjectId('proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f021')
export const OTHER_ORGANIZATION_ID = parseOrganizationId('org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f022')
export const THIRD_ORGANIZATION_ID = parseOrganizationId('org_018f6f42-0a51-7cc4-98c8-4f6f0ca5f023')
export const OTHER_PROJECT_ID = parseProjectId('proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f024')
export const THIRD_PROJECT_ID = parseProjectId('proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f025')
export const FOURTH_PROJECT_ID = parseProjectId('proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f026')
export const FIFTH_PROJECT_ID = parseProjectId('proj_018f6f42-0a51-7cc4-98c8-4f6f0ca5f027')
export const ORGANIZATION_MEMBER_ID = parseOrganizationMemberId(
  'orgmem_018f6f42-0a51-7cc4-98c8-4f6f0ca5f028',
)
