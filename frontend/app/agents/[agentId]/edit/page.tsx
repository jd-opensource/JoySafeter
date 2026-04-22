'use client'

import { Lock, Loader2, Save } from 'lucide-react'
import { useParams } from 'next/navigation'
import { useState, useEffect } from 'react'
import dynamic from 'next/dynamic'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { useAgent } from '@/hooks/queries/agents'
import { useVersion, useUpdateVersion, useFreezeVersion } from '@/hooks/queries/agentVersions'
import { useWorkspaces } from '@/hooks/queries/workspaces'

// Lazy load the heavy graph builder
const AgentBuilder = dynamic(
  () => import('@/components/editors/graph-builder/AgentBuilder'),
  { ssr: false, loading: () => <div className="flex items-center gap-2 px-6 py-6 text-sm text-[var(--text-muted)]"><Loader2 className="h-4 w-4 animate-spin" />Loading graph editor...</div> }
)

export default function AgentEditPage() {
  const params = useParams()
  const agentId = params.agentId as string

  const { data: workspaces = [] } = useWorkspaces()
  const personalWorkspace = workspaces.find((ws) => ws.type === 'personal')
  const workspaceId = personalWorkspace?.id || ''

  const { data: agent } = useAgent(agentId, workspaceId)
  const draftVersionId = agent?.current_draft_version_id || ''

  const { data: version, isLoading: versionLoading } = useVersion(
    agentId,
    draftVersionId,
    workspaceId,
    { enabled: Boolean(draftVersionId) },
  )

  const updateMutation = useUpdateVersion()
  const freezeMutation = useFreezeVersion()

  const [instructions, setInstructions] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')

  useEffect(() => {
    if (version) {
      const payload = version.definition_payload || {}
      setInstructions((payload.instructions as string) || '')
      setSystemPrompt((payload.system_prompt as string) || '')
    }
  }, [version])

  function handleSave() {
    if (!version) return
    updateMutation.mutate({
      agentId,
      versionId: version.id,
      workspaceId,
      definition_payload: {
        ...version.definition_payload,
        instructions,
        system_prompt: systemPrompt,
      },
    })
  }

  function handleFreeze() {
    if (!version) return
    freezeMutation.mutate({ agentId, versionId: version.id, workspaceId })
  }

  if (!agent) return null

  if (!draftVersionId) {
    return (
      <div className="px-6 py-6">
        <p className="text-sm text-[var(--text-muted)]">
          No draft version exists for this agent.
        </p>
      </div>
    )
  }

  if (versionLoading) {
    return (
      <div className="flex items-center gap-2 px-6 py-6 text-sm text-[var(--text-muted)]">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading version...
      </div>
    )
  }

  if (!version) return null

  const isFrozen = version.status === 'frozen'
  const definitionKind = version.definition_kind

  // Route to appropriate editor based on definition_kind
  if (definitionKind === 'graph') {
    return (
      <AgentBuilder
        workspaceId={workspaceId}
        agentId={agentId}
        versionId={draftVersionId!}
      />
    )
  }

  if (definitionKind === 'code') {
    return (
      <Card className="mx-6 my-6 border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
        <p className="text-sm text-[var(--text-muted)]">
          Code editor coming in a future phase.
        </p>
      </Card>
    )
  }

  // Prompt editor (default)
  const isPrompt = definitionKind === 'prompt'

  return (
    <div className="space-y-6 px-6 py-6">
      {/* Version header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">
            Version {version.version_number}
          </h2>
          <Badge variant="outline">{version.definition_kind}</Badge>
          <Badge variant={isFrozen ? 'secondary' : 'default'}>
            {isFrozen ? 'Frozen' : 'Draft'}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          {!isFrozen && isPrompt && (
            <Button
              size="sm"
              className="gap-1.5"
              onClick={handleSave}
              disabled={updateMutation.isPending}
            >
              {updateMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              Save
            </Button>
          )}
          {!isFrozen && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={handleFreeze}
              disabled={freezeMutation.isPending}
            >
              {freezeMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Lock className="h-3.5 w-3.5" />
              )}
              Freeze
            </Button>
          )}
        </div>
      </div>

      {/* Editor */}
      {isPrompt ? (
        <div className="space-y-4">
          <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
            <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
              System Prompt
            </label>
            <Textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="System prompt for the agent..."
              rows={4}
              disabled={isFrozen}
            />
          </Card>
          <Card className="border-[var(--border)] bg-[var(--surface-1)] p-5">
            <label className="mb-2 block text-sm font-medium text-[var(--text-primary)]">
              Instructions
            </label>
            <Textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="Instructions for the agent..."
              rows={8}
              disabled={isFrozen}
            />
          </Card>
        </div>
      ) : (
        <Card className="border-[var(--border)] bg-[var(--surface-1)] p-8 text-center">
          <p className="text-sm text-[var(--text-muted)]">
            Hybrid editor coming in a future phase.
          </p>
        </Card>
      )}
    </div>
  )
}
