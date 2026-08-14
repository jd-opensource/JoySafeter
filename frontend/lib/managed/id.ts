import {
  ENTITY_ID_PREFIXES,
  parseEntityId,
  type EntityId,
  type EntityKind,
} from '@/types/entity-id'

export function entityIdUuid<Kind extends EntityKind>(
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
