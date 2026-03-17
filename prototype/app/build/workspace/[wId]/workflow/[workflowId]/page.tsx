'use client'

import { motion, AnimatePresence } from 'framer-motion'
import {
  Play,
  Trash2,
  GripVertical,
  Code,
  Globe,
  Database,
  GitBranch,
  Variable,
  Repeat,
  Sparkles,
  CircleDot,
  Square,
  ChevronRight,
  X,
  CheckCircle2,
  Clock,
  Zap,
} from 'lucide-react'
import { useCallback, useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import ReactFlow, {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  Handle,
  Position,
} from 'reactflow'
import 'reactflow/dist/style.css'

import { cn } from '@/lib/core/utils/cn'
import {
  workflowNodePalette,
  defaultWorkflowNodes,
  defaultWorkflowEdges,
  type WorkflowNodeType,
} from '@/mocks/workflows'

const EASE = [0.32, 0.72, 0, 1] as [number, number, number, number]

const nodeTypeIcons: Record<
  WorkflowNodeType,
  React.ComponentType<{ className?: string; style?: React.CSSProperties }>
> = {
  start: CircleDot,
  end: Square,
  llm: Sparkles,
  code: Code,
  http: Globe,
  knowledge_retrieval: Database,
  condition: GitBranch,
  variable: Variable,
  iterator: Repeat,
}

const nodeTypeColors: Record<
  WorkflowNodeType,
  { color: string; glow: string; bg: string; border: string }
> = {
  start:               { color: '#34d399', glow: 'rgba(52,211,153,0.25)',  bg: 'rgba(52,211,153,0.08)',  border: 'rgba(52,211,153,0.3)' },
  end:                 { color: '#f87171', glow: 'rgba(248,113,113,0.25)', bg: 'rgba(248,113,113,0.08)', border: 'rgba(248,113,113,0.3)' },
  llm:                 { color: '#a78bfa', glow: 'rgba(167,139,250,0.25)', bg: 'rgba(167,139,250,0.08)', border: 'rgba(167,139,250,0.3)' },
  code:                { color: '#fbbf24', glow: 'rgba(251,191,36,0.25)',  bg: 'rgba(251,191,36,0.08)',  border: 'rgba(251,191,36,0.3)' },
  http:                { color: '#60a5fa', glow: 'rgba(96,165,250,0.25)',  bg: 'rgba(96,165,250,0.08)',  border: 'rgba(96,165,250,0.3)' },
  knowledge_retrieval: { color: '#22d3ee', glow: 'rgba(34,211,238,0.25)',  bg: 'rgba(34,211,238,0.08)',  border: 'rgba(34,211,238,0.3)' },
  condition:           { color: '#f472b6', glow: 'rgba(244,114,182,0.25)', bg: 'rgba(244,114,182,0.08)', border: 'rgba(244,114,182,0.3)' },
  variable:            { color: '#94a3b8', glow: 'rgba(148,163,184,0.25)', bg: 'rgba(148,163,184,0.08)', border: 'rgba(148,163,184,0.3)' },
  iterator:            { color: '#fb923c', glow: 'rgba(251,146,60,0.25)',  bg: 'rgba(251,146,60,0.08)',  border: 'rgba(251,146,60,0.3)' },
}

function WorkflowNode({
  data,
  selected,
}: {
  data: { label: string; type: WorkflowNodeType; description?: string }
  selected?: boolean
}) {
  const Icon = nodeTypeIcons[data.type] || CircleDot
  const { color, glow, bg, border } = nodeTypeColors[data.type] || nodeTypeColors.variable

  return (
    <div
      className="relative rounded-xl min-w-[172px]"
      style={{
        background: 'rgba(13,13,20,0.9)',
        border: `1px solid ${selected ? color : border}`,
        boxShadow: selected
          ? `0 0 0 2px ${color}30, 0 0 24px ${glow}, 0 4px 24px rgba(0,0,0,0.5)`
          : `0 0 14px ${glow}, 0 4px 16px rgba(0,0,0,0.4)`,
        backdropFilter: 'blur(12px)',
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{
          width: 10,
          height: 10,
          background: color,
          border: '2px solid rgba(13,13,20,0.9)',
          boxShadow: `0 0 6px ${glow}`,
        }}
      />

      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2.5 rounded-t-xl"
        style={{ borderBottom: `1px solid ${border}`, background: bg }}
      >
        <div
          className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-lg"
          style={{ background: bg, border: `1px solid ${border}` }}
        >
          <Icon className="h-3.5 w-3.5" style={{ color }} />
        </div>
        <span className="text-xs font-semibold text-white/90 truncate">{data.label}</span>
      </div>

      {/* Body */}
      {data.description && (
        <div className="px-3 py-2">
          <p className="text-[10px] text-white/40 leading-relaxed">{data.description}</p>
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        style={{
          width: 10,
          height: 10,
          background: color,
          border: '2px solid rgba(13,13,20,0.9)',
          boxShadow: `0 0 6px ${glow}`,
        }}
      />
    </div>
  )
}

const nodeTypes = { workflowNode: WorkflowNode }

const inputCls =
  'w-full rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/80 placeholder:text-white/25 outline-none focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/20 transition-all'
const labelCls = 'block text-[10px] font-medium text-white/40 mb-1 uppercase tracking-wider'

function NodeConfigFields({ node }: { node: Node }) {
  const type = node.data.type as WorkflowNodeType

  if (type === 'llm') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Model</label>
          <select className={inputCls} defaultValue="claude-3-5-sonnet">
            <option value="gpt-4o">GPT-4o</option>
            <option value="claude-3-5-sonnet">Claude 3.5 Sonnet</option>
            <option value="deepseek-v3">DeepSeek V3</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>System Prompt</label>
          <textarea
            className={cn(inputCls, 'h-24 resize-none')}
            defaultValue="You are a security analyst. Analyze the input and classify the threat level."
          />
        </div>
        <div>
          <label className={labelCls}>Temperature</label>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            defaultValue="0.7"
            className="w-full accent-violet-500"
          />
          <div className="flex justify-between text-[9px] text-white/25 mt-0.5">
            <span>0</span><span>0.7</span><span>2</span>
          </div>
        </div>
      </div>
    )
  }

  if (type === 'code') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Language</label>
          <select className={inputCls} defaultValue="python">
            <option value="python">Python</option>
            <option value="javascript">JavaScript</option>
            <option value="bash">Bash</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Code</label>
          <textarea
            className={cn(inputCls, 'h-28 resize-none font-mono text-[10px]')}
            defaultValue={`def main(inputs):\n    # Process inputs\n    return {"result": inputs}`}
          />
        </div>
      </div>
    )
  }

  if (type === 'http') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Method</label>
          <select className={inputCls} defaultValue="GET">
            <option>GET</option>
            <option>POST</option>
            <option>PUT</option>
            <option>DELETE</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>URL</label>
          <input type="text" className={inputCls} placeholder="https://api.example.com/endpoint" />
        </div>
        <div>
          <label className={labelCls}>Headers (JSON)</label>
          <textarea
            className={cn(inputCls, 'h-20 resize-none font-mono text-[10px]')}
            defaultValue={`{\n  "Authorization": "Bearer {{token}}"\n}`}
          />
        </div>
      </div>
    )
  }

  if (type === 'knowledge_retrieval') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Dataset</label>
          <select className={inputCls} defaultValue="ds-001">
            <option value="ds-001">CVE Database 2025</option>
            <option value="ds-002">MITRE ATT&CK v15</option>
            <option value="ds-003">Threat Intelligence Feed</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>Query</label>
          <input type="text" className={inputCls} placeholder="{{input.threat_indicator}}" />
        </div>
        <div>
          <label className={labelCls}>Top-K Results</label>
          <input type="number" className={inputCls} defaultValue={5} min={1} max={20} />
        </div>
      </div>
    )
  }

  if (type === 'condition') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Condition Expression</label>
          <input
            type="text"
            className={inputCls}
            placeholder="{{llm.output.threat_level}} == 'high'"
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className={labelCls}>True Branch</label>
            <input type="text" className={inputCls} defaultValue="Yes" />
          </div>
          <div>
            <label className={labelCls}>False Branch</label>
            <input type="text" className={inputCls} defaultValue="No" />
          </div>
        </div>
      </div>
    )
  }

  if (type === 'variable') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Variable Name</label>
          <input type="text" className={inputCls} placeholder="my_variable" />
        </div>
        <div>
          <label className={labelCls}>Value / Expression</label>
          <input type="text" className={inputCls} placeholder="{{previous.output}}" />
        </div>
      </div>
    )
  }

  if (type === 'iterator') {
    return (
      <div className="space-y-3">
        <div>
          <label className={labelCls}>Items Expression</label>
          <input type="text" className={inputCls} placeholder="{{knowledge.results}}" />
        </div>
        <div>
          <label className={labelCls}>Iterator Variable</label>
          <input type="text" className={inputCls} defaultValue="item" />
        </div>
        <div>
          <label className={labelCls}>Max Iterations</label>
          <input type="number" className={inputCls} defaultValue={10} min={1} max={100} />
        </div>
      </div>
    )
  }

  return null
}

const MOCK_RUN_STEPS = [
  { node: 'Start', time: '0ms' },
  { node: 'Analyze Threat', time: '1.2s' },
  { node: 'Is Threat?', time: '5ms' },
  { node: 'Lookup CVE', time: '800ms' },
  { node: 'End', time: '0ms' },
]

export default function WorkflowBuilderPage() {
  const { t } = useTranslation()
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [nodes, setNodes, onNodesChange] = useNodesState(defaultWorkflowNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultWorkflowEdges)
  const [selectedNode, setSelectedNode] = useState<Node | null>(null)
  const [showResults, setShowResults] = useState(false)
  const [isRunning, setIsRunning] = useState(false)

  const onConnect = useCallback(
    (params: Connection) =>
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            animated: false,
            style: { stroke: 'rgba(139,92,246,0.5)', strokeWidth: 1.5 },
          },
          eds,
        ),
      ),
    [setEdges],
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node)
  }, [])

  const onPaneClick = useCallback(() => {
    setSelectedNode(null)
  }, [])

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault()
      const type = event.dataTransfer.getData(
        'application/workflow-node-type',
      ) as WorkflowNodeType
      const label = event.dataTransfer.getData('application/workflow-node-label')
      if (!type) return

      const bounds = reactFlowWrapper.current?.getBoundingClientRect()
      if (!bounds) return

      setNodes((nds) => [
        ...nds,
        {
          id: `${type}-${Date.now()}`,
          type: 'workflowNode',
          position: { x: event.clientX - bounds.left - 86, y: event.clientY - bounds.top - 20 },
          data: { label: label || type, type, description: '' },
        },
      ])
    },
    [setNodes],
  )

  const handleRun = () => {
    setIsRunning(true)
    setShowResults(false)
    setTimeout(() => {
      setIsRunning(false)
      setShowResults(true)
    }, 2000)
  }

  const handleClear = () => {
    setNodes([])
    setEdges([])
    setSelectedNode(null)
    setShowResults(false)
  }

  const selectedType = selectedNode?.data?.type as WorkflowNodeType | undefined
  const selectedColors = selectedType ? nodeTypeColors[selectedType] : null

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: '#0a0a0f' }}>
      {/* ── Left: Node Palette ── */}
      <div
        className="w-[220px] flex-shrink-0 overflow-y-auto"
        style={{
          borderRight: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.015)',
        }}
      >
        <div className="p-3 pt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-white/30 mb-3 px-1">
            {t('workflow.nodePanel')}
          </p>
          <div className="space-y-1">
            {workflowNodePalette.map((node) => {
              const Icon = nodeTypeIcons[node.type]
              const colors = nodeTypeColors[node.type]
              return (
                <PaletteItem
                  key={node.type}
                  node={node}
                  Icon={Icon}
                  colors={colors}
                />
              )
            })}
          </div>
        </div>
      </div>

      {/* ── Center: Canvas ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Toolbar */}
        <div
          className="flex items-center justify-between px-4 py-2.5 flex-shrink-0"
          style={{
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            background: 'rgba(10,10,15,0.8)',
            backdropFilter: 'blur(12px)',
          }}
        >
          <div className="flex items-center gap-1.5 text-[12px]">
            <span className="text-white/30">Build</span>
            <ChevronRight className="h-3 w-3 text-white/20" />
            <span className="text-white/30">Threat Analysis</span>
            <ChevronRight className="h-3 w-3 text-white/20" />
            <span className="text-white/70 font-medium">Threat Analysis Pipeline</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={handleClear}
              className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] text-white/40 transition-all duration-200 hover:text-white/70 hover:bg-white/5"
            >
              <Trash2 className="h-3 w-3" />
              {t('workflow.clear')}
            </button>
            <button
              onClick={handleRun}
              disabled={isRunning}
              className="group flex items-center gap-2 rounded-full px-4 py-1.5 text-[11px] font-semibold text-white transition-all duration-300 disabled:opacity-60 hover:-translate-y-px"
              style={{
                background: 'linear-gradient(to right, #7c3aed, #4f46e5)',
                boxShadow: '0 0 14px rgba(139,92,246,0.35)',
              }}
            >
              {isRunning ? (
                <>
                  <span className="h-3 w-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  Running…
                </>
              ) : (
                <>
                  <Play className="h-3 w-3" />
                  {t('workflow.run')}
                </>
              )}
            </button>
          </div>
        </div>

        {/* ReactFlow Canvas */}
        <div ref={reactFlowWrapper} className="flex-1" onDragOver={onDragOver} onDrop={onDrop}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
            style={{ background: '#0a0a0f' }}
            defaultEdgeOptions={{
              style: { stroke: 'rgba(139,92,246,0.4)', strokeWidth: 1.5 },
              animated: false,
            }}
          >
            <Background
              gap={24}
              size={1}
              color="rgba(255,255,255,0.04)"
              variant={BackgroundVariant.Dots}
            />
            <Controls
              style={{
                background: 'rgba(13,13,20,0.9)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 12,
              }}
            />
            <MiniMap
              style={{
                background: 'rgba(13,13,20,0.9)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: 12,
              }}
              maskColor="rgba(10,10,15,0.7)"
            />
          </ReactFlow>
        </div>

        {/* Run Results Panel */}
        <AnimatePresence>
          {showResults && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 224, opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.3, ease: EASE }}
              className="flex-shrink-0 overflow-hidden"
              style={{
                borderTop: '1px solid rgba(139,92,246,0.2)',
                background: 'rgba(13,13,20,0.95)',
                backdropFilter: 'blur(20px)',
              }}
            >
              <div className="p-4 h-full overflow-auto">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div
                      className="flex h-5 w-5 items-center justify-center rounded-full"
                      style={{ background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.3)' }}
                    >
                      <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                    </div>
                    <span className="text-[11px] font-semibold text-white/70">
                      {t('workflow.runResults')}
                    </span>
                    <span
                      className="text-[10px] text-emerald-400 font-medium px-1.5 py-0.5 rounded-full"
                      style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.2)' }}
                    >
                      Completed
                    </span>
                    <span className="flex items-center gap-1 text-[10px] text-white/30">
                      <Clock className="h-2.5 w-2.5" />
                      2.3s
                    </span>
                  </div>
                  <button
                    onClick={() => setShowResults(false)}
                    className="text-white/20 hover:text-white/50 transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-5 gap-2 mb-3">
                  {MOCK_RUN_STEPS.map((step) => (
                    <div
                      key={step.node}
                      className="rounded-lg px-2.5 py-2 text-center"
                      style={{
                        background: 'rgba(52,211,153,0.05)',
                        border: '1px solid rgba(52,211,153,0.15)',
                      }}
                    >
                      <div className="flex items-center justify-center mb-1">
                        <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                      </div>
                      <p className="text-[9px] font-medium text-white/60 truncate">{step.node}</p>
                      <p className="text-[8px] text-white/25 mt-0.5">{step.time}</p>
                    </div>
                  ))}
                </div>

                <div
                  className="rounded-lg p-3"
                  style={{
                    background: 'rgba(255,255,255,0.03)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Zap className="h-3 w-3 text-violet-400" />
                    <span className="text-[10px] font-medium text-white/40">Output</span>
                  </div>
                  <p className="text-[11px] text-white/65 font-mono">
                    Detected SQL injection vulnerability (CVE-2025-1234) — Severity: HIGH — CVSS: 9.1
                  </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Right: Config Panel ── */}
      <div
        className="w-[280px] flex-shrink-0 overflow-y-auto"
        style={{
          borderLeft: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.015)',
        }}
      >
        <div className="p-3 pt-4">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-white/30 mb-3 px-1">
            {t('workflow.configuration')}
          </p>

          <AnimatePresence mode="wait">
            {selectedNode ? (
              <motion.div
                key={selectedNode.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.2, ease: EASE }}
                className="space-y-4"
              >
                {/* Node identity card */}
                <div
                  className="rounded-xl p-3"
                  style={{
                    background: selectedColors ? selectedColors.bg : 'rgba(255,255,255,0.03)',
                    border: `1px solid ${selectedColors ? selectedColors.border : 'rgba(255,255,255,0.06)'}`,
                  }}
                >
                  <div className="flex items-center gap-2.5">
                    {selectedType && (() => {
                      const Icon = nodeTypeIcons[selectedType]
                      return (
                        <div
                          className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg"
                          style={{
                            background: selectedColors?.bg,
                            border: `1px solid ${selectedColors?.border}`,
                          }}
                        >
                          <Icon className="h-4 w-4" style={{ color: selectedColors?.color }} />
                        </div>
                      )
                    })()}
                    <div>
                      <p className="text-[12px] font-semibold text-white/85">
                        {selectedNode.data.label}
                      </p>
                      <p className="text-[10px] text-white/35 capitalize">
                        {selectedNode.data.type?.replace(/_/g, ' ')}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Label editor */}
                <div>
                  <label className={labelCls}>Label</label>
                  <input
                    type="text"
                    defaultValue={selectedNode.data.label}
                    className={inputCls}
                  />
                </div>

                {/* Type-specific fields */}
                <NodeConfigFields node={selectedNode} />

                {/* Delete button */}
                <button
                  onClick={() => {
                    setNodes((nds) => nds.filter((n) => n.id !== selectedNode.id))
                    setEdges((eds) =>
                      eds.filter(
                        (e) => e.source !== selectedNode.id && e.target !== selectedNode.id,
                      ),
                    )
                    setSelectedNode(null)
                  }}
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[11px] text-rose-400/70 transition-all duration-200 hover:text-rose-400 hover:bg-rose-500/8"
                  style={{ border: '1px solid rgba(244,63,94,0.15)' }}
                >
                  <Trash2 className="h-3 w-3" />
                  Delete Node
                </button>
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="flex flex-col items-center justify-center py-16 px-4 text-center"
              >
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-2xl mb-3"
                  style={{
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid rgba(255,255,255,0.06)',
                  }}
                >
                  <Sparkles className="h-5 w-5 text-white/20" />
                </div>
                <p className="text-[12px] font-medium text-white/30">Select a node</p>
                <p className="text-[10px] text-white/18 mt-1">
                  Click any node to configure its settings
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

// Extracted to avoid inline event-handler recreation
function PaletteItem({
  node,
  Icon,
  colors,
}: {
  node: { type: WorkflowNodeType; label: string; description: string }
  Icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>
  colors: { color: string; glow: string; bg: string; border: string }
}) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('application/workflow-node-type', node.type)
        e.dataTransfer.setData('application/workflow-node-label', node.label)
        e.dataTransfer.effectAllowed = 'move'
      }}
      className="group flex items-center gap-2.5 rounded-xl px-2.5 py-2 cursor-grab active:cursor-grabbing"
      style={{
        border: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(255,255,255,0.025)',
        transition: 'border 0.15s, background 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget
        el.style.border = `1px solid ${colors.border}`
        el.style.background = colors.bg
        el.style.boxShadow = `0 0 10px ${colors.glow}`
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget
        el.style.border = '1px solid rgba(255,255,255,0.06)'
        el.style.background = 'rgba(255,255,255,0.025)'
        el.style.boxShadow = ''
      }}
    >
      <div
        className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-lg"
        style={{ background: colors.bg, border: `1px solid ${colors.border}` }}
      >
        <Icon className="h-3.5 w-3.5" style={{ color: colors.color }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[11px] font-medium text-white/75 leading-none mb-0.5">{node.label}</p>
        <p className="text-[9px] text-white/30 truncate">{node.description}</p>
      </div>
      <GripVertical className="h-3 w-3 text-white/20 group-hover:text-white/40 transition-colors" />
    </div>
  )
}
