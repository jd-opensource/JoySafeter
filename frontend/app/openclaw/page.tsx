'use client'

import { useCallback, useState } from 'react'

import { TaskList } from './components/TaskList'
import { TaskOutputViewer } from './components/TaskOutputViewer'
import { TaskSubmitForm } from './components/TaskSubmitForm'
import { WorkerGrid } from './components/WorkerGrid'

export default function OpenClawPage() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleTaskSubmitted = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  return (
    <div className="flex h-full flex-col gap-6 overflow-auto p-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
          OpenClaw Workers
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          Manage distributed OpenClaw worker instances and submit tasks.
        </p>
      </div>

      <WorkerGrid />

      <div className="grid flex-1 grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-6">
          <TaskSubmitForm onSubmitted={handleTaskSubmitted} />
          <TaskList
            refreshKey={refreshKey}
            selectedTaskId={selectedTaskId}
            onSelectTask={setSelectedTaskId}
          />
        </div>

        <TaskOutputViewer taskId={selectedTaskId} />
      </div>
    </div>
  )
}
