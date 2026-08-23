'use client'

import { useState } from 'react'

import { CompatibleCredentialPicker } from '@/components/managed/llm/compatible-credential-picker'
import { ModelConnectionConfigurator } from '@/components/managed/llm/model-connection-configurator'
import type { CredentialDetail } from '@/types/managed'

interface QuickstartLlmStepProps {
  engineId: string
  value: string
  disabled?: boolean
  onSelect: (value: string) => void
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
        onCreated={(secret) => {
          setView('select')
          onCreated(secret)
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
