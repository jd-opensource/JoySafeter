import { Terminal, Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import { API_BASE } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'

interface AgentApiAccessDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string
  projectId: string
  endpointKind?: 'graph'
}

export function AgentApiAccessDialog({
  open,
  onOpenChange,
  agentId,
  projectId,
  endpointKind = 'graph',
}: AgentApiAccessDialogProps) {
  const { t } = useTranslation()
  const { copied, handleCopy } = useCopyToClipboard()

  const apiUrl = `${API_BASE}/openapi/${endpointKind}/${agentId}`

  const curlExample = `curl -X POST "${apiUrl}/run" \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"inputs": {"your_input_key": "your_input_value"}}'`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] max-w-4xl flex-col overflow-hidden">
        <DialogHeader className="px-2 pt-2">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--brand-100)]">
              <Terminal className="h-4 w-4 text-[var(--brand-600)]" />
            </div>
            <div>
              <DialogTitle className="text-xl">{t('workspace.apiAccess')}</DialogTitle>
              <DialogDescription>{t('workspace.apiAccessDescription')}</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="custom-scrollbar mt-4 flex-1 overflow-y-auto px-2">
          <div className="space-y-6">
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {t('workspace.baseUrl')}
                </h3>
                <div className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-2.5">
                  <div className="flex flex-col gap-1 overflow-hidden">
                    <span className="text-xs font-semibold uppercase tracking-wider text-[var(--text-tertiary)]">
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
                      <TooltipContent>{t('workspace.copy')}</TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {t('workspace.authentication')}
                </h3>
                <p className="text-sm text-[var(--text-tertiary)]">
                  {t('workspace.authenticationDescription', { header: '' })}
                  <code className="rounded bg-[var(--surface-3)] px-1 py-0.5 text-[var(--text-primary)]">
                    Authorization
                  </code>
                </p>
                <div className="rounded-lg border border-[var(--brand-100)] bg-[var(--brand-50)] p-4">
                  <code className="font-mono text-sm font-semibold text-[var(--brand-600)]">
                    Authorization: Bearer YOUR_API_KEY
                  </code>
                </div>
              </div>

              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {t('workspace.exampleRequest')}
                </h3>
                <div className="relative overflow-hidden rounded-lg border border-[var(--border)]">
                  <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--surface-3)] px-4 py-2">
                    <span className="text-mono text-xs font-semibold text-[var(--text-secondary)]">
                      cURL
                    </span>
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
                        <TooltipContent>{t('workspace.copyCode')}</TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                  <pre className="overflow-x-auto bg-[var(--code-bg)] p-4 font-mono text-xs text-[var(--text-subtle)]">
                    <code>{curlExample}</code>
                  </pre>
                </div>
              </div>

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
          </div>

        </div>
      </DialogContent>
    </Dialog>
  )
}
