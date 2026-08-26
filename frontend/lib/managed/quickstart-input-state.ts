import type { CredentialId } from '@/types/entity-id'

interface QuickstartInputPlaceholderOptions {
  selectedEngine: string
  modelCredentialId: CredentialId | ''
  currentStep: number
  selectedCredentialCompatible: boolean
  isSessionRunning: boolean
  isStreaming: boolean
  readyKey: string
}

export function quickstartInputPlaceholderKey({
  selectedEngine,
  modelCredentialId,
  currentStep,
  selectedCredentialCompatible,
  isSessionRunning,
  isStreaming,
  readyKey,
}: QuickstartInputPlaceholderOptions): string {
  if (isSessionRunning) return 'managed.quickstart.agentProcessing'
  if (isStreaming) return 'managed.quickstart.waitingForResponse'
  if (!selectedEngine && currentStep > 1) return 'managed.quickstart.selectEngineFirst'
  if (currentStep === 1) return readyKey
  if (currentStep === 2) return 'managed.quickstart.chooseModelConnection'
  if (!modelCredentialId) return 'managed.quickstart.noApiKey'
  if (currentStep >= 3 && !selectedCredentialCompatible) {
    return 'managed.quickstart.noCompatibleModelConnection'
  }
  return readyKey
}
