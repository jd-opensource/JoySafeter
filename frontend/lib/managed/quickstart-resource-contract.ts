import {
  parseAgentId,
  parseCredentialGroupId,
  parseEnvironmentId,
  parseSessionId,
  type AgentId,
  type CredentialGroupId,
  type EnvironmentId,
  type SessionId,
} from '@/types/entity-id'

import {
  QUICKSTART_STEP,
  type QuickstartCreatedResourceStepId,
  type QuickstartResourceStepId,
} from './quickstart-flow'

const QUICKSTART_RESOURCE_DEFINITIONS = {
  [QUICKSTART_STEP.AGENT]: {
    apiPath: 'agents',
    parseId: parseAgentId,
  },
  [QUICKSTART_STEP.ENVIRONMENT]: {
    apiPath: 'environments',
    parseId: parseEnvironmentId,
  },
  [QUICKSTART_STEP.CREDENTIAL_GROUP]: {
    apiPath: 'credential-groups',
    parseId: parseCredentialGroupId,
  },
  [QUICKSTART_STEP.SESSION]: {
    apiPath: 'sessions',
    parseId: parseSessionId,
  },
} as const satisfies Record<
  QuickstartResourceStepId,
  { apiPath: string; parseId: (value: string) => string }
>

type QuickstartResourceIdByStep = {
  [QUICKSTART_STEP.AGENT]: AgentId
  [QUICKSTART_STEP.ENVIRONMENT]: EnvironmentId
  [QUICKSTART_STEP.CREDENTIAL_GROUP]: CredentialGroupId
  [QUICKSTART_STEP.SESSION]: SessionId
}

export function quickstartResourceApiPath(step: QuickstartResourceStepId): string {
  return QUICKSTART_RESOURCE_DEFINITIONS[step].apiPath
}

export function quickstartResourceEndpoint(step: QuickstartResourceStepId): string {
  return `/${quickstartResourceApiPath(step)}`
}

export function parseQuickstartResourceId<Step extends QuickstartResourceStepId>(
  step: Step,
  value: string,
): QuickstartResourceIdByStep[Step] {
  return QUICKSTART_RESOURCE_DEFINITIONS[step].parseId(value) as QuickstartResourceIdByStep[Step]
}

export function isQuickstartCreatedResourceStep(
  step: QuickstartResourceStepId,
): step is QuickstartCreatedResourceStepId {
  return step !== QUICKSTART_STEP.SESSION
}
