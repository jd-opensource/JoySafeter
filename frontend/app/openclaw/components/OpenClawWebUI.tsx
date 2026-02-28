'use client'

import { Loader2, Play, Server } from 'lucide-react'
import { useMemo, useState } from 'react'
import { env as runtimeEnv } from 'next-runtime-env'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { apiGet, apiPost } from '@/lib/api-client'

interface InstanceStatus {
  exists: boolean
  id?: string
  status?: string
}

function getApiBaseUrl(): string {
  const url = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  return url?.replace(/\/api\/?$/, '') || 'http://localhost:8000'
}

export function OpenClawWebUI() {
  const [iframeLoading, setIframeLoading] = useState(true)
  const queryClient = useQueryClient()

  const { data: instance, isLoading: instanceLoading } = useQuery<InstanceStatus>({
    queryKey: ['openclaw-instance'],
    queryFn: () => apiGet<InstanceStatus>('openclaw/instances'),
    refetchInterval: 8_000,
  })

  const startMutation = useMutation({
    mutationFn: () => apiPost('openclaw/instances'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['openclaw-instance'] }),
  })

  const iframeSrc = useMemo(() => {
    return `${getApiBaseUrl()}/api/v1/openclaw/proxy/overview`
  }, [])

  if (instanceLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--bg)]">
        <Loader2 className="mb-4 h-8 w-8 animate-spin text-[var(--text-secondary)]" />
        <span className="text-sm text-[var(--text-secondary)]">检查实例状态...</span>
      </div>
    )
  }

  if (!instance?.exists || instance.status !== 'running') {
    return (
      <div className="flex h-full flex-col items-center justify-center rounded-lg border border-[var(--border)] bg-[var(--bg)] py-12 px-4 shadow-sm">
        <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[var(--muted)] mb-6">
          <Server className="h-8 w-8 text-[var(--text-tertiary)]" />
        </div>
        <h3 className="mb-2 text-xl font-semibold tracking-tight text-[var(--text-primary)]">
          {instance?.exists ? 'OpenClaw 实例未运行' : '未创建 OpenClaw 实例'}
        </h3>
        <p className="mb-8 max-w-md text-center text-[var(--text-secondary)] leading-relaxed">
          你需要先启动 OpenClaw 实例，才能使用原生 Web 界面与 Agent 进行交互以及管理设备。
          <br />
          <span className="text-amber-500/90 text-sm mt-2 block">
            提示：实例启动环境准备过程较长，大约需要 4 分钟，请耐心等待。
          </span>
        </p>
        <Button
          size="lg"
          onClick={() => startMutation.mutate()}
          disabled={startMutation.isPending || instance?.status === 'starting'}
          className="h-11 px-8"
        >
          {startMutation.isPending || instance?.status === 'starting' ? (
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          ) : (
            <Play className="mr-2 h-5 w-5" />
          )}
          {instance?.status === 'starting' ? '正在启动...' : '启动实例'}
        </Button>
      </div>
    )
  }

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] shadow-sm">
      <div className="relative min-h-0 flex-1">
        {iframeLoading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[var(--bg)]">
            <div className="flex flex-col items-center gap-2">
              <Loader2 className="h-6 w-6 animate-spin text-[var(--text-secondary)]" />
              <span className="text-sm text-[var(--text-secondary)]">加载 OpenClaw 界面...</span>
            </div>
          </div>
        )}
        <iframe
          src={iframeSrc}
          className="h-full w-full border-0"
          onLoad={() => setIframeLoading(false)}
          onError={() => setIframeLoading(false)}
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
          title="OpenClaw WebUI"
        />
      </div>
    </div>
  )
}
