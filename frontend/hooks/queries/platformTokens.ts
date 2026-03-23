import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { STALE_TIME } from './constants'
import { platformTokenService } from '@/services/platformTokenService'
import type { PlatformToken, PlatformTokenCreateResponse, TokenCreateRequest, TokenListParams } from '@/services/platformTokenService'

export { type PlatformToken, type PlatformTokenCreateResponse, type TokenCreateRequest, type TokenListParams } from '@/services/platformTokenService'

export const platformTokenKeys = {
  all: ['platform-tokens'] as const,
  list: (params?: TokenListParams) => [...platformTokenKeys.all, 'list', params] as const,
}

export function usePlatformTokens(params?: TokenListParams) {
  return useQuery({
    queryKey: platformTokenKeys.list(params),
    queryFn: () => platformTokenService.listTokens(params),
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
