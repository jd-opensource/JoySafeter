'use client'

import { useMemo } from 'react'

import type { Mission, MissionStatus } from '@/types/missions'
import { MISSION_STATUS_ORDER } from '@/types/missions'

import { MissionColumn } from './mission-column'

interface MissionBoardProps {
  missions: Mission[]
}

export function MissionBoard({ missions }: MissionBoardProps) {
  const grouped = useMemo(() => {
    const map: Record<MissionStatus, Mission[]> = {
      backlog: [],
      todo: [],
      in_progress: [],
      in_review: [],
      done: [],
      blocked: [],
      cancelled: [],
    }
    for (const m of missions) {
      if (map[m.status]) {
        map[m.status].push(m)
      }
    }
    // Sort within each column by position
    for (const key of Object.keys(map) as MissionStatus[]) {
      map[key].sort((a, b) => a.position - b.position)
    }
    return map
  }, [missions])

  return (
    <div className="flex h-full gap-3 overflow-x-auto p-4">
      {MISSION_STATUS_ORDER.map((status) => (
        <MissionColumn key={status} status={status} missions={grouped[status]} />
      ))}
    </div>
  )
}
