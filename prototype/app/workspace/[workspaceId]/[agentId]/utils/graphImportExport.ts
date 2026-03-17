import type { Edge, Node, ReactFlowInstance } from 'reactflow'
import { EdgeData } from '../types/graph'

/**
 * Handle exporting the graph state to a JSON file.
 * Automatically adds sizes to nodes if missing.
 */
export function exportGraphToJson(
    nodes: Node[],
    edges: Edge[],
    rfInstance: ReactFlowInstance | null
): void {
    const viewport = rfInstance?.getViewport() || { x: 0, y: 0, zoom: 1 }

    const nodesWithSizes = nodes.map((node) => {
        const nodeCopy = { ...node }
        if (!nodeCopy.width || nodeCopy.width === 0) {
            nodeCopy.width = 140
        }
        if (!nodeCopy.height || nodeCopy.height === 0) {
            nodeCopy.height = 100
        }
        if (!nodeCopy.positionAbsolute) {
            nodeCopy.positionAbsolute = { ...nodeCopy.position }
        }
        return nodeCopy
    })

    const data = {
        version: '1.0',
        nodes: nodesWithSizes,
        edges,
        viewport,
        exportedAt: new Date().toISOString(),
    }

    const jsonString = JSON.stringify(data, null, 2)
    const blob = new Blob([jsonString], { type: 'application/json' })
    const url = URL.createObjectURL(blob)

    const link = document.createElement('a')
    link.href = url
    link.download = `agent-flow-${new Date().getTime()}.json`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
}

/**
 * Represents the result of parsing an imported graph JSON file.
 */
export interface ImportedGraphData {
    nodes: Node[]
    edges: Edge[]
    viewport: { x: number; y: number; zoom: number } | null
}

/**
 * Handle parsing an imported graph JSON file.
 * Uses a Promise to handle the FileReader async loading.
 */
export async function parseImportedGraph(file: File): Promise<ImportedGraphData> {
    return new Promise<ImportedGraphData>((resolve, reject) => {
        const reader = new FileReader()

        reader.onload = (e) => {
            try {
                const text = e.target?.result
                if (typeof text !== 'string') {
                    throw new Error('Failed to read file')
                }

                const data = JSON.parse(text)

                if (!data.nodes || !Array.isArray(data.nodes)) {
                    throw new Error('Invalid graph format: missing nodes array')
                }
                if (!data.edges || !Array.isArray(data.edges)) {
                    throw new Error('Invalid graph format: missing edges array')
                }

                const nodesWithSizes = data.nodes.map((node: Node) => {
                    const nodeCopy = { ...node }
                    // Add default sizes and positions if missing
                    if (!nodeCopy.width || nodeCopy.width === 0) {
                        nodeCopy.width = 140
                    }
                    if (!nodeCopy.height || nodeCopy.height === 0) {
                        nodeCopy.height = 100
                    }
                    if (!nodeCopy.positionAbsolute) {
                        nodeCopy.positionAbsolute = { ...nodeCopy.position }
                    }
                    if (!nodeCopy.position) {
                        nodeCopy.position = { x: 0, y: 0 }
                        nodeCopy.positionAbsolute = { x: 0, y: 0 }
                    }
                    return nodeCopy
                })

                const viewport = data.viewport || null

                resolve({
                    nodes: nodesWithSizes,
                    edges: data.edges,
                    viewport,
                })
            } catch (error: unknown) {
                const message = error instanceof Error ? error.message : 'Failed to parse graph file'
                reject(new Error(message))
            }
        }

        reader.onerror = () => {
            reject(new Error('Failed to read file'))
        }

        reader.readAsText(file)
    })
}
