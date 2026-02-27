'use client'

import { ExternalLink, Loader2, Monitor } from 'lucide-react'
import { useMemo, useState } from 'react'
import { env as runtimeEnv } from 'next-runtime-env'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function getApiBaseUrl(): string {
  const url = runtimeEnv('NEXT_PUBLIC_API_URL') || process.env.NEXT_PUBLIC_API_URL
  return url?.replace(/\/api\/?$/, '') || 'http://localhost:8000'
}

export function OpenClawWebUI() {
  const [loading, setLoading] = useState(true)

  const iframeSrc = useMemo(() => {
    return `${getApiBaseUrl()}/api/v1/openclaw/proxy/`
  }, [])

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between p-4 pb-2">
        <CardTitle className="text-sm font-medium">OpenClaw 原生界面</CardTitle>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => window.open(iframeSrc, '_blank')}
        >
          <ExternalLink className="mr-1 h-3.5 w-3.5" />
          新窗口打开
        </Button>
      </CardHeader>
      <CardContent className="relative flex-1 overflow-hidden p-0">
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
      </CardContent>
    </Card>
  )
}
