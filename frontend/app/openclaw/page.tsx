'use client'

import { useCallback, useState } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { DeviceManager } from './components/DeviceManager'
import { InstanceManager } from './components/InstanceManager'
import { OpenClawChat } from './components/OpenClawChat'
import { OpenClawWebUI } from './components/OpenClawWebUI'
import { TaskList } from './components/TaskList'
import { TaskOutputViewer } from './components/TaskOutputViewer'
import { TaskSubmitForm } from './components/TaskSubmitForm'

export default function OpenClawPage() {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleTaskSubmitted = useCallback(() => {
    setRefreshKey((k) => k + 1)
  }, [])

  return (
    <div className="flex h-full flex-col overflow-hidden p-6">
      <div className="mb-4">
        <h1 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
          OpenClaw
        </h1>
        <p className="mt-1 text-sm text-[var(--text-secondary)]">
          管理你的 OpenClaw 实例，通过 Chat 对话或原生 Web UI 与 Agent 交互。
        </p>
      </div>

      <Tabs defaultValue="dashboard" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="w-fit">
          <TabsTrigger value="dashboard">Dashboard</TabsTrigger>
          <TabsTrigger value="chat">Chat</TabsTrigger>
          <TabsTrigger value="webui">WebUI</TabsTrigger>
        </TabsList>

        <TabsContent value="dashboard" className="flex-1 overflow-auto">
          <div className="flex flex-col gap-6 py-2">
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <InstanceManager />
              <DeviceManager />
            </div>

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
        </TabsContent>

        <TabsContent value="chat" className="flex-1 overflow-hidden">
          <div className="h-full py-2">
            <OpenClawChat />
          </div>
        </TabsContent>

        <TabsContent value="webui" className="flex-1 overflow-hidden">
          <div className="h-full py-2">
            <OpenClawWebUI />
          </div>
        </TabsContent>
      </Tabs>
    </div>
  )
}
