'use client'

import { useState } from 'react'

import { CompatibleCredentialPicker } from '@/components/managed/llm/compatible-credential-picker'
import { ModelConnectionConfigurator } from '@/components/managed/llm/model-connection-configurator'
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
  const [view, setView] = useState<'select' | 'create'>('select')

  if (view === 'create') {
    return (
      <ModelConnectionConfigurator
        initialEngineId={engineId}
        onCancel={() => {
          setView('select')
        }}
        onCreated={(credential) => {
          setView('select')
          onCreated(credential)
        }}
      />
    )
  }

  return (
    <CompatibleCredentialPicker
      engineId={engineId}
      value={value}
      disabled={disabled}
      onChange={onSelect}
      onCreateRequested={() => setView('create')}
    />
  )
}
