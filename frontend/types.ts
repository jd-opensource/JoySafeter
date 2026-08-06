// File extensions that are commonly used and safe
export const COMMON_EXTENSIONS = new Set([
  '.md',
  '.txt',
  '.rst', // Documentation
  '.py',
  '.js',
  '.ts',
  '.jsx',
  '.tsx', // Scripts
  '.sh',
  '.bash',
  '.zsh', // Shell scripts
  '.json',
  '.yaml',
  '.yml',
  '.toml', // Config files
  '.html',
  '.css',
  '.scss', // Web assets
  '.svg',
  '.xml', // Other formats
])

// File extensions that should trigger a warning (potentially unsafe/binary)
export const WARNED_EXTENSIONS = new Set([
  '.exe',
  '.dll',
  '.bin',
  '.so',
  '.dylib', // Executables
  '.class',
  '.jar',
  '.war', // Java
  '.o',
  '.a',
  '.lib', // Object files
  '.zip',
  '.tar',
  '.gz',
  '.rar',
  '.7z', // Archives
  '.db',
  '.sqlite',
  '.sqlite3', // Databases
])

export interface SkillFile {
  id: string
  skill_id: string
  path: string
  file_name: string
  file_type: string
  content: string | null
  storage_type: 'database' | 's3'
  storage_key: string | null
  size: number
  created_at: string
  updated_at: string
}

export interface SkillSecurityScanSummary {
  status: 'passed' | 'warning' | 'blocked' | 'failed' | 'not_scanned' | string
  score: number | null
  severity: string | null
  recommendation: string | null
  issues_count: number
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  scanned_at: string | null
  scan_id: string | null
  target_hash: string | null
}

// File tree node for hierarchical display
export interface FileTreeNode {
  name: string
  path: string
  isDirectory: boolean
  children?: FileTreeNode[]
  file?: SkillFile
}

// YAML frontmatter structure for SKILL.md (per Agent Skills specification)
export interface SkillFrontmatter {
  name: string
  description: string
  tags?: string[]
  license?: string
  compatibility?: string // Max 500 characters
  metadata?: Record<string, string> // dict[str, str]
  'allowed-tools'?: string // Space-delimited string (per spec)
  allowed_tools?: string[] // Also support array format
  [key: string]: unknown // Allow additional custom fields
}

// Parsed SKILL.md content
export interface ParsedSkillMd {
  frontmatter: SkillFrontmatter
  body: string
}

// Execution Panel Types
export type ExecutionStepType =
  | 'node_lifecycle'
  | 'agent_thought'
  | 'tool_execution'
  | 'system_log'
  | 'model_io'
  | 'artifact'
  | 'code_agent_thought'
  | 'code_agent_code'
  | 'code_agent_observation'
  | 'code_agent_final_answer'
  | 'code_agent_planning'
  | 'code_agent_error'
export type ExecutionStepStatus = 'pending' | 'running' | 'waiting' | 'success' | 'error'

// Tool execution data structure
export interface ToolExecutionData {
  request?: Record<string, unknown> // Tool input/arguments
  response?: string | Record<string, unknown> // Tool output/result
}

export interface ExecutionStep {
  id: string
  nodeId: string
  nodeLabel: string
  stepType: ExecutionStepType
  title: string
  status: ExecutionStepStatus
  startTime: number
  endTime?: number
  duration?: number
  content?: string // For streaming text content (agent_thought)
  data?: ToolExecutionData | Record<string, unknown> // For structured data (tool arguments/results)
  // Trace / Observation hierarchy (Phase D)
  traceId?: string
  observationId?: string
  parentObservationId?: string
  // Token usage (from GENERATION observations)
  promptTokens?: number
  completionTokens?: number
  totalTokens?: number
}

// ============ Execution Tree Types (Langfuse-style trace tree) ============

export type ExecutionTreeNodeType = 'TRACE' | 'NODE' | 'TOOL' | 'MODEL' | 'THOUGHT' | 'CODE_AGENT'

export type ExecutionTreeNode = {
  id: string
  type: ExecutionTreeNodeType
  name: string
  startTime: number
  endTime?: number
  duration?: number
  status: ExecutionStepStatus
  children: ExecutionTreeNode[]
  depth: number
  /** Max depth of subtree rooted at this node (0 for leaf nodes) */
  childrenDepth: number
  /** Milliseconds from trace start to this node's start time */
  startTimeSinceTrace: number
  /** Original step data reference */
  step?: ExecutionStep
  /** Parent node ID */
  parentId?: string
}

/** Flattened tree node for virtualized rendering */
export interface ExecutionTreeFlatItem {
  node: ExecutionTreeNode
  /** Whether this node is expanded in the tree view */
  isExpanded: boolean
  /** Whether this node has children */
  hasChildren: boolean
}

// StreamManager types for execution state management
export interface StreamManagerState {
  steps: Map<string, ExecutionStep>
  currentStepId: string | null
  isStreaming: boolean
}

export interface StreamManagerConfig {
  enableVirtualScroll: boolean
  virtualScrollThreshold: number // Enable virtual scroll when steps exceed this count
  scrollDebounceMs: number // Debounce scroll updates
  toolCallCollapseThreshold: number // Auto-collapse tool calls with output exceeding this length
}
