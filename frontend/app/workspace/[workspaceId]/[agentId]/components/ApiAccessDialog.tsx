import { Key, Terminal, Copy, Check } from 'lucide-react'
import { useState } from 'react'

import { ApiKeysTable } from '@/components/api-keys/ApiKeysTable'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useTranslation } from '@/lib/i18n'
import { toastSuccess, toastError } from '@/lib/utils/toast'

interface ApiAccessDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string
  workspaceId: string
}

export function ApiAccessDialog({
  open,
  onOpenChange,
  agentId,
  workspaceId,
}: ApiAccessDialogProps) {
  const { t } = useTranslation()
  const [copiedUrl, setCopiedUrl] = useState(false)
  const [copiedCode, setCopiedCode] = useState(false)

  // Determine the base URL dynamically based on current origin
  const baseUrl = typeof window !== 'undefined' ? window.location.origin : ''
  const apiUrl = `${baseUrl}/api/v1/openapi/graph/${agentId}`

  const curlExample = `curl -X POST "${apiUrl}/run" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {"your_input_key": "your_input_value"}}'`

  const handleCopyUrl = async () => {
    try {
      await navigator.clipboard.writeText(apiUrl)
      setCopiedUrl(true)
      toastSuccess(t('workspace.copiedToClipboard', { defaultValue: '已复制' }))
      setTimeout(() => setCopiedUrl(false), 2000)
    } catch {
      toastError(t('workspace.copyFailed', { defaultValue: '复制失败' }))
    }
  }

  const handleCopyCode = async () => {
    try {
      await navigator.clipboard.writeText(curlExample)
      setCopiedCode(true)
      toastSuccess(t('workspace.copiedToClipboard', { defaultValue: '已复制' }))
      setTimeout(() => setCopiedCode(false), 2000)
    } catch {
      toastError(t('workspace.copyFailed', { defaultValue: '复制失败' }))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <DialogHeader className="px-2 pt-2">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100">
              <Terminal className="h-4 w-4 text-blue-600" />
            </div>
            <div>
              <DialogTitle className="text-xl">{t('workspace.apiAccess', { defaultValue: 'API Access' })}</DialogTitle>
              <DialogDescription>
                {t('workspace.apiAccessDescription', { defaultValue: 'Access and execute this graph remotely via REST API.' })}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto mt-4 px-2 custom-scrollbar">
          <Tabs defaultValue="integration" className="w-full">
            <TabsList className="grid w-[400px] grid-cols-2 mb-6">
              <TabsTrigger value="integration">
                <Terminal className="h-4 w-4 mr-2" />
                Integration Guide
              </TabsTrigger>
              <TabsTrigger value="keys">
                <Key className="h-4 w-4 mr-2" />
                API Keys
              </TabsTrigger>
            </TabsList>

            <TabsContent value="integration" className="space-y-6">
              {/* Endpoint Information */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Base URL</h3>
                <div className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 p-2.5">
                  <div className="flex flex-col gap-1 overflow-hidden">
                    <span className="text-[10px] font-semibold text-gray-500 uppercase tracking-wider">ENDPOINT</span>
                    <code className="text-sm font-mono text-gray-800 break-all truncate" title={apiUrl}>
                      {apiUrl}
                    </code>
                  </div>
                  <TooltipProvider delayDuration={300}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 flex-shrink-0"
                          onClick={handleCopyUrl}
                        >
                          {copiedUrl ? <Check className="h-4 w-4 text-green-600" /> : <Copy className="h-4 w-4 text-gray-500" />}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>{t('workspace.copy', { defaultValue: 'Copy' })}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

              {/* Authentication */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Authentication</h3>
                <p className="text-sm text-gray-500">
                  Authenticate your API requests by including your API Key in the <code className="bg-gray-100 px-1 py-0.5 rounded text-gray-800">Authorization</code> HTTP header as a Bearer token.
                </p>
                <div className="rounded-lg border border-blue-200 bg-blue-50/50 p-4">
                  <code className="text-sm font-mono text-blue-800 font-semibold">
                    Authorization: Bearer YOUR_API_KEY
                  </code>
                </div>
              </div>

              {/* Example Request */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-900">Example Request</h3>
                <div className="relative rounded-lg overflow-hidden border border-gray-200">
                  <div className="flex items-center justify-between bg-gray-100 px-4 py-2 border-b border-gray-200">
                    <span className="text-xs font-semibold text-gray-600 text-mono">cURL</span>
                    <TooltipProvider delayDuration={300}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            onClick={handleCopyCode}
                          >
                            {copiedCode ? <Check className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3 text-gray-500" />}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>{t('workspace.copyCode', { defaultValue: 'Copy Code' })}</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <pre className="p-4 bg-[#0d1117] text-gray-300 text-xs font-mono overflow-x-auto">
                    <code>{curlExample}</code>
                  </pre>
                </div>
              </div>

              {/* Documentation Link */}
              <div className="pt-2">
                <a
                  href="https://github.com/jd-opensource/JoySafeter/blob/main/docs/api/openapi.md"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-700 hover:underline font-medium inline-flex items-center"
                >
                  {t('workspace.viewFullApiDocs', { defaultValue: 'View Full API Documentation' })}
                  <svg className="ml-1 w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                  </svg>
                </a>
              </div>
            </TabsContent>

            <TabsContent value="keys" className="space-y-4">
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm p-4">
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-900">Workspace API Keys</h3>
                  <p className="text-xs text-gray-500 mt-1">Manage API keys that have access to this workspace's resources.</p>
                </div>
                <ApiKeysTable workspaceId={workspaceId} />
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  )
}
