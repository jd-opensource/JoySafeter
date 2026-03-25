'use client'

import { Key, Terminal, Copy, Check } from 'lucide-react'

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
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import { API_BASE } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'

import { ApiTokensTab } from './ApiTokensTab'

interface SkillApiAccessDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  skillId: string
}

export function SkillApiAccessDialog({
  open,
  onOpenChange,
  skillId,
}: SkillApiAccessDialogProps) {
  const { t } = useTranslation()
  const { copied: copiedUrl, handleCopy: copyUrl } = useCopyToClipboard()
  const { copied: copiedCode, handleCopy: copyCode } = useCopyToClipboard()

  const apiUrl = `${API_BASE}/skills/${skillId}`

  const curlExample = `curl -X POST "${apiUrl}/execute" \\
  -H "Authorization: Bearer YOUR_API_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {"your_input_key": "your_input_value"}}'`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-4xl flex-col overflow-hidden">
        <DialogHeader className="px-2 pt-2">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--skill-brand-100)]">
              <Terminal className="h-4 w-4 text-[var(--skill-brand-600)]" />
            </div>
            <div>
              <DialogTitle className="text-xl">
                {t('skills.apiAccess', { defaultValue: 'API Access' })}
              </DialogTitle>
              <DialogDescription>
                {t('skills.apiAccessDescription', {
                  defaultValue: 'Access and execute this skill remotely via REST API.',
                })}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="custom-scrollbar mt-1 flex-1 overflow-y-auto px-2">
          <Tabs defaultValue="integration" className="w-full">
            <TabsList className="mb-3 grid w-[400px] grid-cols-2">
              <TabsTrigger value="integration">
                <Terminal className="mr-2 h-4 w-4" />
                {t('skills.integrationGuide', { defaultValue: 'Integration Guide' })}
              </TabsTrigger>
              <TabsTrigger value="tokens">
                <Key className="mr-2 h-4 w-4" />
                {t('skills.apiTokens', { defaultValue: 'API Tokens' })}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="integration" className="space-y-6">
              {/* Endpoint Information */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Base URL</h3>
                <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-2.5">
                  <div className="flex flex-col gap-1 overflow-hidden">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                      ENDPOINT
                    </span>
                    <code
                      className="truncate break-all font-mono text-sm text-[var(--text-primary)]"
                      title={apiUrl}
                    >
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
                          onClick={() => copyUrl(apiUrl)}
                        >
                          {copiedUrl ? (
                            <Check className="h-4 w-4 text-green-600" />
                          ) : (
                            <Copy className="h-4 w-4 text-[var(--text-tertiary)]" />
                          )}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        {t('common.copy', { defaultValue: 'Copy' })}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

              {/* Authentication */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Authentication</h3>
                <p className="text-sm text-[var(--text-tertiary)]">
                  {t('skills.authDescription', {
                    defaultValue:
                      'Authenticate your API requests by including your API Token in the Authorization HTTP header as a Bearer token.',
                  })}
                </p>
                <div className="rounded-lg border border-[var(--skill-brand-200)] bg-[var(--skill-brand-50)] p-4">
                  <code className="font-mono text-sm font-semibold text-[var(--skill-brand-700)]">
                    Authorization: Bearer YOUR_API_TOKEN
                  </code>
                </div>
              </div>

              {/* Example Request */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">Example Request</h3>
                <div className="relative overflow-hidden rounded-lg border border-[var(--border)]">
                  <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-3)] px-4 py-2">
                    <span className="text-mono text-xs font-semibold text-[var(--text-secondary)]">cURL</span>
                    <TooltipProvider delayDuration={300}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            onClick={() => copyCode(curlExample)}
                          >
                            {copiedCode ? (
                              <Check className="h-3 w-3 text-green-600" />
                            ) : (
                              <Copy className="h-3 w-3 text-[var(--text-tertiary)]" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('common.copyCode', { defaultValue: 'Copy Code' })}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <pre className="overflow-x-auto bg-[#0d1117] p-4 font-mono text-xs text-gray-300">
                    <code>{curlExample}</code>
                  </pre>
                </div>
              </div>
            </TabsContent>

            <TabsContent value="tokens" className="space-y-4">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-4 shadow-sm">
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-[var(--text-primary)]">
                    {t('skills.skillApiTokens', { defaultValue: 'Skill API Tokens' })}
                  </h3>
                  <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                    {t('skills.skillApiTokensDescription', {
                      defaultValue:
                        'Manage tokens scoped to this skill for programmatic execution.',
                    })}
                  </p>
                </div>
                <ApiTokensTab skillId={skillId} />
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>
    </Dialog>
  )
}
