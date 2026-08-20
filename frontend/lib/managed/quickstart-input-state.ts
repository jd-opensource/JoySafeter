interface QuickstartInputPlaceholderOptions {
  selectedEngine: string
  secretRef: string
  currentStep: number
  selectedSecretCompatible: boolean
  isSessionRunning: boolean
  isStreaming: boolean
  readyKey: string
}

export function quickstartInputPlaceholderKey({
  selectedEngine,
  secretRef,
  currentStep,
  selectedSecretCompatible,
  isSessionRunning,
  isStreaming,
  readyKey,
}: QuickstartInputPlaceholderOptions): string {
  if (isSessionRunning) return 'managed.quickstart.agentProcessing'
  if (isStreaming) return 'managed.quickstart.waitingForResponse'
  if (!selectedEngine && currentStep > 1) return 'managed.quickstart.selectEngineFirst'
  if (currentStep === 1) return readyKey
  if (currentStep === 2) return 'managed.quickstart.chooseSecret'
  if (!secretRef) return 'managed.quickstart.noApiKey'
  if (currentStep >= 3 && !selectedSecretCompatible) {
    return 'managed.quickstart.noCompatibleSecret'
  }
  return readyKey
}
