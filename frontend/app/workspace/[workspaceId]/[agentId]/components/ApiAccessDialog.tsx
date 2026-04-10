import { Key, Terminal, Copy, Check, Plus } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useToast } from '@/hooks/use-toast'
import { TokenList } from '@/components/tokens/TokenList'
import { TokenCreatedDialog } from '@/components/settings/token-created-dialog'
import {
  useCreateToken,
  usePlatformTokens,
  type PlatformTokenCreateResponse,
} from '@/hooks/queries/platformTokens'
import { useCopyToClipboard } from '@/app/chat/shared/hooks/useCopyToClipboard'
import { API_BASE } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'

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
  const { toast } = useToast()
  const { copied, handleCopy } = useCopyToClipboard()

  // Token creation state
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [tokenName, setTokenName] = useState('')
  const [tokenScope, setTokenScope] = useState('graphs:execute')
  const [createdToken, setCreatedToken] = useState<PlatformTokenCreateResponse | null>(null)

  const { data: tokens = [] } = usePlatformTokens({ resourceType: 'graph', resourceId: workspaceId })
  const createMutation = useCreateToken()

  const apiUrl = `${API_BASE}/openapi/graph/${agentId}`

  const curlExample = `curl -X POST "${apiUrl}/run" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {"your_input_key": "your_input_value"}}'`

  const handleCreateToken = async () => {
    if (!tokenName.trim()) return
    try {
      const result = await createMutation.mutateAsync({
        name: tokenName.trim(),
        scopes: [tokenScope],
        resource_type: 'graph',
        resource_id: workspaceId,
      })
      setCreatedToken(result)
      toast({ title: t('settings.tokens.createdSuccess') })
      setTokenName('')
      setShowCreateForm(false)
    } catch (error: unknown) {
      toast({ title: error instanceof Error ? error.message : String(error), variant: 'destructive' })
    }
  }

  const tokenHeader = (
    <div>
      <div className="mb-4">
        <h3 className="text-sm font-medium text-[var(--text-primary)]">
          {t('workspace.apiKeys')}
        </h3>
        <p className="mt-1 text-xs text-[var(--text-tertiary)]">
          {t('workspace.apiKeysDescription')}
        </p>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setShowCreateForm(!showCreateForm)}
        className="gap-2"
        disabled={tokens.length >= 50}
      >
        <Plus size={14} />
        {t('settings.tokens.create')}
      </Button>
      {tokens.length >= 50 && (
        <p className="mt-1 text-xs text-[var(--status-warning)]">{t('settings.tokens.limitReached')}</p>
      )}
      {showCreateForm && (
        <div className="mt-3 flex items-end gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-4">
          <div className="flex-1">
            <Label className="text-xs">{t('settings.tokens.name')}</Label>
            <Input
              value={tokenName}
              onChange={(e) => setTokenName(e.target.value)}
              placeholder={t('settings.tokens.namePlaceholder')}
              className="mt-1"
            />
          </div>
          <div className="w-32">
            <Label className="text-xs">{t('settings.tokens.type')}</Label>
            <Select value={tokenScope} onValueChange={setTokenScope}>
              <SelectTrigger className="mt-1 bg-[var(--surface-elevated)]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="graphs:execute">
                  {t('settings.tokens.scopeRead')}
                </SelectItem>
                <SelectItem value="graphs:read">
                  {t('settings.tokens.scopeRead')}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button size="sm" onClick={handleCreateToken} disabled={createMutation.isPending}>
            <Plus size={14} />
          </Button>
        </div>
      )}
    </div>
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-4xl flex-col overflow-hidden">
        <DialogHeader className="px-2 pt-2">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--brand-100)]">
              <Terminal className="h-4 w-4 text-[var(--brand-600)]" />
            </div>
            <div>
              <DialogTitle className="text-xl">
                {t('workspace.apiAccess')}
              </DialogTitle>
              <DialogDescription>
                {t('workspace.apiAccessDescription')}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="custom-scrollbar mt-4 flex-1 overflow-y-auto px-2">
          <Tabs defaultValue="integration" className="w-full">
            <TabsList className="mb-6 grid w-[400px] grid-cols-2">
              <TabsTrigger value="integration">
                <Terminal className="mr-2 h-4 w-4" />
                {t('workspace.integrationGuide')}
              </TabsTrigger>
              <TabsTrigger value="keys">
                <Key className="mr-2 h-4 w-4" />
                {t('workspace.apiTokens')}
              </TabsTrigger>
            </TabsList>

            <TabsContent value="integration" className="space-y-6">
              {/* Endpoint Information */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('workspace.baseUrl')}</h3>
                <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-2.5">
                  <div className="flex flex-col gap-1 overflow-hidden">
                    <span className="text-2xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
                      {t('workspace.endpoint')}
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
                          onClick={() => handleCopy(apiUrl)}
                        >
                          {copied ? (
                            <Check className="h-4 w-4 text-[var(--status-success)]" />
                          ) : (
                            <Copy className="h-4 w-4 text-[var(--text-tertiary)]" />
                          )}
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>
                        {t('workspace.copy')}
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

              {/* Authentication */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('workspace.authentication')}</h3>
                <p className="text-sm text-[var(--text-tertiary)]">
                  {t('workspace.authenticationDescription', { header: '' })}
                  <code className="rounded bg-[var(--surface-3)] px-1 py-0.5 text-[var(--text-primary)]">
                    Authorization
                  </code>
                </p>
                <div className="rounded-lg border border-[var(--brand-100)] bg-[var(--brand-50)] p-4">
                  <code className="font-mono text-sm font-semibold text-[var(--brand-600)]">
                    Authorization: Bearer YOUR_API_TOKEN
                  </code>
                </div>
              </div>

              {/* Example Request */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">{t('workspace.exampleRequest')}</h3>
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
                            onClick={() => handleCopy(curlExample)}
                          >
                            {copied ? (
                              <Check className="h-3 w-3 text-[var(--status-success)]" />
                            ) : (
                              <Copy className="h-3 w-3 text-[var(--text-tertiary)]" />
                            )}
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>
                          {t('workspace.copyCode')}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <pre className="overflow-x-auto bg-[var(--code-bg)] p-4 font-mono text-xs text-[var(--text-subtle)]">
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
                  className="inline-flex items-center text-sm font-medium text-[var(--brand-600)] hover:text-[var(--brand-600)] hover:underline"
                >
                  {t('workspace.viewFullApiDocs')}
                  <svg
                    className="ml-1 h-4 w-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                    />
                  </svg>
                </a>
              </div>
            </TabsContent>

            <TabsContent value="keys" className="space-y-4">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-elevated)] p-4 shadow-sm">
                <TokenList resourceType="graph" resourceId={workspaceId} header={tokenHeader} />
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </DialogContent>

      <TokenCreatedDialog
        open={!!createdToken}
        onOpenChange={(open) => !open && setCreatedToken(null)}
        tokenData={createdToken}
      />
    </Dialog>
  )
}
