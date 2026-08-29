type NetworkPolicyRefreshInput = {
  sessionActive: boolean
  streamForced: boolean
  networkingStatus: string | null | undefined
}

const DEGRADED_NETWORKING_STATUSES = new Set(['pending', 'nacked', 'failed'])

export function networkPolicyRefetchInterval({
  sessionActive,
  streamForced,
  networkingStatus,
}: NetworkPolicyRefreshInput): 2000 | 5000 | false {
  if (sessionActive || streamForced) return 2000
  if (networkingStatus && DEGRADED_NETWORKING_STATUSES.has(networkingStatus)) return 5000
  return false
}
