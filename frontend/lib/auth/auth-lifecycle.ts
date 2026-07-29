import type { QueryClient } from '@tanstack/react-query'

import { clearNonSessionQueryData } from '@/lib/query-client-lifecycle'
import { useProjectStore } from '@/stores/managed/project-store'

export function clearAuthenticatedClientState(queryClient: QueryClient): void {
  useProjectStore.getState().clearContext()
  clearNonSessionQueryData(queryClient, { refetchActive: false })
}
