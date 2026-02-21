/**
 * onConnect sub-functions — extracted from builderStore for readability.
 *
 * Contains the edge-type/route-key determination logic and auto-wiring
 * logic that were previously inlined in the 133-line onConnect handler.
 */
import type { Edge, Node } from 'reactflow'
import type { EdgeData, RouteRule } from '../types/graph'
import { nodeRegistry } from '../services/nodeRegistry'

/** Conditional source node types that trigger route_key suggestions */
const CONDITIONAL_SOURCE_TYPES = ['router_node', 'condition', 'loop_condition_node']

interface EdgeTypeResult {
    edgeType: EdgeData['edge_type']
    routeKey: string | undefined
}

/**
 * Determine the edge type and default route_key for a new connection.
 *
 * Logic:
 * - router_node → suggest first unmatched route
 * - condition → suggest 'true' then 'false'
 * - loop_condition_node → suggest 'continue_loop' then 'exit_loop',
 *   detect loop_back when target precedes source
 */
export function determineEdgeTypeAndRouteKey(
    sourceId: string,
    targetId: string,
    nodes: Node[],
    edges: Edge[],
): EdgeTypeResult {
    const sourceNode = nodes.find((n) => n.id === sourceId)
    const sourceType = (sourceNode?.data as { type?: string })?.type || ''
    const isConditional = CONDITIONAL_SOURCE_TYPES.includes(sourceType)

    let edgeType: EdgeData['edge_type'] = isConditional ? 'conditional' : 'normal'
    let routeKey: string | undefined = undefined

    if (!isConditional) {
        return { edgeType, routeKey }
    }

    if (sourceType === 'router_node') {
        const config = (sourceNode?.data as { config?: { routes?: RouteRule[] } })?.config
        const routes = config?.routes || []
        const existingKeys = new Set(
            edges
                .filter((e) => e.source === sourceId)
                .map((e) => ((e.data || {}) as EdgeData).route_key)
                .filter(Boolean),
        )
        const available = routes.find((r) => !existingKeys.has(r.targetEdgeKey))
        if (available) routeKey = available.targetEdgeKey
    } else if (sourceType === 'condition') {
        const hasTrueEdge = edges.some(
            (e) =>
                e.source === sourceId &&
                ((e.data || {}) as EdgeData).route_key === 'true',
        )
        routeKey = hasTrueEdge ? 'false' : 'true'
    } else if (sourceType === 'loop_condition_node') {
        const hasContinue = edges.some(
            (e) =>
                e.source === sourceId &&
                ((e.data || {}) as EdgeData).route_key === 'continue_loop',
        )
        routeKey = hasContinue ? 'exit_loop' : 'continue_loop'

        // Detect loop_back
        if (routeKey === 'continue_loop') {
            if (sourceId === targetId) {
                edgeType = 'loop_back'
            } else {
                const targetNode = nodes.find((n) => n.id === targetId)
                if (sourceNode && targetNode && targetNode.position.x < sourceNode.position.x) {
                    edgeType = 'loop_back'
                }
            }
        }
    }

    return { edgeType, routeKey }
}

/**
 * Auto-wire: map source node's output to target node's input if the target
 * node has a config property that looks like a state mapping array.
 */
export function autoWireConnection(
    sourceId: string,
    targetId: string,
    nodes: Node[],
    updateNodeConfig: (nodeId: string, config: Record<string, unknown>) => void,
): void {
    const sourceNode = nodes.find((n) => n.id === sourceId)
    const targetNode = nodes.find((n) => n.id === targetId)
    if (!sourceNode || !targetNode) return

    const targetType = (targetNode?.data as { type?: string })?.type
    const nodeDef = nodeRegistry.get(targetType || '')
    if (!nodeDef?.defaultConfig) return

    const configRecord = nodeDef.defaultConfig as Record<string, unknown>
    const mapperPropKey = Object.keys(configRecord).find(
        (key) =>
            Array.isArray(configRecord[key]) ||
            key.includes('mapping') ||
            key.includes('dependencies'),
    )
    if (!mapperPropKey) return

    const currentConfig = (targetNode.data as any).config || {}
    const mapperValue = currentConfig[mapperPropKey] || []
    const sourceRefStr = `{${sourceId}.output}`

    if (!mapperValue.includes(sourceRefStr)) {
        updateNodeConfig(targetId, {
            [mapperPropKey]: [...mapperValue, sourceRefStr],
        })
    }
}
