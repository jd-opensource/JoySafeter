import { describe, expect, it } from 'vitest'

import en from './locales/en'
import zh from './locales/zh'

type TerminologyExpectation = readonly [
  category: string,
  path: string,
  english: string,
  chinese: string,
]

const terminologyExpectations: readonly TerminologyExpectation[] = [
  ['navigation', 'nav.secrets', 'Connections & Credentials', '连接与凭据'],
  ['navigation', 'nav.vaults', 'MCP Credential Sets', 'MCP 凭据组'],
  ['navigation', 'nav.apiKeys', 'Project Access Tokens', '项目访问令牌'],
  [
    'connections and credentials',
    'managed.secrets.title',
    'Connections & Credentials',
    '连接与凭据',
  ],
  [
    'connections and credentials',
    'managed.secrets.subtitle',
    'Manage model connections and service credentials for this project.',
    '管理当前项目的模型连接与服务凭据。',
  ],
  [
    'connections and credentials',
    'managed.secrets.new',
    'New Connection or Credential',
    '新建连接或凭据',
  ],
  [
    'connections and credentials',
    'managed.secrets.dataLabel',
    'Credential Fields',
    '凭据字段',
  ],
  [
    'connections and credentials',
    'managed.secrets.backToList',
    'Back to Connections & Credentials',
    '返回连接与凭据',
  ],
  [
    'connections and credentials',
    'managed.secrets.empty',
    'No model connections or service credentials yet.',
    '暂无模型连接或服务凭据。',
  ],
  [
    'connections and credentials',
    'managed.secrets.deleteTitle',
    'Delete Connection or Credential',
    '删除连接或凭据',
  ],
  [
    'connections and credentials',
    'managed.search.secrets',
    'Search connections and credentials by name or ID',
    '按名称或 ID 搜索连接与凭据',
  ],
  ['model and service', 'managed.llm.modelConfiguration', 'Model Connection', '模型连接'],
  ['model and service', 'managed.llm.genericSecret', 'Service Credential', '服务凭据'],
  [
    'MCP credential sets',
    'managed.vaults.title',
    'MCP Credential Sets',
    'MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.new',
    'New MCP Credential Set',
    '新建 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.credentials',
    'MCP Credentials',
    'MCP 凭据',
  ],
  [
    'MCP credential sets',
    'managed.vaults.addCredential',
    'Add MCP Bearer Credential',
    '添加 MCP Bearer 凭据',
  ],
  [
    'MCP credential sets',
    'managed.vaults.empty',
    'No MCP credential sets yet.',
    '暂无 MCP 凭据组。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.archiveVault',
    'Archive MCP Credential Set',
    '归档 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.archiveTitle',
    'Archive MCP Credential Set',
    '归档 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.deleteTitle',
    'Delete MCP Credential Set',
    '删除 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.backToVaults',
    'Back to MCP Credential Sets',
    '返回 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.search.vaults',
    'Search MCP credential sets by name, ID, or status',
    '按名称、ID 或状态搜索 MCP 凭据组',
  ],
  [
    'project access tokens',
    'managed.apiKeys.title',
    'Project Access Tokens',
    '项目访问令牌',
  ],
  [
    'project access tokens',
    'managed.apiKeys.subtitle',
    'Manage tokens used by external programs to call this project.',
    '管理外部程序调用当前项目所使用的令牌。',
  ],
  ['project access tokens', 'managed.apiKeys.create', 'Create Token', '创建令牌'],
  [
    'project access tokens',
    'managed.apiKeys.empty',
    'No project access tokens yet.',
    '暂无项目访问令牌。',
  ],
  [
    'project access tokens',
    'managed.apiKeys.revokeTitle',
    'Revoke Project Access Token',
    '撤销项目访问令牌',
  ],
  ['project access tokens', 'managed.apiKeys.revoke', 'Revoke Token', '撤销令牌'],
  [
    'project access tokens',
    'manage.apiKeys.title',
    'Project Access Tokens',
    '项目访问令牌',
  ],
  [
    'project access tokens',
    'manage.apiKeys.subtitle',
    'Manage tokens used by external programs to call this project.',
    '管理外部程序调用当前项目所使用的令牌。',
  ],
  ['project access tokens', 'manage.apiKeys.create', 'Create Token', '创建令牌'],
  [
    'project access tokens',
    'manage.apiKeys.empty',
    'No project access tokens yet.',
    '暂无项目访问令牌。',
  ],
  [
    'project access tokens',
    'manage.apiKeys.revokeTitle',
    'Revoke Project Access Token',
    '撤销项目访问令牌',
  ],
  ['project access tokens', 'manage.apiKeys.revoke', 'Revoke Token', '撤销令牌'],
  [
    'project access tokens',
    'managed.search.apiKeys',
    'Search project access tokens by name, prefix, or role',
    '按名称、前缀或角色搜索项目访问令牌',
  ],
  [
    'triggers',
    'managed.triggers.serviceCredential',
    'Service Credential',
    '服务凭据',
  ],
  [
    'triggers',
    'managed.triggers.serviceCredentialPlaceholder',
    'Select a service credential',
    '选择服务凭据',
  ],
  [
    'triggers',
    'managed.triggers.serviceCredentialUnavailable',
    'This service credential no longer exists. Select another one.',
    '该服务凭据已不存在，请重新选择。',
  ],
  [
    'triggers',
    'managed.triggers.serviceCredentialLoadFailed',
    'Service credentials could not be loaded. Retry before saving.',
    '服务凭据加载失败，请重试后再保存。',
  ],
  ['triggers', 'managed.triggers.credentialField', 'Credential Field', '凭据字段'],
  [
    'triggers',
    'managed.triggers.credentialFieldPlaceholder',
    'Select a credential field',
    '选择凭据字段',
  ],
  [
    'triggers',
    'managed.triggers.credentialFieldUnavailable',
    'This credential field no longer exists. Select another one.',
    '该凭据字段已不存在，请重新选择。',
  ],
  [
    'triggers',
    'managed.triggers.credentialFieldEmpty',
    'This service credential has no fields.',
    '该服务凭据没有可用字段。',
  ],
  ['triggers', 'managed.triggers.credentialFieldCount', '{{count}} fields', '{{count}} 个字段'],
  ['triggers', 'managed.triggers.authMethods', 'Authentication Methods', '认证方式'],
  [
    'environments',
    'managed.environments.egressCredential',
    'Service Credential',
    '服务凭据',
  ],
  [
    'environments',
    'managed.environments.egressCredentialTooltip',
    'Name of the saved service credential. The real token or cookie never enters the sandbox.',
    '平台里保存的服务凭据名称；真实 token 或 cookie 不会进入沙箱。',
  ],
  [
    'environments',
    'managed.environments.egressAuthType',
    'Authentication Method',
    '认证方式',
  ],
  [
    'environments',
    'managed.environments.egressAuthHint',
    'How the platform uses a credential field to authenticate the outbound request.',
    '平台如何使用凭据字段为出站请求生成认证信息。',
  ],
  [
    'environments',
    'managed.environments.egressSecretKey',
    'Credential Field',
    '凭据字段',
  ],
  [
    'environments',
    'managed.environments.egressSelectSecretKey',
    'Select credential field',
    '选择凭据字段',
  ],
  [
    'environments',
    'managed.environments.egressSelectCredential',
    'Select service credential',
    '选择服务凭据',
  ],
  [
    'environments',
    'managed.environments.egressSearchCredential',
    'Search service credentials',
    '搜索服务凭据',
  ],
  [
    'environments',
    'managed.environments.egressNoCredentialFound',
    'No matching service credentials',
    '没有匹配的服务凭据',
  ],
  [
    'environments',
    'managed.environments.egressSecretKeyTooltip',
    'Credential field inside the service credential. Case-sensitive. The platform reads this field and injects its value into the request.',
    '服务凭据里的凭据字段，区分大小写；平台会读取这个字段的值并注入请求。',
  ],
  [
    'environments',
    'managed.environments.egressCookieSecretKeyTooltip',
    'Credential field in the service credential that stores the full Cookie header string. Case-sensitive. For example, COOKIE_HEADER contains thor=...; pin=..., so the injected header is Cookie: <COOKIE_HEADER>.',
    '服务凭据中保存完整 Cookie header 字符串的凭据字段，区分大小写。例如字段 COOKIE_HEADER 的值是 thor=...; pin=...，最终注入 Cookie: <COOKIE_HEADER>。',
  ],
  [
    'environments',
    'managed.environments.egressSecretKeyHint',
    'Credential field inside the selected service credential. Case-sensitive.',
    '所选服务凭据里的凭据字段，区分大小写。',
  ],
  [
    'environments',
    'managed.environments.egressCookieNameTooltip',
    'Credential field that stores the full Cookie header string.',
    '保存完整 Cookie header 字符串的凭据字段。',
  ],
  [
    'environments',
    'managed.environments.validation.cookieRequired',
    'Enter the credential field that stores the full Cookie header string',
    '请填写保存完整 Cookie header 字符串的凭据字段',
  ],
  [
    'sessions',
    'managed.sessions.create.advancedSummary',
    'Runtime environment, MCP credential sets, resources, memory, Git',
    '运行环境、MCP 凭据组、文件资源、Memory、Git',
  ],
  [
    'sessions',
    'managed.sessions.create.vaults',
    'MCP Credential Sets',
    'MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.manageVaults',
    'Manage MCP Credential Sets',
    '管理 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.createVault',
    'Create MCP credential set…',
    '新建 MCP 凭据组…',
  ],
  [
    'sessions',
    'managed.sessions.create.searchVault',
    'Search MCP credential sets by name or ID',
    '按名称或 ID 搜索 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.goToVault',
    'Go to MCP Credential Set',
    '前往 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.resourceKindEnvironment',
    'Environment',
    '环境',
  ],
  [
    'quickstart',
    'managed.quickstart.resourceKindMcpCredentialSet',
    'MCP Credential Set',
    'MCP 凭据组',
  ],
  ['quickstart', 'managed.quickstart.resourceKindAgent', 'Agent', '智能体'],
  [
    'quickstart',
    'managed.quickstart.step.chooseSecret',
    'Choose Model Connection',
    '选择模型连接',
  ],
  [
    'quickstart',
    'managed.quickstart.noApiKey',
    'No Model Connection selected...',
    '尚未选择模型连接...',
  ],
  [
    'quickstart',
    'managed.quickstart.chooseSecret',
    'Complete Step 2 above: choose or create a Model Connection',
    '请在上方完成第二步：选择或创建模型连接',
  ],
  [
    'quickstart',
    'managed.quickstart.noCompatibleSecret',
    'No compatible Model Connection for this engine',
    '当前引擎没有兼容的模型连接',
  ],
  [
    'quickstart',
    'managed.quickstart.secretQuestion',
    'Step 2: Choose a Model Connection',
    '第二步：选择模型连接',
  ],
  [
    'quickstart',
    'managed.quickstart.templateAppliedMessage',
    'Template ready. First, choose a runtime engine below. Then choose a Model Connection before creating the agent.',
    '模板已准备好。第一步，请在下方选择运行引擎；第二步选择模型连接，然后即可创建智能体。',
  ],
  [
    'quickstart',
    'managed.quickstart.engineHint',
    'The runtime engine determines how the agent runs. Choosing one opens Model Connection next.',
    '运行引擎决定智能体由哪种运行时执行。选择后会进入模型连接。',
  ],
  [
    'quickstart',
    'managed.quickstart.secretHint',
    'A Model Connection contains the model and its credentials. Create one here if no compatible Model Connection exists.',
    '模型连接包含模型和访问凭据。如果还没有兼容模型连接，可以在这里立即创建。',
  ],
  [
    'quickstart',
    'managed.quickstart.step.configureVault',
    'Configure MCP Credential Set',
    '配置 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.createThisVault',
    'Create this MCP Credential Set',
    '创建此 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.nextConfigureVault',
    'Next: Configure MCP Credential Set',
    '下一步：配置 MCP 凭据组 →',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultIntro',
    'If this agent uses MCP servers that require credentials, it needs an MCP credential set to store them. An MCP credential set is a workspace-level MCP server credential store that sessions reference by ID at creation -- think of it as a secure keychain.',
    '如果此智能体使用需要凭据的 MCP 服务器，它需要一个 MCP 凭据组来存储这些凭据。MCP 凭据组是工作区级别的 MCP 服务器凭据存储，会话在创建时通过 ID 引用它 —— 可以把它看作一个安全的钥匙链。',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultReuseOrCreate',
    'Which MCP credential set do you want to use to store MCP credentials?',
    '你想使用哪个 MCP 凭据组来存储 MCP 凭据？',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultCreateNew',
    'Create New MCP Credential Set',
    '创建新 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultNameQuestion',
    'What would you like to name this MCP credential set?',
    '你想给这个 MCP 凭据组起什么名字？',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultNamePlaceholder',
    'e.g. production-mcp-credential-set',
    '例如 production-mcp-credential-set',
  ],
  [
    'quickstart',
    'managed.quickstart.createVault',
    'Create MCP Credential Set',
    '创建 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.errors.createVaultFailed',
    'Failed to create MCP credential set',
    '创建 MCP 凭据组失败',
  ],
  [
    'quickstart',
    'managed.quickstart.errors.vaultConfigMissing',
    'MCP credential set configuration not found',
    '未找到 MCP 凭据组配置',
  ],
  [
    'quickstart',
    'managed.quickstart.stepComplete.vaultCreated',
    'MCP Credential Set Configured',
    'MCP 凭据组已配置',
  ],
  [
    'quickstart',
    'managed.quickstart.stepDesc.4',
    'MCP Credential Set configured! An MCP credential set is a workspace-level MCP server credential store that sessions reference by ID at creation -- enabling the same authorized connection to be reused across multiple sessions.',
    'MCP 凭据组已配置！MCP 凭据组是工作区级别的 MCP 服务器凭据存储，会话在创建时通过 ID 引用它 —— 让同一授权连接可在多个会话间复用。',
  ],
  [
    'Vault static Bearer',
    'managed.vaults.cred.createTitle',
    'Add MCP Bearer Credential',
    '添加 MCP Bearer 凭据',
  ],
  [
    'Vault static Bearer',
    'managed.vaults.cred.createDescription',
    'Store a Bearer token for one MCP server in this credential set.',
    '在当前 MCP 凭据组中保存一个 MCP Server 的 Bearer Token。',
  ],
  ['Vault static Bearer', 'managed.vaults.cred.token', 'Bearer Token', 'Bearer Token'],
  [
    'Vault static Bearer',
    'managed.vaults.cred.tokenPlaceholder',
    'Enter Bearer token',
    '输入 Bearer Token',
  ],
  ['Vault static Bearer', 'managed.vaults.cred.adding', 'Adding…', '添加中…'],
  ['Vault static Bearer', 'managed.vaults.cred.add', 'Add Credential', '添加凭据'],
]

const apiKeyFields = ['title', 'subtitle', 'create', 'empty', 'revokeTitle', 'revoke'] as const

const quickstartModelConnectionPaths = [
  'managed.quickstart.step.chooseSecret',
  'managed.quickstart.noApiKey',
  'managed.quickstart.chooseSecret',
  'managed.quickstart.noCompatibleSecret',
  'managed.quickstart.secretQuestion',
  'managed.quickstart.templateAppliedMessage',
  'managed.quickstart.engineHint',
  'managed.quickstart.secretHint',
] as const

const quickstartMcpCredentialSetPaths = [
  'managed.quickstart.step.configureVault',
  'managed.quickstart.createThisVault',
  'managed.quickstart.nextConfigureVault',
  'managed.quickstart.vaultIntro',
  'managed.quickstart.vaultReuseOrCreate',
  'managed.quickstart.vaultCreateNew',
  'managed.quickstart.vaultNameQuestion',
  'managed.quickstart.vaultNamePlaceholder',
  'managed.quickstart.createVault',
  'managed.quickstart.errors.createVaultFailed',
  'managed.quickstart.errors.vaultConfigMissing',
  'managed.quickstart.stepComplete.vaultCreated',
  'managed.quickstart.stepDesc.4',
] as const

function getTranslationValue(root: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((value, key) => {
    if (typeof value !== 'object' || value === null) return undefined
    return (value as Record<string, unknown>)[key]
  }, root)
}

describe('credential domain terminology', () => {
  it.each(terminologyExpectations)(
    'uses exact English %s copy for %s',
    (_category, path, english) => {
      expect(getTranslationValue(en.translation, path)).toBe(english)
    },
  )

  it.each(terminologyExpectations)(
    'uses exact Chinese %s copy for %s',
    (_category, path, _english, chinese) => {
      expect(getTranslationValue(zh.translation, path)).toBe(chinese)
    },
  )

  it.each(apiKeyFields)('keeps managed and production API token copy synchronized for %s', (field) => {
    expect(en.translation.managed.apiKeys[field]).toBe(en.translation.manage.apiKeys[field])
    expect(zh.translation.managed.apiKeys[field]).toBe(zh.translation.manage.apiKeys[field])
  })

  it.each(quickstartModelConnectionPaths)(
    'removes legacy model-configuration nouns from Quickstart %s',
    (path) => {
      expect(getTranslationValue(en.translation, path)).not.toMatch(/\bmodel configurations?\b/i)
      expect(getTranslationValue(zh.translation, path)).not.toMatch(/模型配置/)
    },
  )

  it.each(quickstartMcpCredentialSetPaths)(
    'removes legacy Vault nouns from Quickstart %s',
    (path) => {
      expect(getTranslationValue(en.translation, path)).not.toMatch(/\bvaults?\b/i)
      expect(getTranslationValue(zh.translation, path)).not.toMatch(/凭[据证]库/)
    },
  )
})
