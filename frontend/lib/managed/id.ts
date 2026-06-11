export function stripIdPrefix(id: string): string {
  return id.replace(/^(agent_|sess_|env_|vault_|vlt_|cred_|mst_|evt_|thread_|memstore_|mem_|file_|skill_|secret_)/, '')
}
