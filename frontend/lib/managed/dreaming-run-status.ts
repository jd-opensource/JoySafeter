const DREAMING_ACTIVE_RUN_STATUSES = new Set(['pending', 'scheduling', 'rescheduling', 'running'])
const DREAMING_TERMINAL_RUN_STATUSES = new Set(['success', 'failed', 'dead_letter', 'crashed'])

export function isDreamingRunActive(status: string | null | undefined): boolean {
  return DREAMING_ACTIVE_RUN_STATUSES.has(status || '')
}

export function isDreamingRunTerminal(status: string | null | undefined): boolean {
  return DREAMING_TERMINAL_RUN_STATUSES.has(status || '')
}

export function dreamingRunPollInterval(status: string | null | undefined): 2000 | false {
  return isDreamingRunActive(status) ? 2000 : false
}

export function dreamingButtonLabelForStatus(
  status: string | null | undefined,
  mutationPending: boolean,
): 'Dreaming run...' | 'Dreaming Complete' | 'Dreaming' {
  if (mutationPending || isDreamingRunActive(status)) {
    return 'Dreaming run...'
  }
  if (status === 'success') {
    return 'Dreaming Complete'
  }
  return 'Dreaming'
}
