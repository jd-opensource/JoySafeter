export function resolveSecretsRedirect(create: string | null): string {
  if (create === 'llm') return '/managed/credentials?tab=models&create=model'
  if (create === 'generic' || create === 'custom')
    return '/managed/credentials?tab=services&create=service'
  return '/managed/credentials?tab=models'
}

export function resolveVaultsRedirect(create: string | null): string {
  if (create === '1') return '/managed/credentials?tab=mcp&create=vault'
  return '/managed/credentials?tab=mcp'
}
