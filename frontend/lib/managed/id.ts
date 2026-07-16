export function stripIdPrefix(id: string): string {
  let value = id
  let next = value.replace(
    /^(agent_|sched_|task_|sess_|env_|vault_|vlt_|cred_|mst_|evt_|thread_|memstore_|mem_|file_|skill_|secret_)/,
    '',
  )
  while (next !== value) {
    value = next
    next = value.replace(
      /^(agent_|sched_|task_|sess_|env_|vault_|vlt_|cred_|mst_|evt_|thread_|memstore_|mem_|file_|skill_|secret_)/,
      '',
    )
  }
  return value
}

export function withIdPrefix(id: string, prefix: string): string {
  return `${prefix}${stripIdPrefix(id)}`
}

export function shortIdWithPrefix(id: string, prefix: string, length = 8): string {
  return `${prefix}${stripIdPrefix(id).slice(0, length)}`
}
