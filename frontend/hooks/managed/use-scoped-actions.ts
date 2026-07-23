import { useEffect, useRef } from 'react'

import {
  managedScopeKey,
  useManagedRequestScope,
  type ManagedRequestScope,
} from '@/lib/managed/request-scope'
import { useProjectStore } from '@/stores/managed/project-store'

import { currentProjectAllowsWrite, useCurrentProjectReadOnly } from './use-current-project-read-only'

export interface UseScopedActionsOptions {
  /**
   * Called whenever the active scope changes or the project turns read-only —
   * pages use this to close open dialogs / clear pending targets. The action
   * run-id is already bumped before this fires, so any in-flight async action
   * will fail its `isCurrentAction` check.
   */
  onReset?: () => void
}

export interface ScopedActions {
  /** Ref tracking the scope key this component last rendered under. */
  scopeRef: React.MutableRefObject<string>
  /** Ref tracking the full request scope (org+project) for API calls. */
  requestScopeRef: React.MutableRefObject<ManagedRequestScope>
  /** The current request scope (reactive; from `useManagedRequestScope`). */
  scope: ManagedRequestScope
  /** Whether the current project is read-only (reactive). */
  readOnly: boolean
  /**
   * Begin a new user-initiated action. Returns the run-id + scope snapshot to
   * validate the async result against later, or `null` when the project is
   * read-only or the scope is already inactive (caller should abort).
   */
  beginAction: () => { runId: number; scope: string; requestScope: ManagedRequestScope } | null
  /**
   * True when `runId`+`scope` still describe the current action AND the scope
   * is active AND the project allows writes. Guards the tail of an async
   * mutation before it commits UI/state changes.
   */
  isCurrentAction: (runId: number, scope: string) => boolean
  /** True when `scope` is still the live scope (org/project unchanged). */
  scopeIsActive: (scope?: string) => boolean
  /** Bump the run counter without starting a new action (e.g. on dialog close). */
  bumpRun: () => void
}

/**
 * Scope-guard / stale-run orchestration shared by every managed resource page.
 *
 * Consolidates the identical `managedScopeRef` + `actionRunRef` +
 * `getCurrentManagedScope` / `currentManagedScopeIsActive` / `isCurrentAction`
 * trio and the three lifecycle effects (scope-change reset, unmount cleanup,
 * read-only reset) that were copy-pasted across ~17 pages and create dialogs.
 *
 * Pages layer their resource-specific "is this row still in the active list"
 * checks on top of `scopeIsActive` / `isCurrentAction`.
 */
export function useScopedActions(options: UseScopedActionsOptions = {}): ScopedActions {
  const { onReset } = options
  const scope = useManagedRequestScope()
  const readOnly = useCurrentProjectReadOnly()

  const scopeRef = useRef(scope.key)
  const requestScopeRef = useRef<ManagedRequestScope>(scope)
  const actionRunRef = useRef(0)

  // Keep the latest onReset without re-arming the effects each render.
  const onResetRef = useRef(onReset)
  onResetRef.current = onReset

  const getCurrentManagedScope = () => {
    const { currentOrgId, currentProjectId } = useProjectStore.getState()
    return managedScopeKey(currentOrgId, currentProjectId)
  }

  const scopeIsActive = (scope: string = scopeRef.current) =>
    scopeRef.current === scope && getCurrentManagedScope() === scope

  const isCurrentAction = (runId: number, scope: string) =>
    actionRunRef.current === runId && scopeIsActive(scope) && currentProjectAllowsWrite()

  const bumpRun = () => {
    actionRunRef.current += 1
  }

  const beginAction = () => {
    if (!currentProjectAllowsWrite()) return null
    if (!scopeIsActive(scopeRef.current)) return null
    actionRunRef.current += 1
    return {
      runId: actionRunRef.current,
      scope: scopeRef.current,
      requestScope: requestScopeRef.current,
    }
  }

  // Scope changed → invalidate in-flight actions and let the page reset UI.
  useEffect(() => {
    if (scopeRef.current !== scope.key) {
      actionRunRef.current += 1
      onResetRef.current?.()
    }
    scopeRef.current = scope.key
    requestScopeRef.current = scope
  }, [scope.key, scope])

  // Unmount → invalidate any in-flight action so its tail no-ops.
  useEffect(
    () => () => {
      actionRunRef.current += 1
    },
    [],
  )

  // Project turned read-only → invalidate + reset UI.
  useEffect(() => {
    if (readOnly) {
      actionRunRef.current += 1
      onResetRef.current?.()
    }
  }, [readOnly])

  return {
    scopeRef,
    requestScopeRef,
    scope,
    readOnly,
    beginAction,
    isCurrentAction,
    scopeIsActive,
    bumpRun,
  }
}
