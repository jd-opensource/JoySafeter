'use client'

/**
 * Workspace API Keys Management Page
 */

import { Key } from 'lucide-react'
import { useParams } from 'next/navigation'

import { ApiKeysTable } from '@/components/api-keys/ApiKeysTable'
import { useSidebarStore } from '@/stores/sidebar/store'

export default function WorkspaceApiKeysPage() {
  const params = useParams()
  const workspaceId = params?.workspaceId as string
  const isSidebarCollapsed = useSidebarStore((state) => state.isCollapsed)

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div
        className="flex-shrink-0 border-b border-gray-200 bg-white px-6 py-4 transition-all duration-300"
        style={{ marginLeft: isSidebarCollapsed ? '280px' : '0px' }}
      >
        <div className="flex items-center gap-3">
          <Key className="h-6 w-6 text-gray-700" />
          <h1 className="text-base font-semibold text-gray-900">API Keys</h1>
        </div>
      </div>

      {/* Content */}
      <div
        className="flex-1 overflow-y-auto p-6 transition-all duration-300"
        style={{ marginLeft: isSidebarCollapsed ? '280px' : '0px' }}
      >
        <ApiKeysTable workspaceId={workspaceId} />

        {/* Usage hint */}
        <div className="mt-6 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <h4 className="mb-2 text-xs font-semibold text-gray-700">使用说明</h4>
          <p className="mb-2 text-xs text-gray-500">
            在 HTTP 请求头中添加 API Key 即可调用 OpenAPI 端点：
          </p>
          <code className="block rounded border border-gray-200 bg-white px-3 py-2 font-mono text-xs text-gray-700">
            Authorization: Bearer YOUR_API_KEY
          </code>
          <p className="mt-2 text-xs text-gray-400">
            可用端点：POST /api/v1/openapi/graph/&#123;graphId&#125;/run · GET .../status · POST
            .../abort · GET .../result
          </p>
        </div>
      </div>
    </div>
  )
}
