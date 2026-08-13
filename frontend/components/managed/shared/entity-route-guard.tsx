'use client'

import React, { type ComponentType } from 'react'
import { useRouter } from 'next/navigation'

import { isEntityId, type EntityKind } from '@/types/entity-id'

import { ResourceErrorState, type ManagedResourceKind } from './resource-error-state'

// Kinds that are both a parseable entity id and a ResourceErrorState resource.
type GuardableKind = EntityKind & ManagedResourceKind

interface EntityRouteGuardOptions<Params> {
  kind: GuardableKind
  paramKey: keyof Params & string
  backTo: string
  // Optional entity-id kind used to validate the route param when it differs
  // from the resource `kind` (e.g. the `secret`/`vault` pages now carry
  // unified `credential`/`credentialGroup` ids but keep their resource copy).
  idKind?: EntityKind
}

// Wraps a detail-page component so an invalid `[id]` route param renders a
// localized not-found state instead of throwing when the param is parsed.
// The guard early-returns before Inner mounts, so Inner's hooks stay
// unconditional (Rules of Hooks) without each page repeating the boilerplate.
export function withEntityRouteGuard<Params extends Record<string, string>>(
  Inner: ComponentType<{ params: Promise<Params> }>,
  { kind, paramKey, backTo, idKind }: EntityRouteGuardOptions<Params>,
): ComponentType<{ params: Promise<Params> }> {
  function EntityRouteGuard({ params }: { params: Promise<Params> }) {
    const router = useRouter()
    const rawId = React.use(params)[paramKey]
    if (!isEntityId(rawId, idKind ?? kind)) {
      return <ResourceErrorState resource={kind} reason="notFound" onBack={() => router.push(backTo)} />
    }
    return <Inner params={params} />
  }
  return EntityRouteGuard
}
