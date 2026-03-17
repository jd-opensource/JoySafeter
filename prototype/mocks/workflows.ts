export type WorkflowNodeType =
  | 'start'
  | 'end'
  | 'llm'
  | 'code'
  | 'http'
  | 'knowledge_retrieval'
  | 'condition'
  | 'variable'
  | 'iterator'

export interface WorkflowNodeData {
  label: string
  type: WorkflowNodeType
  description?: string
  config?: Record<string, unknown>
}

export interface WorkflowTemplate {
  id: string
  name: string
  description: string
  nodeCount: number
  category: string
}

export const workflowTemplates: WorkflowTemplate[] = [
  {
    id: 'wf-tpl-001',
    name: 'Threat Analysis Pipeline',
    description: 'Automated threat detection and classification workflow',
    nodeCount: 6,
    category: 'Security',
  },
  {
    id: 'wf-tpl-002',
    name: 'RAG Query Pipeline',
    description: 'Retrieve-Augment-Generate pipeline for knowledge-based Q&A',
    nodeCount: 5,
    category: 'Knowledge',
  },
  {
    id: 'wf-tpl-003',
    name: 'Vulnerability Scanner',
    description: 'Multi-step vulnerability scanning and reporting',
    nodeCount: 8,
    category: 'Security',
  },
]

export const workflowNodePalette: { type: WorkflowNodeType; label: string; description: string; color: string }[] = [
  { type: 'start', label: 'Start', description: 'Workflow entry point', color: '#22c55e' },
  { type: 'end', label: 'End', description: 'Workflow exit point', color: '#ef4444' },
  { type: 'llm', label: 'LLM', description: 'Language model inference', color: '#8b5cf6' },
  { type: 'code', label: 'Code', description: 'Execute custom code', color: '#f59e0b' },
  { type: 'http', label: 'HTTP Request', description: 'Make HTTP API calls', color: '#3b82f6' },
  { type: 'knowledge_retrieval', label: 'Knowledge Retrieval', description: 'Query knowledge base', color: '#06b6d4' },
  { type: 'condition', label: 'Condition', description: 'Conditional branching', color: '#ec4899' },
  { type: 'variable', label: 'Variable', description: 'Set or transform variables', color: '#64748b' },
  { type: 'iterator', label: 'Iterator', description: 'Loop over items', color: '#f97316' },
]

export const defaultWorkflowNodes = [
  {
    id: 'start-1',
    type: 'workflowNode',
    position: { x: 100, y: 200 },
    data: { label: 'Start', type: 'start' as WorkflowNodeType, description: 'Workflow entry' },
  },
  {
    id: 'llm-1',
    type: 'workflowNode',
    position: { x: 400, y: 100 },
    data: { label: 'Analyze Threat', type: 'llm' as WorkflowNodeType, description: 'Use LLM to analyze input' },
  },
  {
    id: 'condition-1',
    type: 'workflowNode',
    position: { x: 700, y: 200 },
    data: { label: 'Is Threat?', type: 'condition' as WorkflowNodeType, description: 'Check threat level' },
  },
  {
    id: 'kb-1',
    type: 'workflowNode',
    position: { x: 1000, y: 100 },
    data: { label: 'Lookup CVE', type: 'knowledge_retrieval' as WorkflowNodeType, description: 'Search CVE database' },
  },
  {
    id: 'code-1',
    type: 'workflowNode',
    position: { x: 1000, y: 300 },
    data: { label: 'Format Report', type: 'code' as WorkflowNodeType, description: 'Generate report' },
  },
  {
    id: 'end-1',
    type: 'workflowNode',
    position: { x: 1300, y: 200 },
    data: { label: 'End', type: 'end' as WorkflowNodeType, description: 'Output results' },
  },
]

export const defaultWorkflowEdges = [
  { id: 'e-start-llm', source: 'start-1', target: 'llm-1', animated: true },
  { id: 'e-llm-cond', source: 'llm-1', target: 'condition-1' },
  { id: 'e-cond-kb', source: 'condition-1', target: 'kb-1', label: 'Yes' },
  { id: 'e-cond-code', source: 'condition-1', target: 'code-1', label: 'No' },
  { id: 'e-kb-end', source: 'kb-1', target: 'end-1' },
  { id: 'e-code-end', source: 'code-1', target: 'end-1' },
]
