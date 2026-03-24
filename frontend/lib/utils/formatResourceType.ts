export const formatResourceType = (type?: string | null): string => {
  if (!type) return 'Unknown'
  return type.charAt(0).toUpperCase() + type.slice(1)
}
