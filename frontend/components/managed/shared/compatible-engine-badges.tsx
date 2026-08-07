import { Badge } from '@/components/ui/badge'
import type { LlmCatalog } from '@/types/llm'

export function CompatibleEngineBadges({
  engineIds,
  catalog,
}: {
  engineIds: string[]
  catalog?: LlmCatalog | null
}) {
  if (engineIds.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {engineIds.map((engineId) => (
        <Badge key={engineId} variant="outline">
          {catalog?.engines.find((engine) => engine.id === engineId)?.display_name ?? engineId}
        </Badge>
      ))}
    </div>
  )
}
