'use client'

export function MonoId({ id, truncate = true }: { id: string; truncate?: boolean }) {
  const display = truncate && id.length > 16 ? `${id.slice(0, 12)}...${id.slice(-4)}` : id

  return (
    <span className="font-mono text-xs text-muted-foreground" title={id}>
      {display}
    </span>
  )
}
