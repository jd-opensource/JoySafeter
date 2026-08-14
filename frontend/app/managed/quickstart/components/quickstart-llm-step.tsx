'use client'

import { useState } from 'react'

import { CompatibleSecretPicker } from '@/components/managed/llm/compatible-secret-picker'
import { LlmSecretConfigurator } from '@/components/managed/llm/llm-secret-configurator'
import type { SecretDetail } from '@/types/managed'

interface QuickstartLlmStepProps {
  engineId: string
  value: string
  disabled?: boolean
  onSelect: (value: string) => void
  onCreated: (secret: SecretDetail) => void
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
      <LlmSecretConfigurator
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
    <CompatibleSecretPicker
      engineId={engineId}
      value={value}
      disabled={disabled}
      onChange={onSelect}
      onCreateRequested={() => setView('create')}
    />
  )
}
