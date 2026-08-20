export type QuickstartLaunchAssuranceState =
  | 'required'
  | 'ready'
  | 'enforced'
  | 'recommended'
  | 'not_authorized'
  | 'automatic'

export interface QuickstartLaunchAssurance {
  runtime: QuickstartLaunchAssuranceState
  modelConnection: QuickstartLaunchAssuranceState
  environment: QuickstartLaunchAssuranceState
  externalTools: QuickstartLaunchAssuranceState
  audit: QuickstartLaunchAssuranceState
  needsHardening: boolean
}

export function deriveQuickstartLaunchAssurance({
  hasRuntime,
  hasModelConnection,
  hasEnvironment,
  hasExternalToolAuthorization,
}: {
  hasRuntime: boolean
  hasModelConnection: boolean
  hasEnvironment: boolean
  hasExternalToolAuthorization: boolean
}): QuickstartLaunchAssurance {
  return {
    runtime: hasRuntime ? 'ready' : 'required',
    modelConnection: hasModelConnection ? 'ready' : 'required',
    environment: hasEnvironment ? 'enforced' : 'recommended',
    externalTools: hasExternalToolAuthorization ? 'ready' : 'not_authorized',
    audit: 'automatic',
    needsHardening: !hasEnvironment,
  }
}
