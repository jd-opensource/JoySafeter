export interface Agent {
  id: string;
  name: string;
  description?: string | null;
  model: { id: string; speed?: string };
  tools?: AgentTool[];
  mcp_servers?: McpServer[];
  skills?: AgentSkillRef[];
  skill_ids?: string[];
  system?: string | null;
  system_prompt?: string;
  version?: number;
  metadata?: Record<string, unknown>;
  env?: Record<string, string>;
  environment_ref?: string | null;
  secret_ref?: string | null;
  engine_kind?: string;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface AgentSkillRef {
  type: "custom";
  skill_id: string;
  version: string;
}

export interface ToolItemConfig {
  name: string;
  enabled?: boolean;
  permission_policy?: { type: string };
  argument_patterns?: string[];
}

export interface ToolDefaultConfig {
  permission_policy?: { type: string };
  enabled?: boolean;
}

export type AgentTool =
  | {
      type: "agent_toolset_20260401";
      default_config?: ToolDefaultConfig;
      configs?: ToolItemConfig[];
    }
  | {
      type: "mcp_toolset";
      mcp_server_name: string;
      default_config?: ToolDefaultConfig;
      configs?: ToolItemConfig[];
    }
  | {
      type: "custom";
      name: string;
      description: string;
      input_schema: unknown;
    };

export interface McpServer {
  type: "url";
  name: string;
  url: string;
}

export interface Session {
  id: string;
  agent?: SessionAgent;
  environment_id?: string;
  status: SessionStatus;
  stop_reason?: string;
  title?: string;
  metadata?: Record<string, unknown>;
  vault_ids?: string[];
  repo_resources?: SessionRepoResource[];
  usage?: SessionUsage;
  stats?: SessionStats;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface SessionAgent {
  id: string;
  agent_id?: string;
  name: string;
  engine_kind?: string | null;
  model?: { id: string } | null;
  version?: number;
}

export type SessionStatus = "idle" | "running" | "rescheduling" | "terminated";

export interface SessionUsage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
}

export interface SessionStats {
  started_at?: string;
  ended_at?: string;
  duration_ms?: number;
  duration_seconds?: number | null;
  active_seconds?: number | null;
}

export interface SessionEvent {
  id: string;
  type: string;
  seq?: number;
  created_at?: string;
  // Flattened payload fields
  content?: { type: string; text: string }[] | string;
  model?: string;
  usage?: Partial<SessionUsage>;
  stop_reason?: unknown;
  tool?: string;
  tool_name?: string;
  name?: string;
  call_id?: string;
  _call_id?: string;
  tool_use_id?: string;
  input?: unknown;
  output?: unknown;
  is_error?: boolean;
  duration_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  task_id?: string;
  processed_at?: string | null;
  // Legacy compat
  session_id?: string;
  event_type?: string;
  payload?: unknown;
  _collapsedCount?: number;
}

export interface EnvironmentNetworking {
  type: string;
  allowed_hosts?: string[];
  allow_mcp_servers?: boolean;
  allow_package_managers?: boolean;
}

export interface EnvironmentPackages {
  apt?: string[];
  pip?: string[];
  npm?: string[];
  cargo?: string[];
  gem?: string[];
  go?: string[];
}

export interface EnvironmentConfig {
  type?: string;
  packages?: EnvironmentPackages;
  networking?: EnvironmentNetworking;
  env_vars?: Record<string, string>;
  secret_refs?: string[];
}

export interface Environment {
  id: string;
  name: string;
  description?: string;
  config?: EnvironmentConfig;
  metadata?: Record<string, string>;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface Vault {
  id: string;
  name: string;
  description?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface VaultCredential {
  id: string;
  vault_id: string;
  name: string;
  credential_type: string;
  mcp_server_url: string;
  oauth_config?: {
    client_id: string;
    token_endpoint: string;
    expires_at?: string;
    scopes?: string[];
  } | null;
  env_var_name?: string | null;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface MemoryStore {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  archived_at?: string | null;
}

export interface PaginatedResponse<T> {
  data: T[];
  has_more?: boolean;
}

export interface FileRecord {
  id: string;
  filename: string;
  purpose: string;
  content_type: string;
  size_bytes: number;
  downloadable: boolean;
  created_at: string;
}

export interface SessionFileResource {
  id: string;
  type: "file";
  file_id: string;
  mount_path: string;
  access: string;
  created_at: string;
}

export interface SessionRepoResource {
  id: string;
  type: "github_repository";
  url: string;
  branch: string;
  mount_path: string;
  mount_name: string;
  // The clone token (authorization_token) is never returned by the API.
}

export type SessionResource = SessionFileResource | SessionRepoResource;

export interface AddFileResourceRequest {
  type: "file";
  file_id: string;
  mount_path?: string;
}

export interface AddRepoResourceRequest {
  type: "github_repository";
  url: string;
  branch?: string;
  mount_path?: string;
  authorization_token?: string;
}

export interface SkillSecurityScanSummary {
  status: "passed" | "warning" | "blocked" | "failed" | "not_scanned" | string;
  score: number | null;
  severity: string | null;
  recommendation: string | null;
  issues_count: number;
  critical_count: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  scanned_at: string | null;
  scan_id: string | null;
  target_hash: string | null;
}

export interface SkillSecurityScanRecord extends SkillSecurityScanSummary {
  id: string;
  skill_id: string | null;
  project_id: string | null;
  owner_id: string | null;
  created_by_id: string;
  trigger: string;
  target_name: string | null;
  target_hash: string;
  scanner: string;
  scanner_version: string | null;
  report: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface SkillRecord {
  id: string;
  display_title?: string;
  source: string;
  latest_version?: string;
  name: string;
  description: string;
  content: string;
  tags: unknown[];
  allowed_tools: unknown[];
  metadata: Record<string, unknown>;
  license: string;
  compatibility: Record<string, unknown>;
  is_public: boolean;
  source_type: string;
  source_url: string;
  created_at: string;
  updated_at: string;
  security_scan?: SkillSecurityScanSummary;
}

export interface SkillVersionRecord {
  id: string;
  skill_id: string;
  version: string;
  name: string;
  description: string;
  directory: string;
  content: string;
  frontmatter: Record<string, unknown>;
  release_notes?: string;
  created_at: string;
}

export interface SkillFileRecord {
  id: string;
  skill_id: string;
  path: string;
  file_name: string;
  file_type: string;
  content: string;
  size: number;
  created_at: string;
  updated_at: string;
}

export interface MemberRecord {
  user_id: string;
  email: string;
  display_name: string;
  avatar_url?: string;
  role: string;
  joined_at: string;
}

export interface Secret {
  id: string;
  name: string;
  provider?: string;
  protocol?: string;
  is_default?: boolean;
  data?: Record<string, string>;
  keys?: string[];
  created_at: string;
  updated_at: string;
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  key_prefix: string;
  key?: string;
  role?: string;
  last_used_at?: string;
  expires_at?: string;
  created_at: string;
}

export interface ProjectRecord {
  id: string;
  name: string;
  slug: string;
  is_default: boolean;
  created_at: string;
}
