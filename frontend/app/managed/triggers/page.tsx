'use client'

import { Copy, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { managedGet } from '@/lib/api-client'
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

export default function AgentTriggersPage() {
  const scope = useManagedRequestScope()
  const triggersQuery = useAgentTriggers()
  const createMut = useCreateAgentTrigger()
  const deleteMut = useDeleteAgentTrigger()
  const [agents, setAgents] = useState<AgentOption[]>([])
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<WebhookForm>({
    name: '',
    agent_id: '',
    prompt_template: 'Handle webhook payload:\n{{ body }}',
    secret_ref: '',
    description: '',
    session_mode: 'fresh',
  })

  useEffect(() => {
    if (!scope.key) return
    managedGet<any>('/agents?limit=100', managedRequestOptions(scope))
      .then((res) => setAgents((Array.isArray(res) ? res : res?.data ?? []).map((a: any) => ({ id: a.id, name: a.name ?? a.id }))))
      .catch(() => setAgents([]))
  }, [scope.key])

  const triggers = triggersQuery.data ?? []

  async function createTrigger() {
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
      setForm({ name: '', agent_id: '', prompt_template: 'Handle webhook payload:\n{{ body }}', secret_ref: '', description: '', session_mode: 'fresh' })
      toastSuccess('触发器已创建')
    } catch (error) {
      toastError(error instanceof Error ? error.message : '创建触发器失败')
    }
  }

  return (
    <main className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">触发器</h1>
          <p className="text-sm text-muted-foreground">配置 webhook 触发指定智能体执行 prompt。</p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)}><Plus className="mr-2 h-4 w-4" />新建触发器</Button>
      </div>

      {showForm && (
        <section className="space-y-4 rounded-lg border bg-card p-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>名称</Label>
              <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="告警 webhook" />
            </div>
            <div className="space-y-2">
              <Label>智能体</Label>
              <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}>
                <option value="">请选择智能体</option>
                {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
              </select>
            </div>
            <div className="space-y-2">
              <Label>Secret 引用</Label>
              <Input value={form.secret_ref} onChange={(e) => setForm({ ...form, secret_ref: e.target.value })} placeholder="选择或输入保存 WEBHOOK_SECRET 的密钥名称" />
            </div>
            <div className="space-y-2">
              <Label>会话模式</Label>
              <select className="h-10 w-full rounded-md border bg-background px-3 text-sm" value={form.session_mode} onChange={(e) => setForm({ ...form, session_mode: e.target.value as 'fresh' | 'reuse' })}>
                <option value="fresh">每次新建会话</option>
                <option value="reuse">复用触发器会话</option>
              </select>
            </div>
          </div>
          <div className="space-y-2">
            <Label>Prompt 模板</Label>
            <Textarea className="min-h-32" value={form.prompt_template} onChange={(e) => setForm({ ...form, prompt_template: e.target.value })} />
            <p className="text-xs text-muted-foreground">可用变量示例：{'{{ body }}'}、{'{{ body.alert.name }}'}、{'{{ headers.user_agent }}'}。</p>
          </div>
          <Button disabled={!form.name || !form.agent_id || !form.secret_ref || !form.prompt_template || createMut.isPending} onClick={createTrigger}>保存</Button>
        </section>
      )}

      <section className="space-y-3">
        {triggers.map((trigger) => (
          <div key={trigger.id} className="rounded-lg border bg-card p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 space-y-1">
                <div className="font-medium">{trigger.name}</div>
                <div className="text-sm text-muted-foreground">{trigger.enabled ? '已启用' : '已禁用'} · {trigger.session_mode}</div>
                <code className="block truncate rounded bg-muted px-2 py-1 text-xs">{trigger.webhook_url}</code>
                {trigger.last_error && <div className="text-sm text-destructive">最近错误：{trigger.last_error}</div>}
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={async () => { await navigator.clipboard?.writeText(trigger.webhook_url ?? ''); toastSuccess('Webhook URL 已复制') }}><Copy className="h-4 w-4" /></Button>
                <Button variant="destructive" size="sm" onClick={() => deleteMut.mutate(trigger.id)}><Trash2 className="h-4 w-4" /></Button>
              </div>
            </div>
          </div>
        ))}
        {!triggers.length && <div className="rounded-lg border bg-card p-8 text-center text-muted-foreground">暂无触发器</div>}
      </section>
    </main>
  )
}
