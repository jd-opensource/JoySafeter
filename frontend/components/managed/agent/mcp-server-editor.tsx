'use client'

import { Plus, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTranslation } from '@/lib/i18n'
import { toastOperationError } from '@/lib/managed/errors'
import {
  mcpServerEndpointLabel,
  parseMcpArgsInput,
  parseMcpEnvInput,
  validateUniqueMcpServerName,
  type McpPermissionPolicy,
  type McpServerEntry,
} from '@/lib/managed/mcp-config'
import { validateUrlScheme } from '@/lib/utils/url-validation'
import type { McpAuthRequirement, McpRemoteTransport } from '@/types/managed'

interface McpServerEditorProps {
  value: McpServerEntry[]
  onChange: (value: McpServerEntry[]) => void
  disabled?: boolean
}

const TRANSPORTS: Array<{ value: McpRemoteTransport | 'local_stdio'; labelKey: string }> = [
  { value: 'streamable_http', labelKey: 'managed.agents.create.mcpTransportStreamableHttp' },
  { value: 'sse', labelKey: 'managed.agents.create.mcpTransportSse' },
  { value: 'local_stdio', labelKey: 'managed.agents.create.mcpTransportLocalStdio' },
]

const AUTH_REQUIREMENTS: Array<{ value: McpAuthRequirement; labelKey: string }> = [
  { value: 'required', labelKey: 'managed.agents.create.mcpAuthRequired' },
  { value: 'optional', labelKey: 'managed.agents.create.mcpAuthOptional' },
  { value: 'none', labelKey: 'managed.agents.create.mcpAuthNone' },
]

function transportLabelKey(type: McpRemoteTransport | 'local_stdio'): string {
  return TRANSPORTS.find((option) => option.value === type)!.labelKey
}

export function McpServerEditor({ value, onChange, disabled = false }: McpServerEditorProps) {
  const { t } = useTranslation()
  const id = useId()
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [transport, setTransport] = useState<McpRemoteTransport | 'local_stdio'>('streamable_http')
  const [url, setUrl] = useState('')
  const [authRequirement, setAuthRequirement] = useState<McpAuthRequirement>('required')
  const [command, setCommand] = useState('')
  const [args, setArgs] = useState('')
  const [env, setEnv] = useState('')

  const resetDraft = () => {
    setName('')
    setTransport('streamable_http')
    setUrl('')
    setAuthRequirement('required')
    setCommand('')
    setArgs('')
    setEnv('')
  }

  const cancelDraft = () => {
    resetDraft()
    setShowForm(false)
  }

  const addServer = () => {
    const normalizedName = name.trim()
    if (!normalizedName) return
    const nameError = validateUniqueMcpServerName(normalizedName, value)
    if (nameError) {
      toastOperationError(t, new Error(nameError), 'common.error')
      return
    }

    let next: McpServerEntry
    if (transport === 'local_stdio') {
      const normalizedCommand = command.trim()
      if (!normalizedCommand) return
      try {
        next = {
          type: 'local_stdio',
          name: normalizedName,
          command: normalizedCommand,
          args: parseMcpArgsInput(args),
          env: parseMcpEnvInput(env),
          policy: 'always_ask',
        }
      } catch (error) {
        toastOperationError(t, error, 'common.error')
        return
      }
    } else {
      const normalizedUrl = url.trim()
      if (!normalizedUrl) return
      const urlError = validateUrlScheme(normalizedUrl)
      if (urlError) {
        toastOperationError(t, new Error(urlError), 'common.error')
        return
      }
      next = {
        type: transport,
        name: normalizedName,
        url: normalizedUrl,
        auth_requirement: transport === 'sse' ? 'none' : authRequirement,
        policy: 'always_ask',
      }
    }

    onChange([...value, next])
    cancelDraft()
  }

  const setPolicy = (index: number, policy: McpPermissionPolicy) => {
    onChange(
      value.map((server, serverIndex) => (serverIndex === index ? { ...server, policy } : server)),
    )
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2">
        <h3 className="text-sm font-semibold text-foreground">
          {t('managed.agents.edit.mcpServers')}
          <span className="ml-1 text-xs font-normal text-muted-foreground">
            {t('managed.agents.formOptional')}
          </span>
        </h3>
        <button
          type="button"
          title={t('managed.agents.create.addMcpServer')}
          disabled={disabled}
          onClick={() => setShowForm(true)}
          className="flex h-6 w-6 items-center justify-center rounded border border-border transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
      <p className="text-xs text-muted-foreground">
        {t('managed.agents.create.mcpConnectionBoundary')}
      </p>

      {value.length === 0 && !showForm && (
        <p className="py-2 text-center text-sm text-muted-foreground">
          {t('managed.agents.create.noMcpServers')}
        </p>
      )}

      {value.map((server, index) => (
        <div key={`${server.name}:${server.type}`} className="flex items-center gap-2 text-sm">
          <span className="font-medium">{server.name}</span>
          <span className="flex-1 truncate text-muted-foreground">
            {mcpServerEndpointLabel(server)}
          </span>
          <span className="text-xs text-muted-foreground">{t(transportLabelKey(server.type))}</span>
          <select
            value={server.policy}
            disabled={disabled}
            onChange={(event) => setPolicy(index, event.target.value as McpPermissionPolicy)}
            className="h-7 rounded border border-border bg-background px-1.5 text-xs"
            title={t('managed.agents.create.mcpPolicyHint')}
          >
            <option value="always_ask">{t('managed.policy.alwaysAsk')}</option>
            <option value="always_allow">{t('managed.policy.alwaysAllow')}</option>
          </select>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(value.filter((_, serverIndex) => serverIndex !== index))}
            className="text-muted-foreground hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}

      {showForm && (
        <div className="space-y-3 rounded-md border border-border p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor={`${id}-transport`} className="text-sm font-medium">
                {t('managed.agents.create.mcpTransport')}
              </label>
              <select
                id={`${id}-transport`}
                value={transport}
                disabled={disabled}
                onChange={(event) => {
                  const nextTransport = event.target.value as McpRemoteTransport | 'local_stdio'
                  setTransport(nextTransport)
                  if (nextTransport === 'sse') setAuthRequirement('none')
                }}
                className="flex h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
              >
                {TRANSPORTS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label htmlFor={`${id}-name`} className="text-sm font-medium">
                {t('managed.agents.create.mcpName')}
              </label>
              <Input
                id={`${id}-name`}
                placeholder={t('managed.agents.create.mcpNamePlaceholder')}
                value={name}
                disabled={disabled}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
          </div>

          {transport === 'local_stdio' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <label htmlFor={`${id}-command`} className="text-sm font-medium">
                  {t('managed.agents.create.mcpCommand')}
                </label>
                <Input
                  id={`${id}-command`}
                  placeholder={t('managed.agents.create.mcpCommandPlaceholder')}
                  value={command}
                  disabled={disabled}
                  onChange={(event) => setCommand(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor={`${id}-args`} className="text-sm font-medium">
                  {t('managed.agents.create.mcpArgs')}
                </label>
                <textarea
                  id={`${id}-args`}
                  placeholder={t('managed.agents.create.mcpArgsPlaceholder')}
                  value={args}
                  disabled={disabled}
                  onChange={(event) => setArgs(event.target.value)}
                  className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  {t('managed.agents.create.mcpLocalEnvWarning')}
                </p>
              </div>
              <div className="space-y-1.5">
                <label htmlFor={`${id}-env`} className="text-sm font-medium">
                  {t('managed.agents.create.mcpEnv')}
                </label>
                <textarea
                  id={`${id}-env`}
                  placeholder={t('managed.agents.create.mcpEnvPlaceholder')}
                  value={env}
                  disabled={disabled}
                  onChange={(event) => setEnv(event.target.value)}
                  className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm"
                />
              </div>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor={`${id}-url`} className="text-sm font-medium">
                  {t('managed.agents.create.mcpUrl')}
                </label>
                <Input
                  id={`${id}-url`}
                  placeholder={t('managed.agents.create.mcpUrlPlaceholder')}
                  value={url}
                  disabled={disabled}
                  onChange={(event) => setUrl(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor={`${id}-auth`} className="text-sm font-medium">
                  {t('managed.agents.create.mcpAuthRequirement')}
                </label>
                <select
                  id={`${id}-auth`}
                  value={authRequirement}
                  disabled={disabled || transport === 'sse'}
                  onChange={(event) => setAuthRequirement(event.target.value as McpAuthRequirement)}
                  className="flex h-9 w-full rounded-md border border-border bg-background px-3 text-sm"
                >
                  {AUTH_REQUIREMENTS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.labelKey)}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  {transport === 'sse'
                    ? t('managed.agents.create.mcpSseAuthLimitation')
                    : t('managed.agents.create.mcpUrlMatchHint')}
                </p>
              </div>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={cancelDraft}>
              {t('common.cancel')}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={addServer}>
              {t('managed.agents.create.add')}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
