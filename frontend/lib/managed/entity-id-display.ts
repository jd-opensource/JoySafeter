import {
  ENTITY_ID_PREFIXES,
  parseEntityId,
  type EntityId,
  type EntityKind,
  type EventId,
} from '@/types/entity-id'

function entityIdUuid<Kind extends EntityKind>(
  id: EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]>,
  kind: Kind,
): string {
  const parsed = parseEntityId(id, kind)
  return parsed.slice(ENTITY_ID_PREFIXES[kind].length)
}

export function shortEntityId<Kind extends EntityKind>(
  id: EntityId<(typeof ENTITY_ID_PREFIXES)[Kind]>,
  kind: Kind,
  length = 8,
): string {
  return `${ENTITY_ID_PREFIXES[kind]}${entityIdUuid(id, kind).slice(0, length)}`
}

export function eventIdTimestamp(eventId: EventId): number | null {
  const hex = entityIdUuid(eventId, 'event').replace(/-/g, '')
  if (hex.length < 12) return null
  const timestamp = Number.parseInt(hex.slice(0, 12), 16)
  return timestamp > 1_000_000_000_000 && timestamp < 2_000_000_000_000 ? timestamp : null
}
