import type {
  AgentId,
  ApiKeyId,
  CredentialGroupId,
  CredentialId,
  EnvironmentId,
  EventId,
  FileId,
  MemoryStoreId,
  ProjectId,
  SandboxId,
  SessionId,
  SessionResourceId,
  SkillFileId,
  SkillId,
  SkillSecurityScanId,
  SkillUsageId,
  SkillVersionFileId,
  SkillVersionId,
  StorageGrantId,
  StorageMountAuditId,
  StorageVolumeId,
  TaskId,
} from '@/types/entity-id'

export interface Agent {
  id: AgentId
  name: string
  description?: string | null
  model?: AgentModelConfig | null
  tools?: AgentTool[]
  mcp_servers?: McpServer[]
  skills?: AgentSkillRef[]
  system?: string | null
  version?: number
  metadata?: Record<string, unknown>
  env?: Record<string, string>
  environment_ref?: string | null
  model_credential_id?: CredentialId | null
  model_connection?: ModelConnectionSummary | null
  engine_kind: string
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface ApiKey {
  id: ApiKeyId
  project_id: ProjectId
  name: string
  key_prefix: string
  role: string
  status: 'active' | 'expired' | 'revoked'
  created_at?: string
  expires_at?: string | null
  revoked_at?: string | null
  last_used_at?: string | null
}

export interface ApiKeyCreateResponse extends ApiKey {
  raw_key: string
}

export interface AgentSkillRef {
  type: 'custom'
  skill_id: SkillId
  version: string
}

export interface ToolItemConfig {
  name: string
  enabled?: boolean
  permission_policy?: { type: string }
  argument_patterns?: string[]
}

export interface ToolDefaultConfig {
  permission_policy?: { type: string }
  enabled?: boolean
}

export type AgentTool =
  | {
      type: 'agent_toolset_20260401'
      default_config?: ToolDefaultConfig
      configs?: ToolItemConfig[]
    }
  | {
      type: 'mcp_toolset'
      mcp_server_name: string
      default_config?: ToolDefaultConfig
      configs?: ToolItemConfig[]
    }
  | {
      type: 'custom'
      name: string
      description: string
      input_schema: unknown
    }

export type McpRemoteTransport = 'streamable_http' | 'sse'
export type McpAuthRequirement = 'required' | 'optional' | 'none'

export interface RemoteMcpServer {
  type: McpRemoteTransport
  name: string
  url: string
  auth_requirement: McpAuthRequirement
}

export interface LocalMcpServer {
  type: 'local_stdio'
  name: string
  command: string
  args: string[]
  env: Record<string, string>
}

export type McpServer = RemoteMcpServer | LocalMcpServer

export type McpCredentialAuthScheme = 'static_bearer' | 'header_api_key' | 'custom_header'

export interface Session {
  id: SessionId
  agent?: SessionAgent
  environment_id?: string
  status: SessionStatus
  stop_reason?: string
  title?: string
  metadata?: Record<string, unknown>
  credential_group_ids?: CredentialGroupId[]
  repo_resources?: SessionRepoResource[]
  storage_mounts?: SessionStorageMount[]
  usage?: SessionUsage
  stats?: SessionStats
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface SessionAgent {
  id: AgentId
  agent_id?: AgentId
  name: string
  engine_kind?: string | null
  model?: AgentModelConfig | null
  model_credential_id?: CredentialId | null
  model_connection?: ModelConnectionSummary | null
  version?: number
}

export interface AgentModelConfig {
  id: string
  speed?: string
}

export interface ModelConnectionSummary {
  id: CredentialId
  name: string
  provider: string | null
  protocol: string | null
  model: string | null
  is_default: boolean
  archived_at: string | null
}

export type SessionStatus = 'idle' | 'running' | 'rescheduling' | 'terminated'

export interface SessionUsage {
  input_tokens: number
  output_tokens: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
}

export interface SessionStats {
  started_at?: string
  ended_at?: string
  duration_ms?: number
  duration_seconds?: number | null
  active_seconds?: number | null
}

export interface NetworkPolicyStatus {
  sandbox_id: SandboxId
  session_id?: SessionId | null
  task_id?: TaskId | null
  project_id?: string | null
  session_title?: string | null
  agent_name?: string | null
  sandbox_status: string
  networking_status: string
  networking_policy_hash?: string | null
  networking_policy_version: number
  networking_last_error?: string | null
  networking_ready_at?: string | null
  sandbox_updated_at: string
  latest_policy_status?: string | null
  latest_policy_error?: string | null
  latest_policy_nack_reason?: string | null
  latest_policy_updated_at?: string | null
  rendered_summary?: Record<string, unknown>
}

export interface NetworkPolicyListResponse {
  data: NetworkPolicyStatus[]
  total: number
  page: number
  page_size: number
}

export interface SessionEvent {
  id?: EventId
  type: string
  seq?: number
  created_at?: string
  // Flattened payload fields
  content?: { type: string; text: string }[] | string
  model?: string
  usage?: Partial<SessionUsage>
  stop_reason?: unknown
  tool?: string
  tool_name?: string
  name?: string
  call_id?: string
  _call_id?: string
  tool_use_id?: string
  input?: unknown
  output?: unknown
  is_error?: boolean
  duration_ms?: number
  input_tokens?: number
  output_tokens?: number
  cache_read_tokens?: number
  cache_write_tokens?: number
  task_id?: TaskId
  processed_at?: string | null
  _collapsedCount?: number
}

export interface QuickstartTaskSummary {
  id: TaskId
  status: string
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  error?: string | null
}

export interface SessionSkillUsage {
  id: SkillUsageId
  skill_id?: SkillId | null
  skill_name?: string | null
  skill_source_type?: string | null
  skill_version?: string | null
  skill_version_id?: SkillVersionId | null
  target?: string | null
  security_scan_id?: SkillSecurityScanId | null
  target_hash?: string | null
  artifact_hash?: string | null
  session_id?: SessionId | null
  agent_id?: AgentId | null
  project_id?: string | null
  user_id?: string | null
  created_at: string
}

export interface EnvironmentNetworking {
  type: string
  allowed_hosts?: string[]
  allow_package_managers?: boolean
}

export interface EnvironmentPackages {
  apt?: string[]
  pip?: string[]
  npm?: string[]
  cargo?: string[]
  gem?: string[]
  go?: string[]
}

export interface EnvironmentEgressServiceInject {
  type?: 'bearer' | 'api_key' | 'raw_header' | 'cookie' | string
  credential_field?: string
  header?: string
  cookie_name?: string
  cookies?: Record<string, string>
}

export interface EnvironmentEgressService {
  name: string
  kind?: 'external' | string
  exposure?: 'placeholder' | 'transparent' | string
  base_url: string
  service_credential_id: CredentialId
  inject?: EnvironmentEgressServiceInject
  allowed_paths?: string[]
}

export interface CanonicalEnvironmentCredentialReferences {
  direct_credential_ids: CredentialId[]
  egress_services: EnvironmentEgressService[]
}

export interface EnvironmentMountResource {
  type: 'storage' | string
  name: string
  volume_ref: string
  sub_path?: string
  mount_path: string
  access?: 'read_only' | 'read_write' | string
  required?: boolean
}

export interface EnvironmentStorageVolume {
  name?: string
  volume_id?: StorageVolumeId
  mount_path?: string
}

export interface StorageVolumeCatalogItem {
  volume_ref: string
  backend_type?: string
  display_name: string
  description?: string
  max_access: 'read_only' | 'read_write' | string
  allowed_prefixes?: string[]
  quota_bytes?: number | null
  used_bytes?: number
  supports_docker?: boolean
  supports_k8s?: boolean
}

export interface StorageProjectGrant {
  id: StorageGrantId
  volume_id: StorageVolumeId
  project_id: string
  max_access: 'read_only' | 'read_write' | string
  allowed_prefixes?: string[]
  quota_bytes?: number | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface StorageOrganizationGrant {
  id: StorageGrantId
  volume_id: StorageVolumeId
  org_id: string
  max_access: 'read_only' | 'read_write' | string
  allowed_prefixes?: string[]
  quota_bytes?: number | null
  enabled: boolean
  created_at: string
  updated_at: string
}

export interface StorageVolume extends StorageVolumeCatalogItem {
  id: StorageVolumeId
  docker?: Record<string, unknown>
  k8s?: Record<string, unknown>
  enabled: boolean
  metadata?: Record<string, unknown>
  grants?: StorageProjectGrant[]
  organization_grants?: StorageOrganizationGrant[]
  created_at: string
  updated_at: string
}

export interface StorageMountAudit {
  id: StorageMountAuditId
  volume_id?: StorageVolumeId | null
  project_id?: string | null
  session_id?: SessionId | null
  environment_id?: EnvironmentId | null
  user_id?: string | null
  action: string
  volume_ref?: string | null
  mount_path?: string | null
  sub_path?: string | null
  access?: string | null
  bytes_used?: number | null
  result: string
  detail?: Record<string, unknown>
  created_at: string
}

export interface EnvironmentConfig {
  type?: string
  packages?: EnvironmentPackages
  networking?: EnvironmentNetworking
  env_vars?: Record<string, string>
  environment_credential_ids?: CredentialId[]
  egress_services?: EnvironmentEgressService[]
  storage_volumes?: EnvironmentStorageVolume[]
  mount_resources?: EnvironmentMountResource[]
}

export interface Environment {
  id: EnvironmentId
  name: string
  description?: string
  config?: EnvironmentConfig
  metadata?: Record<string, string>
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface CredentialGroup {
  id: CredentialGroupId
  name: string
  description?: string
  metadata?: Record<string, string>
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface CredentialGroupCredential {
  id: CredentialId
  group_id: CredentialGroupId
  name: string
  mcp_server_url: string
  auth_scheme: McpCredentialAuthScheme
  data?: Record<string, string>
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface MemoryStore {
  id: MemoryStoreId
  name: string
  description?: string
  created_at: string
  updated_at: string
  archived_at?: string | null
}

export interface PaginatedResponse<T> {
  data: T[]
  has_more?: boolean
}

export interface FileRecord {
  id: FileId
  type?: 'file'
  filename: string
  purpose: string
  content_type: string
  size_bytes: number
  sha256?: string
  downloadable: boolean
  session_id?: SessionId | null
  created_at: string
}

export interface SessionFileResource {
  id: SessionResourceId
  type: 'file'
  file_id: FileId
  mount_path: string
  access: string
  created_at: string
}

export interface SessionRepoResource {
  id: SessionResourceId
  type: 'github_repository'
  url: string
  branch: string
  mount_path: string
  mount_name: string
  has_authorization_token: boolean
  token_status: 'none' | 'active' | 'expired' | 'erased'
  token_expires_at: string | null
  token_rotated_at: string | null
  token_erased_at: string | null
  // The clone token (authorization_token) is never returned by the API.
}

export interface SessionStorageMount {
  id: SessionResourceId
  type: 'storage'
  name: string
  volume_ref: string
  volume_id: StorageVolumeId
  sub_path: string
  mount_path: string
  access: string
  required: boolean
  created_at: string
}

export type SessionResource = SessionFileResource | SessionRepoResource

export interface AddFileResourceRequest {
  type: 'file'
  file_id: FileId
  mount_path?: string
}

export interface AddRepoResourceRequest {
  type: 'github_repository'
  url: string
  branch?: string
  mount_path?: string
  authorization_token?: string
  token_expires_at?: string
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
  scan_id: SkillSecurityScanId | null
  target_hash: string | null
}

export interface SkillSecurityScanRecord {
  id: SkillSecurityScanId
  skill_id: SkillId | null
  project_id: string | null
  owner_id: string | null
  created_by_id: string
  trigger: string
  target_name: string | null
  target_hash: string
  scanner: string
  scanner_version: string | null
  status: string
  score: number | null
  severity: string | null
  recommendation: string | null
  issues_count: number
  critical_count: number
  high_count: number
  medium_count: number
  low_count: number
  report: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export type SkillVisibility = 'project' | 'organization' | 'public'

// The tiers a skill version can be promoted to (everything above the project
// floor). Exposure to these happens only through the promotion approval flow.
export type PromotableTier = Exclude<SkillVisibility, 'project'>

export type SkillLifecycleStatus = 'draft' | 'pending_review' | 'approved' | 'rejected' | 'archived'

export interface SkillImpactSummary {
  counts: {
    agents: number
    agent_versions: number
    triggers: number
    active_tasks: number
    total: number
  }
  references: Array<{
    type: string
    id: string
    name: string
    version?: string | null
    status?: string | null
  }>
}

export interface SkillRecord {
  id: SkillId
  display_title?: string
  latest_version?: string | null
  name: string
  description: string
  content: string
  tags: unknown[]
  allowed_tools: unknown[]
  metadata: Record<string, unknown>
  license: string | null
  compatibility: string | null
  visibility: SkillVisibility
  lifecycle_status: SkillLifecycleStatus
  // Version currently served at each tier, set only through the promotion
  // approval flow. ``null`` when the skill is not exposed at that tier.
  org_version_id?: SkillVersionId | null
  public_version_id?: SkillVersionId | null
  source_type: string
  source_url: string | null
  created_at: string
  updated_at: string
  security_scan?: SkillSecurityScanSummary
  impact?: SkillImpactSummary | null
}

export interface SkillVersionRecord {
  id: SkillVersionId
  skill_id: SkillId
  version: string
  skill_name: string
  skill_description: string
  content: string
  tags: unknown[]
  allowed_tools: unknown[]
  compatibility: string | null
  license: string | null
  release_notes?: string | null
  published_at?: string | null
  // Promotion state: ``lifecycle_status`` is the version's review state
  // (approved / pending_review / rejected); when pending,
  // ``review_target_visibility`` is the tier the submission targets.
  lifecycle_status: SkillLifecycleStatus
  review_target_visibility?: SkillVisibility | null
  created_at: string
}

export interface SkillFileRecord {
  id: SkillFileId
  skill_id: SkillId
  path: string
  file_name: string
  file_type: string
  content: string
  size: number
  created_at: string
  updated_at: string
}

export interface SkillVersionFileRecord {
  id: SkillVersionFileId
  version_id: SkillVersionId
  path: string
  file_name: string
  file_type: string
  content: string
  size: number
  created_at: string
}

export interface MemberRecord {
  user_id: string
  email: string
  display_name: string
  avatar_url?: string
  role: string
  joined_at: string
}

export interface Credential {
  id: import('./entity-id').CredentialId
  name: string
  kind: 'model' | 'mcp' | 'service'
  provider: string | null
  protocol: string | null
  model: string | null
  compatible_engine_ids: string[]
  is_default: boolean
  data?: Record<string, string>
  mcp_server_url?: string | null
  group_id?: import('./entity-id').CredentialGroupId | null
  auth_scheme: McpCredentialAuthScheme | null
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface CredentialDetail extends Credential {
  data: Record<string, string>
}

export interface ApiKeyInfo {
  id: string
  name: string
  key_prefix: string
  key?: string
  role?: string
  status?: 'active' | 'expired' | 'revoked'
  last_used_at?: string
  expires_at?: string | null
  revoked_at?: string | null
  created_at: string
}

export interface ProjectRecord {
  id: string
  name: string
  slug: string
  is_default: boolean
  created_at: string
}
