'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CheckCheck, Loader2, Smartphone } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { apiGet, apiPost } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'

interface Device {
  id: string
  name?: string
  type?: string
  status?: string
  lastSeen?: string
}

interface DeviceInfo {
  deviceId: string
  platform?: string
  clientId?: string
  clientMode?: string
  role?: string
  createdAtMs?: number
  approvedAtMs?: number
}

interface DeviceResponse {
  pending: DeviceInfo[]
  paired: DeviceInfo[]
}

export function DeviceManager() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<DeviceResponse>({
    queryKey: ['openclaw-devices'],
    queryFn: () => apiGet<DeviceResponse>('openclaw/devices'),
    refetchInterval: 10_000,
  })

  const devices: Device[] = [
    ...(data?.pending || []).map((d) => ({
      id: d.deviceId,
      name: d.clientId,
      type: d.platform,
      status: 'pending',
      lastSeen: d.createdAtMs ? new Date(d.createdAtMs).toLocaleString() : undefined,
    })),
    ...(data?.paired || []).map((d) => ({
      id: d.deviceId,
      name: d.clientId,
      type: d.platform,
      status: 'paired',
      lastSeen: d.approvedAtMs ? new Date(d.approvedAtMs).toLocaleString() : undefined,
    })),
  ]

  const approveMutation = useMutation({
    mutationFn: (id: string) => apiPost(`openclaw/devices/${id}/approve`),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
  })

  const approveAllMutation = useMutation({
    mutationFn: () => apiPost('openclaw/devices/approve-all'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-devices'] }),
  })

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2">
        <CardTitle className="text-sm font-medium">{t('openclaw.devicePairing')}</CardTitle>
        {devices.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => approveAllMutation.mutate()}
            disabled={approveAllMutation.isPending}
          >
            {approveAllMutation.isPending ? (
              <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
            ) : (
              <CheckCheck className="mr-1 h-3.5 w-3.5" />
            )}
            {t('openclaw.approveAll')}
          </Button>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-sm text-[var(--text-secondary)]">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            {t('openclaw.loadingDevices')}
          </div>
        ) : devices.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8">
            <Smartphone className="mb-2 h-6 w-6 text-[var(--text-tertiary)]" />
            <p className="text-xs text-[var(--text-tertiary)]">{t('openclaw.noPairedDevices')}</p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {devices.map((d) => (
              <li key={d.id} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2">
                  <Smartphone className="h-4 w-4 text-[var(--text-secondary)]" />
                  <div>
                    <p className="text-sm font-medium text-[var(--text-primary)]">
                      {d.name || d.id}
                    </p>
                    {d.type && <p className="text-xs text-[var(--text-tertiary)]">{d.type}</p>}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {d.status && (
                    <Badge variant="outline" className="text-xs">
                      {d.status}
                    </Badge>
                  )}
                  {d.status === 'pending' && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-xs"
                      onClick={() => approveMutation.mutate(d.id)}
                      disabled={approveMutation.isPending}
                    >
                      <Check className="mr-0.5 h-3 w-3" />
                      {t('openclaw.approveAccess')}
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
