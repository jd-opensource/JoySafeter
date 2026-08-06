export function stripIdPrefix(id: string): string {
  let value = id
  let next = value.replace(
    /^(agent_|trig_|task_|sess_|env_|vault_|cred_|evt_|memstore_|mem_|file_|skill_|sklver_|sklfile_|secret_)/,
    '',
  )
  while (next !== value) {
    value = next
    next = value.replace(
      /^(agent_|trig_|task_|sess_|env_|vault_|cred_|evt_|memstore_|mem_|file_|skill_|sklver_|sklfile_|secret_)/,
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
