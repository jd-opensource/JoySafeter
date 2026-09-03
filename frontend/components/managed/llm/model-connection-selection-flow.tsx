'use client'

import { useState } from 'react'

import { CompatibleCredentialPicker } from '@/components/managed/llm/compatible-credential-picker'
import { ModelConnectionConfigurator } from '@/components/managed/llm/model-connection-configurator'
import type { CredentialId } from '@/types/entity-id'
import type { Credential, CredentialDetail } from '@/types/managed'

interface ModelConnectionSelectionFlowProps {
  engineId?: string
  modelConsumerId?: string
  value: CredentialId | ''
  disabled?: boolean
  allowNone?: boolean
  conflictCredential?: Credential | null
  conflictValue?: string
  conflictMessage?: string
  onSelect: (value: CredentialId | '') => void
  onCreated: (credential: CredentialDetail) => void
}

export function ModelConnectionSelectionFlow({
  engineId,
  modelConsumerId,
  value,
  disabled = false,
  allowNone = false,
  conflictCredential,
  conflictValue,
  conflictMessage,
  onSelect,
  onCreated,
}: ModelConnectionSelectionFlowProps) {
  const [view, setView] = useState<'select' | 'create'>('select')

  if (view === 'create') {
    return (
      <ModelConnectionConfigurator
        initialEngineId={engineId}
        initialModelConsumerId={modelConsumerId}
        onCancel={() => setView('select')}
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
      modelConsumerId={modelConsumerId}
      value={value}
      allowNone={allowNone}
      disabled={disabled}
      conflictCredential={conflictCredential}
      conflictValue={conflictValue}
      conflictMessage={conflictMessage}
      onChange={onSelect}
      onCreateRequested={() => setView('create')}
    />
  )
}
