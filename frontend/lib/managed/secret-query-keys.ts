export function secretDetailQueryKey(scopeKey: string, secretId: string, catalogVersion: string) {
  return ['secret', scopeKey, secretId, catalogVersion] as const
}
