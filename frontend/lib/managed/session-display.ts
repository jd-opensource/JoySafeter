export function getSessionDisplayTitle(title: string | null | undefined, fallback: string): string {
  return title?.trim() || fallback
}
