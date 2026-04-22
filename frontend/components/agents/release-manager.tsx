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
import type { AgentVersion } from '@/types/agent'

type RuntimeKind = 'graph' | 'sandbox' | 'hosted' | 'external'

const RUNTIME_KIND_OPTIONS: RuntimeKind[] = ['graph', 'sandbox', 'hosted', 'external']

const RUNTIME_KIND_LABELS: Record<RuntimeKind, string> = {
  graph: 'Graph',
  sandbox: 'Sandbox',
  hosted: 'Hosted',
  external: 'External',
}

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
        return // invalid JSON, don't submit
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
          <DialogTitle>Publish New Release</DialogTitle>
          <DialogDescription>
            Create a new release from a frozen version.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Version selector */}
          <div className="space-y-2">
            <Label htmlFor="release-version">Version *</Label>
            {frozenVersions.length === 0 ? (
              <p className="text-sm text-[var(--text-muted)]">
                No frozen versions available. Freeze a version first.
              </p>
            ) : (
              <Select value={selectedVersionId} onValueChange={setSelectedVersionId}>
                <SelectTrigger id="release-version">
                  <SelectValue placeholder="Select a frozen version" />
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

          {/* Runtime kind */}
          <div className="space-y-2">
            <Label htmlFor="release-runtime-kind">Runtime Kind</Label>
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
                    {RUNTIME_KIND_LABELS[rk]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Runtime binding JSON */}
          <div className="space-y-2">
            <Label htmlFor="release-runtime-binding">Runtime Binding (JSON)</Label>
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
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!selectedVersionId || frozenVersions.length === 0 || publishMutation.isPending}
            >
              {publishMutation.isPending ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Publishing...
                </>
              ) : (
                'Publish'
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
