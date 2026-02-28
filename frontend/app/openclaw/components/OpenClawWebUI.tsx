'use client'

import { ExternalLink, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { env as runtimeEnv } from 'next-runtime-env'

import { Button } from '@/components/ui/button'

function getApiBaseUrl(): string {
  const url = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  return url?.replace(/\/api\/?$/, '') || 'http://localhost:8000'
}

export function OpenClawWebUI() {
  const [loading, setLoading] = useState(true)

  const iframeSrc = useMemo(() => {
    return `${getApiBaseUrl()}/api/v1/openclaw/proxy/overview`
  }, [])

  return (
    <div className="relative flex h-full flex-col overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)]">
      <div className="flex shrink-0 items-center justify-end gap-2 border-b border-[var(--border)] px-3 py-2">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => window.open(iframeSrc, '_blank')}
        >
          <ExternalLink className="mr-1 h-3.5 w-3.5" />
          新窗口打开
        </Button>
      </div>
      <div className="relative min-h-0 flex-1">
        {loading && (
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
          onLoad={() => setLoading(false)}
          onError={() => setLoading(false)}
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-modals"
          title="OpenClaw WebUI"
        />
      </div>
    </div>
  )
}
