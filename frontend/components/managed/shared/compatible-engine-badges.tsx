import { Badge } from '@/components/ui/badge'

const ENGINE_LABELS: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  native: 'Native',
  pi: 'Pi',
}

export function CompatibleEngineBadges({ engineIds }: { engineIds: string[] }) {
  if (engineIds.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {engineIds.map((engineId) => (
        <Badge key={engineId} variant="outline">
          {ENGINE_LABELS[engineId] ?? engineId}
        </Badge>
      ))}
    </div>
  )
}
