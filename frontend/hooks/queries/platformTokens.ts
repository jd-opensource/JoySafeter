import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { platformTokenService } from '@/services/platformTokenService'
import type { PlatformToken, PlatformTokenCreateResponse, TokenCreateRequest } from '@/services/platformTokenService'

export { type PlatformToken, type PlatformTokenCreateResponse, type TokenCreateRequest } from '@/services/platformTokenService'

export const platformTokenKeys = {
  all: ['platform-tokens'] as const,
  list: () => [...platformTokenKeys.all, 'list'] as const,
}

export function usePlatformTokens() {
  return useQuery({
    queryKey: platformTokenKeys.list(),
    queryFn: () => platformTokenService.listTokens(),
    retry: false,
    staleTime: STALE_TIME.LONG,
  })
}

export function useCreateToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: TokenCreateRequest) =>
      platformTokenService.createToken(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformTokenKeys.all })
    },
  })
}

export function useRevokeToken() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (tokenId: string) => platformTokenService.revokeToken(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: platformTokenKeys.all })
    },
  })
}
