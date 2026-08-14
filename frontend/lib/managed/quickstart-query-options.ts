export function quickstartQueryOptions<TOptions extends object>(options: TOptions) {
  return {
    ...options,
    refetchOnMount: 'always' as const,
  }
}
