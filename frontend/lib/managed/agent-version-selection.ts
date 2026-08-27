export interface AgentVersionSelection {
  selectedVersion: string
  baseVersion: string
  targetVersion: string
}

export function advanceAgentVersionSelection({
  previousLatest,
  currentLatest,
  selectedVersion,
  baseVersion,
  targetVersion,
}: AgentVersionSelection & {
  previousLatest: number
  currentLatest: number
}): AgentVersionSelection {
  if (previousLatest === currentLatest) return { selectedVersion, baseVersion, targetVersion }
  const previousLatestValue = String(previousLatest)
  const currentLatestValue = String(currentLatest)
  const previousDefaultBase = String(Math.max(1, previousLatest - 1))
  const currentDefaultBase = String(Math.max(1, currentLatest - 1))
  return {
    selectedVersion: selectedVersion === previousLatestValue ? currentLatestValue : selectedVersion,
    baseVersion: baseVersion === previousDefaultBase ? currentDefaultBase : baseVersion,
    targetVersion: targetVersion === previousLatestValue ? currentLatestValue : targetVersion,
  }
}
