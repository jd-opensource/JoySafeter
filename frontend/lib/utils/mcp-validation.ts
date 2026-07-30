export interface NamedMcpServer {
  name: string
}

export function validateUniqueMcpServerName(
  name: string | undefined | null,
  existingServers: NamedMcpServer[],
): string | null {
  const trimmedName = name?.trim()
  if (!trimmedName) return null

  const duplicate = existingServers.some((server) => server.name.trim() === trimmedName)
  if (!duplicate) return null

  return `Duplicate MCP server name: ${trimmedName}`
}
