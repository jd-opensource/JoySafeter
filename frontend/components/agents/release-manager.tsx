'use client'

import { useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useVersions } from '@/hooks/queries/agentVersions'
import { usePublishRelease } from '@/hooks/queries/agentReleases'
import { useTranslation } from '@/lib/i18n'
import type { AgentVersion } from '@/types/agent'

type RuntimeKind = 'graph' | 'sandbox' | 'hosted' | 'external'

const RUNTIME_KIND_OPTIONS: RuntimeKind[] = ['graph', 'sandbox', 'hosted', 'external']

interface ReleaseManagerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  agentId: string
  workspaceId: string
}

export function ReleaseManager({
  open,
  onOpenChange,
  agentId,
  workspaceId,
}: ReleaseManagerProps) {
  const { t } = useTranslation()
  const { data: versions = [] } = useVersions(agentId, workspaceId)
  const publishMutation = usePublishRelease()

  const frozenVersions = versions.filter((v: AgentVersion) => v.status === 'frozen')

  const [selectedVersionId, setSelectedVersionId] = useState('')
  const [runtimeKind, setRuntimeKind] = useState<RuntimeKind>('graph')
  const [runtimeBindingJson, setRuntimeBindingJson] = useState('')

  function resetForm() {
    setSelectedVersionId('')
    setRuntimeKind('graph')
    setRuntimeBindingJson('')
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedVersionId) return

    let runtimeBinding: Record<string, unknown> | undefined
    if (runtimeBindingJson.trim()) {
      try {
        runtimeBinding = JSON.parse(runtimeBindingJson.trim())
      } catch {
        return
      }
    }

    publishMutation.mutate(
      {
        agentId,
        workspaceId,
        agent_version_id: selectedVersionId,
        runtime_kind: runtimeKind,
        runtime_binding: runtimeBinding,
      },
      {
        onSuccess: () => {
          resetForm()
          onOpenChange(false)
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('agents.detail.publishReleaseTitle')}</DialogTitle>
          <DialogDescription>{t('agents.detail.publishReleaseDescription')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="release-version">Version *</Label>
            {frozenVersions.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">
                {t('agents.detail.noFrozenVersions')}
              </p>
            ) : (
              <Select value={selectedVersionId} onValueChange={setSelectedVersionId}>
                <SelectTrigger id="release-version">
                  <SelectValue placeholder={t('agents.detail.selectFrozenVersion')} />
                </SelectTrigger>
                <SelectContent>
                  {frozenVersions.map((v: AgentVersion) => (
                    <SelectItem key={v.id} value={v.id}>
                      v{v.version_number} ({v.definition_kind})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="release-runtime-kind">{t('agents.detail.runtimeKind')}</Label>
            <Select
              value={runtimeKind}
              onValueChange={(v) => setRuntimeKind(v as RuntimeKind)}
            >
              <SelectTrigger id="release-runtime-kind">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RUNTIME_KIND_OPTIONS.map((rk) => (
                  <SelectItem key={rk} value={rk}>
                    {t(`agents.detail.runtimeKindOptions.${rk}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="release-runtime-binding">{t('agents.detail.runtimeBinding')}</Label>
            <Textarea
              id="release-runtime-binding"
              value={runtimeBindingJson}
              onChange={(e) => setRuntimeBindingJson(e.target.value)}
              placeholder='{"key": "value"}'
              rows={3}
              className="font-mono text-xs"
            />
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t('agents.cancel')}
            </Button>
            <Button
              type="submit"
              disabled={!selectedVersionId || frozenVersions.length === 0 || publishMutation.isPending}
            >
              {publishMutation.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  {t('agents.detail.publishingRelease')}
                </>
              ) : (
                t('agents.detail.publishRelease')
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
