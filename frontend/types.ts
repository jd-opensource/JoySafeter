
export interface Position {
  x: number;
  y: number;
}

export interface Viewport {
  x: number;
  y: number;
  zoom: number;
}

export enum NodeType {
  USER = 'USER',
  AI = 'AI',
}

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp: number;
    tool_calls?: ToolCall[];
    isStreaming?: boolean;
    metadata?: {
        lastNode?: string;
        lastRunId?: string;
        lastUpdate?: number;
        [key: string]: any;
    };
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, any>;
  status: 'running' | 'completed' | 'failed';
  result?: any;
  startTime: number;
  endTime?: number;
}

// File extensions that are commonly used and safe
export const COMMON_EXTENSIONS = new Set([
  '.md', '.txt', '.rst',  // Documentation
  '.py', '.js', '.ts', '.jsx', '.tsx',  // Scripts
  '.sh', '.bash', '.zsh',  // Shell scripts
  '.json', '.yaml', '.yml', '.toml',  // Config files
  '.html', '.css', '.scss',  // Web assets
  '.svg', '.xml',  // Other formats
]);

// File extensions that should trigger a warning (potentially unsafe/binary)
export const WARNED_EXTENSIONS = new Set([
  '.exe', '.dll', '.bin', '.so', '.dylib',  // Executables
  '.class', '.jar', '.war',  // Java
  '.o', '.a', '.lib',  // Object files
  '.zip', '.tar', '.gz', '.rar', '.7z',  // Archives
  '.db', '.sqlite', '.sqlite3',  // Databases
]);

export interface SkillFile {
  id: string;
  skill_id: string;
  path: string;
  file_name: string;
  file_type: string;
  content: string | null;
  storage_type: 'database' | 's3';
  storage_key: string | null;
  size: number;
  created_at: string;
  updated_at: string;
  // Legacy fields for backward compatibility
  name?: string;
  language?: string;
}

// File tree node for hierarchical display
export interface FileTreeNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children?: FileTreeNode[];
  file?: SkillFile;
}

// YAML frontmatter structure for SKILL.md (per Agent Skills specification)
export interface SkillFrontmatter {
  name: string;
  description: string;
  tags?: string[];
  license?: string;
  compatibility?: string;  // Max 500 characters
  metadata?: Record<string, string>;  // dict[str, str]
  'allowed-tools'?: string;  // Space-delimited string (per spec)
  allowed_tools?: string[];  // Also support array format
  // Legacy fields (for backward compatibility)
  version?: string;
  author?: string;
  [key: string]: any;  // Allow additional custom fields
}

// Parsed SKILL.md content
export interface ParsedSkillMd {
  frontmatter: SkillFrontmatter;
  body: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string; // This is the markdown body from SKILL.md
  tags: string[];
  source_type: 'local' | 'git' | 's3';
  source_url: string | null;
  root_path: string | null;
  owner_id: string | null;
  created_by_id: string;
  is_public: boolean;
  license: string | null;
  compatibility?: string | null;  // Max 500 characters (per Agent Skills spec)
  metadata?: Record<string, string>;  // dict[str, str] (per Agent Skills spec)
  allowed_tools?: string[];  // list[str] (per Agent Skills spec)
  created_at: string;
  updated_at: string;
  files?: SkillFile[];
  // Legacy fields for backward compatibility (deprecated, use source_type instead)
  source?: 'local' | 'git' | 's3';  // Updated: 'aws' -> 's3' to match form schema
  sourceUrl?: string;
  updatedAt?: number;
}


export interface CanvasNode {
  id: string;
  parentId: string | null;
  type: NodeType;
  content: string;
  position: Position;
  width: number;
  isStreaming?: boolean;
  createdAt: number;
  toolCalls?: ToolCall[];
  data?: any;
}

export interface Edge {
  id: string;
  source: string;
  target: string;
}

export interface ChatMessage {
  role: 'user' | 'model';
  parts: { text: string }[];
}

export type ViewMode = 'chat' | 'builder' | 'skills';

// Execution Panel Types
export type ExecutionStepType = 'node_lifecycle' | 'agent_thought' | 'tool_execution' | 'system_log' | 'model_io' | 'code_agent_thought' | 'code_agent_code' | 'code_agent_observation' | 'code_agent_final_answer' | 'code_agent_planning' | 'code_agent_error';
export type ExecutionStepStatus = 'pending' | 'running' | 'waiting' | 'success' | 'error';

// Tool execution data structure
export interface ToolExecutionData {
  request?: any;    // Tool input/arguments
  response?: any;   // Tool output/result
}

export interface ExecutionStep {
  id: string;
  nodeId: string;
  nodeLabel: string;
  stepType: ExecutionStepType;
  title: string;
  status: ExecutionStepStatus;
  startTime: number;
  endTime?: number;
  duration?: number;
  content?: string;  // For streaming text content (agent_thought)
  data?: ToolExecutionData | any;  // For structured data (tool arguments/results)
}

// StreamManager types for execution state management
export interface StreamManagerState {
  steps: Map<string, ExecutionStep>;
  currentStepId: string | null;
  isStreaming: boolean;
}

export interface StreamManagerConfig {
  enableVirtualScroll: boolean;
  virtualScrollThreshold: number;  // Enable virtual scroll when steps exceed this count
  scrollDebounceMs: number;        // Debounce scroll updates
  toolCallCollapseThreshold: number; // Auto-collapse tool calls with output exceeding this length
}
