'use client'

import { ModelConnectionSelectionFlow } from '@/components/managed/llm/model-connection-selection-flow'
import type { CredentialId } from '@/types/entity-id'
import type { CredentialDetail } from '@/types/managed'

interface QuickstartLlmStepProps {
  engineId: string
  value: CredentialId | ''
  disabled?: boolean
  onSelect: (value: CredentialId | '') => void
  onCreated: (credential: CredentialDetail) => void
}

export function QuickstartLlmStep({
  engineId,
  value,
  disabled = false,
  onSelect,
  onCreated,
}: QuickstartLlmStepProps) {
  return (
    <ModelConnectionSelectionFlow
      engineId={engineId}
      value={value}
      disabled={disabled}
      onSelect={onSelect}
      onCreated={onCreated}
    />
  )
}
