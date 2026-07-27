'use client'

import { Copy, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useCurrentProjectReadOnly, currentProjectAllowsWrite } from '@/hooks/managed/use-current-project-read-only'
import { managedGet } from '@/lib/api-client'
import { useTranslation } from '@/lib/i18n'
import { useManagedRequestScope, managedRequestOptions } from '@/lib/managed/request-scope'
import { useAgentTriggers, useCreateAgentTrigger, useDeleteAgentTrigger } from '@/lib/managed/triggers'
import { toastSuccess, toastError } from '@/lib/utils/toast'

interface AgentOption {
  id: string
  name: string
}

type WebhookForm = {
  name: string
  agent_id: string
  prompt_template: string
  secret_ref: string
  description: string
  session_mode: 'fresh' | 'reuse'
}

const EMPTY_FORM: WebhookForm = {
  name: '',
  agent_id: '',
  prompt_template: 'Handle webhook payload:\n{{ body }}',
  secret_ref: '',
  description: '',
  session_mode: 'fresh',
}

export default function AgentTriggersPage() {
  const { t } = useTranslation()
  const projectReadOnly = useCurrentProjectReadOnly()
  const scope = useManagedRequestScope()
  const triggersQuery = useAgentTriggers()
  const createMut = useCreateAgentTrigger()
  const deleteMut = useDeleteAgentTrigger()
  const [agents, setAgents] = useState<AgentOption[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<WebhookForm>(EMPTY_FORM)

  useEffect(() => {
    if (!scope.key) return
    managedGet<any>('/agents?limit=100', managedRequestOptions(scope))
      .then((res) => setAgents((Array.isArray(res) ? res : res?.data ?? []).map((a: any) => ({ id: a.id, name: a.name ?? a.id }))))
      .catch(() => setAgents([]))
  }, [scope.key])

  const triggers = triggersQuery.data ?? []

  async function createTrigger() {
    if (!currentProjectAllowsWrite()) return
    try {
      await createMut.mutateAsync({
        name: form.name,
        agent_id: form.agent_id,
        prompt_template: form.prompt_template,
        secret_ref: form.secret_ref,
        secret_key: 'WEBHOOK_SECRET',
        description: form.description || null,
        session_mode: form.session_mode,
        type: 'webhook',
      })
      setShowForm(false)
      setForm(EMPTY_FORM)
      toastSuccess(t('managed.triggers.created'))
    } catch (error) {
      toastError(error instanceof Error ? error.message : t('managed.triggers.createFailed'))
    }
  }

  function deleteTrigger(id: string) {
    if (!currentProjectAllowsWrite()) return
    deleteMut.mutate(id)
  }

  return (
    <main className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('managed.triggers.title')}</h1>
          <p className="text-sm text-muted-foreground">{t('managed.triggers.subtitle')}</p>
        </div>
        {!projectReadOnly && (
          <Button onClick={() => setShowForm((v) => !v)}><Plus className="mr-2 h-4 w-4" />{t('managed.triggers.new')}</Button>
        )}
      </div>

      {showForm && !projectReadOnly && (
        <section className="space-y-4 rounded-lg border bg-card p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('managed.triggers.name')}</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={t('managed.triggers.namePlaceholder')} />
            </div>
            <div className="space-y-2">
              <Label>{t('managed.triggers.agent')}</Label>
              <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}>
                <option value="">{t('managed.triggers.selectAgent')}</option>
                {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <Label>{t('managed.triggers.secretRef')}</Label>
              <Input value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} placeholder={t('managed.triggers.secretRefPlaceholder')} />
            </div>
            <div className="space-y-2">
              <Label>{t('managed.triggers.sessionMode')}</Label>
              <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.session_mode} onChange={(e) => setForm({ ...form, session_mode: e.target.value as 'fresh' | 'reuse' })}>
                <option value="fresh">{t('managed.schedules.sessionModeOption.fresh')}</option>
                <option value="reuse">{t('managed.schedules.sessionModeOption.reuse')}</option>
              </select>
            </div>
          </div>
          <div className="space-y-2">
            <Label>{t('managed.triggers.promptTemplate')}</Label>
            <Textarea className="min-h-32" value={form.prompt_template} onChange={(e) => setForm({ ...form, prompt_template: e.target.value })} />
            <p className="text-xs text-muted-foreground">
              {t('managed.triggers.promptVarsHint')}{' '}
              <code>{'{{ body }}'}</code>, <code>{'{{ body.alert.name }}'}</code>, <code>{'{{ headers.user_agent }}'}</code>
            </p>
          </div>
          <Button disabled={!form.name || !form.agent_id || !form.secret_ref || !form.prompt_template || createMut.isPending} onClick={createTrigger}>{t('common.save')}</Button>
        </section>
      )}

      <section className="space-y-3">
        {triggers.map((trigger) => (
          <div key={trigger.id} className="rounded-lg border bg-card p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <div className="font-medium">{trigger.name}</div>
                <div className="text-sm text-muted-foreground">
                  {trigger.enabled ? t('managed.triggers.enabled') : t('managed.triggers.disabled')} · {t(`managed.schedules.sessionModeOption.${trigger.session_mode || 'fresh'}`)}
                </div>
                <code className="block truncate rounded bg-muted px-2 py-1 text-xs">{trigger.webhook_url}</code>
                {trigger.last_error && <div className="text-sm text-destructive">{t('managed.triggers.lastError')} {trigger.last_error}</div>}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={async () => { await navigator.clipboard?.writeText(trigger.webhook_url ?? ''); toastSuccess(t('managed.triggers.urlCopied')) }}><Copy className="h-4 w-4" /></Button>
                {!projectReadOnly && (
                  <Button variant="destructive" size="sm" onClick={() => deleteTrigger(trigger.id)}><Trash2 className="h-4 w-4" /></Button>
                )}
              </div>
            </div>
          </div>
        ))}
        {!triggers.length && <div className="rounded-lg border bg-card p-8 text-center text-muted-foreground">{t('managed.triggers.empty')}</div>}
      </section>
    </main>
  )
}
