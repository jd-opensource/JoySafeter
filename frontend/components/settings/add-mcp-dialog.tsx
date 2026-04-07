'use client'

import { X, Info, Plus, FileJson, SquarePen, Trash2, Save, Loader2 } from 'lucide-react'
import { useState, useEffect } from 'react'


import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DialogDescription,
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
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useToast } from '@/hooks/use-toast'
import { useCreateMcpServer, useUpdateMcpServer, useTestMcpServer } from '@/hooks/queries/mcp'
import type { McpServer } from '@/hooks/queries/mcp'
import { useTranslation } from '@/lib/i18n'
import { cn } from '@/lib/utils'

import {
  serverToEditData,
  DEFAULT_MCP_FORM_CONFIG,
} from './mcp-dialog-utils'

interface AddMcpDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  editingServer?: McpServer | null
}

interface HeaderItem {
  key: string
  value: string
}

export function AddMcpDialog({ open, onOpenChange, editingServer }: AddMcpDialogProps) {
  const { t } = useTranslation()
  const isEditMode = !!editingServer
  const [mode, setMode] = useState<'form' | 'json'>('form')
  const [name, setName] = useState('')
  const [transport, setTransport] = useState<'streamable-http' | 'sse' | 'stdio'>(
    DEFAULT_MCP_FORM_CONFIG.transport,
  )
  const [address, setAddress] = useState('')
  const [headers, setHeaders] = useState<HeaderItem[]>([])

  // Settings
  const [retryEnabled, setRetryEnabled] = useState(false)
  const [maxRetries, setMaxRetries] = useState(String(DEFAULT_MCP_FORM_CONFIG.retries))
  const [retryDelay, setRetryDelay] = useState('1000')
  const [statusEnabled, setStatusEnabled] = useState<boolean>(DEFAULT_MCP_FORM_CONFIG.enabled)

  const [jsonContent, setJsonContent] = useState('')
  const { toast } = useToast()
  const createMcpServer = useCreateMcpServer()
  const updateMcpServer = useUpdateMcpServer()
  const testMcpServer = useTestMcpServer()

  // Sync Form -> JSON when switching tabs
  useEffect(() => {
    if (mode === 'json') {
      const config = {
        name,
        transport,
        address,
        headers: headers.reduce((acc, h) => ({ ...acc, [h.key]: h.value }), {}),
        retry: retryEnabled
          ? { maxRetries: Number(maxRetries), delay: Number(retryDelay) }
          : undefined,
        enabled: statusEnabled,
      }
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setJsonContent(JSON.stringify(config, null, 2))
    }
  }, [mode, name, transport, address, headers, retryEnabled, maxRetries, retryDelay, statusEnabled])

  // Load editing server data or reset form
  useEffect(() => {
    if (open && editingServer) {
      const editData = serverToEditData(editingServer)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setName(editData.name)
      setTransport(editData.transport as 'streamable-http' | 'sse' | 'stdio')
      setAddress(editData.url || '')
      setHeaders(
        Object.entries(editData.headers || {}).map(([key, value]) => ({
          key,
          value: String(value),
        })),
      )
      setStatusEnabled(editData.enabled ?? DEFAULT_MCP_FORM_CONFIG.enabled)
      if (editData.timeout) {
        setRetryEnabled(true)
        setMaxRetries(String(DEFAULT_MCP_FORM_CONFIG.retries))
        setRetryDelay(
          String(
            Math.floor(
              (editData.timeout || DEFAULT_MCP_FORM_CONFIG.timeout) /
                DEFAULT_MCP_FORM_CONFIG.retries,
            ),
          ),
        )
      }
    } else if (!open) {
      // Reset form
      setName('')
      setTransport(DEFAULT_MCP_FORM_CONFIG.transport)
      setAddress('')
      setHeaders([])
      setRetryEnabled(false)
      setMaxRetries(String(DEFAULT_MCP_FORM_CONFIG.retries))
      setRetryDelay('1000')
      setStatusEnabled(DEFAULT_MCP_FORM_CONFIG.enabled)
      setJsonContent('')
    }
  }, [open, editingServer])

  const handleHeaderAdd = () => {
    setHeaders([...headers, { key: '', value: '' }])
  }

  const handleHeaderRemove = (index: number) => {
    setHeaders(headers.filter((_, i) => i !== index))
  }

  const handleHeaderChange = (index: number, field: 'key' | 'value', value: string) => {
    const newHeaders = [...headers]
    newHeaders[index] = { ...newHeaders[index], [field]: value }
    setHeaders(newHeaders)
  }

  const handleSave = async () => {
    if (!name.trim() || !address.trim()) {
      toast({
        title: t('settings.validationError'),
        description: t('settings.fillRequiredFields'),
        variant: 'destructive',
      })
      return
    }

    try {
      // 1) Test connection first to avoid saving incorrect address/transport configuration
      // Note: backend supports both 'sse' and 'streamable-http' transport methods, do not convert
      const testResult = await testMcpServer.mutateAsync({
        transport: transport,
        url: transport !== 'stdio' ? address.trim() : undefined,
        headers: headers.reduce(
          (acc, h) => {
            if (h.key.trim() && h.value.trim()) {
              acc[h.key.trim()] = h.value.trim()
            }
            return acc
          },
          {} as Record<string, string>,
        ),
        timeout: retryEnabled ? Number(retryDelay) * Number(maxRetries) : 30000,
      })

      if (!testResult.success) {
        toast({
          title: t('settings.connectionFailed'),
          description: testResult.error || t('settings.connectionFailedDescription'),
          variant: 'destructive',
        })
        return
      }

      // 2) Save configuration after test passes
      // Map form data to API format
      const config = {
        name: name.trim(),
        transport: transport,
        url: transport !== 'stdio' ? address.trim() : undefined,
        headers: headers.reduce(
          (acc, h) => {
            if (h.key.trim() && h.value.trim()) {
              acc[h.key.trim()] = h.value.trim()
            }
            return acc
          },
          {} as Record<string, string>,
        ),
        timeout: retryEnabled ? Number(retryDelay) * Number(maxRetries) : 30000,
        enabled: statusEnabled,
      }

      if (isEditMode && editingServer) {
        await updateMcpServer.mutateAsync({
          serverId: editingServer.id,
          updates: config,
        })
        toast({
          title: t('settings.success'),
          description: t('settings.serverUpdated', { name }),
        })
      } else {
        await createMcpServer.mutateAsync({ config })
        toast({
          title: t('settings.success'),
          description: t('settings.serverCreated', { name }),
        })
      }

      onOpenChange(false)
    } catch (error) {
      toast({
        title: t('settings.error'),
        description: error instanceof Error ? error.message : t('settings.failedToCreate'),
        variant: 'destructive',
      })
    }
  }

  const isSaving = createMcpServer.isPending || updateMcpServer.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-xl gap-0 overflow-hidden border-0 bg-[var(--surface-dialog)] p-0 shadow-2xl sm:rounded-2xl"
        hideCloseButton
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-[var(--border-muted)] bg-[var(--surface-elevated)] px-6 py-4">
          <DialogTitle className="text-base font-bold text-[var(--text-primary)]">
            {isEditMode ? t('settings.editMcpServer') : t('settings.addMcpServer')}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {isEditMode
              ? t('settings.editMcpServerDescription')
              : t('settings.addMcpServerDescription')}
          </DialogDescription>
          <button
            onClick={() => onOpenChange(false)}
            className="rounded-full p-1 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-secondary)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-[var(--border-muted)] bg-[var(--surface-elevated)] px-6">
          <button
            onClick={() => setMode('form')}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition-colors focus:outline-none',
              mode === 'form'
                ? 'border-primary text-primary'
                : 'border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
            )}
          >
            <SquarePen size={14} /> {t('settings.formMode')}
          </button>
          <button
            onClick={() => setMode('json')}
            className={cn(
              'flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold transition-colors focus:outline-none',
              mode === 'json'
                ? 'border-primary text-primary'
                : 'border-transparent text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]',
            )}
          >
            <FileJson size={14} /> {t('settings.jsonMode')}
          </button>
        </div>

        {/* Content */}
        <div className="custom-scrollbar max-h-[60vh] space-y-6 overflow-y-auto bg-[var(--surface-dialog)] p-6">
          {mode === 'form' ? (
            <>
              {/* Basic Info */}
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <Label className="flex items-center gap-1 text-xs font-semibold text-[var(--text-secondary)]">
                    <span className="text-red-500">*</span> {t('settings.name')}
                  </Label>
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t('settings.namePlaceholder')}
                    className="h-10 border-[var(--border)] bg-[var(--surface-elevated)] text-sm focus-visible:border-primary focus-visible:ring-primary"
                  />
                </div>

                <div className="space-y-1.5">
                  <Label className="flex items-center gap-1 text-xs font-semibold text-[var(--text-secondary)]">
                    <span className="text-red-500">*</span> {t('settings.type')}{' '}
                    <Info size={12} className="text-[var(--text-muted)]" />
                  </Label>
                  <Select
                    value={transport}
                    onValueChange={(v) => setTransport(v as typeof transport)}
                  >
                    <SelectTrigger className="h-10 border-[var(--border)] bg-[var(--surface-elevated)] text-sm focus:border-[var(--brand-500)] focus:ring-[var(--brand-500)]">
                      <SelectValue placeholder={t('settings.selectType')} />
                    </SelectTrigger>
                    <SelectContent position="popper" className="z-[10000001]">
                      <SelectItem value="streamable-http">
                        {t('settings.streamableHttp')}
                      </SelectItem>
                      <SelectItem value="sse">{t('settings.sse')}</SelectItem>
                      <SelectItem value="stdio">{t('settings.stdio')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <Label className="flex items-center gap-1 text-xs font-semibold text-[var(--text-secondary)]">
                    <span className="text-red-500">*</span> {t('settings.addressCommand')}
                  </Label>
                  <Input
                    value={address}
                    onChange={(e) => setAddress(e.target.value)}
                    placeholder={t('settings.addressCommandPlaceholder')}
                    className="h-10 border-[var(--border)] bg-[var(--surface-elevated)] font-mono text-sm text-xs focus-visible:border-primary focus-visible:ring-primary"
                  />
                </div>
              </div>

              {/* Request Headers */}
              <div className="space-y-2">
                <Label className="text-xs font-semibold text-[var(--text-secondary)]">
                  {t('settings.requestHeaders')}
                </Label>
                <div className="space-y-2">
                  {headers.map((header, idx) => (
                    <div
                      key={idx}
                      className="flex items-center gap-2 duration-200 animate-in fade-in slide-in-from-left-2"
                    >
                      <Input
                        placeholder={t('settings.headerKey')}
                        className="h-9 flex-1 bg-[var(--surface-elevated)] font-mono text-xs"
                        value={header.key}
                        onChange={(e) => handleHeaderChange(idx, 'key', e.target.value)}
                      />
                      <span className="text-[var(--text-subtle)]">:</span>
                      <Input
                        placeholder={t('settings.headerValue')}
                        className="h-9 flex-1 bg-[var(--surface-elevated)] font-mono text-xs"
                        value={header.value}
                        onChange={(e) => handleHeaderChange(idx, 'value', e.target.value)}
                      />
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-9 w-9 text-[var(--text-muted)] hover:bg-red-50 hover:text-red-500"
                        onClick={() => handleHeaderRemove(idx)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="outline"
                    onClick={handleHeaderAdd}
                    className="h-9 w-full gap-2 border-dashed border-[var(--border-strong)] text-xs text-[var(--text-tertiary)] hover:border-primary/30 hover:bg-[var(--brand-50)] hover:text-[var(--brand-600)]"
                  >
                    <Plus size={14} /> {t('settings.addHeader')}
                  </Button>
                </div>
              </div>

              {/* Retry Settings */}
              <div className="space-y-4 rounded-xl border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Label
                      className="cursor-pointer text-sm font-medium text-[var(--text-primary)]"
                      onClick={() => setRetryEnabled(!retryEnabled)}
                    >
                      {t('settings.retryPolicy')}
                    </Label>
                    <Info size={12} className="text-[var(--text-muted)]" />
                  </div>
                  <Switch checked={retryEnabled} onCheckedChange={setRetryEnabled} />
                </div>

                {retryEnabled && (
                  <div className="grid grid-cols-2 gap-4 border-t border-[var(--surface-1)] pt-2 duration-200 animate-in fade-in slide-in-from-top-1">
                    <div className="space-y-1.5">
                      <Label className="text-2xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                        {t('settings.maxRetries')}
                      </Label>
                      <Input
                        type="number"
                        value={maxRetries}
                        onChange={(e) => setMaxRetries(e.target.value)}
                        className="h-8 border-[var(--border)] bg-[var(--surface-1)] text-xs"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-2xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                        {t('settings.delayMs')}
                      </Label>
                      <Input
                        type="number"
                        value={retryDelay}
                        onChange={(e) => setRetryDelay(e.target.value)}
                        className="h-8 border-[var(--border)] bg-[var(--surface-1)] text-xs"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Status */}
              <div className="flex items-center justify-between rounded-xl border border-[var(--border-muted)] bg-[var(--surface-elevated)] p-4 shadow-sm">
                <div className="space-y-0.5">
                  <Label className="text-sm font-medium text-[var(--text-primary)]">
                    {t('settings.activeStatus')}
                  </Label>
                  <p className="text-xs text-[var(--text-muted)]">{t('settings.activeStatusDescription')}</p>
                </div>
                <Switch checked={statusEnabled} onCheckedChange={setStatusEnabled} />
              </div>
            </>
          ) : (
            <div className="flex h-full flex-col space-y-2">
              <Label className="text-xs font-semibold text-[var(--text-secondary)]">
                {t('settings.configurationJson')}
              </Label>
              <Textarea
                value={jsonContent}
                onChange={(e) => setJsonContent(e.target.value)}
                className="min-h-[300px] flex-1 resize-none border-[var(--border)] bg-[var(--surface-elevated)] p-4 font-mono text-xs leading-relaxed"
                placeholder={t('settings.jsonPlaceholder')}
                spellCheck={false}
              />
              <p className="text-2xs text-[var(--text-muted)]">{t('settings.jsonHint')}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t border-[var(--border-muted)] bg-[var(--surface-elevated)] p-6">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            {t('settings.cancel')}
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={isSaving || (!name && mode === 'form')}
            className="gap-2"
          >
            {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            {isSaving
              ? t('settings.saving')
              : isEditMode
                ? t('settings.updateServer')
                : t('settings.createServer')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
