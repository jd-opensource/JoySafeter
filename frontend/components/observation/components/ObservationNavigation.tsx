'use client'

import { useObservationSelection } from '../contexts/ObservationSelectionContext'
import { ObservationTree } from './ObservationTree'
import { ObservationTimeline } from './ObservationTimeline'
import { ObservationSearchList } from './ObservationSearchList'

export function ObservationNavigation() {
  const { searchQuery, viewMode } = useObservationSelection()

  const hasQuery = searchQuery.trim().length > 0

  if (hasQuery) return <ObservationSearchList />
  if (viewMode === 'timeline') return <ObservationTimeline />
  return <ObservationTree />
}
