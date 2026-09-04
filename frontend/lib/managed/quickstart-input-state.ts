import type { CredentialId } from '@/types/entity-id'

import { QUICKSTART_STEP, type QuickstartStepId } from './quickstart-flow'

interface QuickstartInputPlaceholderOptions {
  selectedEngine: string
  modelCredentialId: CredentialId | ''
  currentStep: QuickstartStepId
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
  if (!selectedEngine && currentStep > QUICKSTART_STEP.ENGINE) {
    return 'managed.quickstart.selectEngineFirst'
  }
  if (currentStep === QUICKSTART_STEP.ENGINE) return readyKey
  if (currentStep === QUICKSTART_STEP.MODEL_CONNECTION) {
    return 'managed.quickstart.chooseModelConnection'
  }
  if (!modelCredentialId) return 'managed.quickstart.noApiKey'
  if (currentStep >= QUICKSTART_STEP.AGENT && !selectedCredentialCompatible) {
    return 'managed.quickstart.noCompatibleModelConnection'
  }
  return readyKey
}
