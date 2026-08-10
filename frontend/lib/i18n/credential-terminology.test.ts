import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

import { createInstance } from 'i18next'
import ts from 'typescript'
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
  ['agent model connection', 'agents.edit.secretRef', 'Model Connection', '模型连接'],
  [
    'agent model connection',
    'managed.agents.engineKindDesc',
    'The engine determines the supported API protocols. Model Connections are filtered to compatible Provider and Protocol combinations.',
    '引擎决定支持哪些 API 协议；模型连接会按兼容的 Provider 与 Protocol 组合自动筛选。',
  ],
  [
    'agent model connection',
    'managed.agents.edit.secretRef',
    'Model Connection',
    '模型连接',
  ],
  [
    'model connection states',
    'managed.llm.catalogIdentityUnavailable',
    'This Model Connection references a provider or protocol that is no longer available in the current catalog. Create a new Model Connection before using it.',
    '该模型连接引用的供应商或协议已不在当前目录中，现为只读状态。请新建可用的模型连接后再替换使用。',
  ],
  [
    'model connection states',
    'managed.llm.chooseEngineFirst',
    'Choose an engine first to see compatible Model Connections.',
    '请先选择引擎，再查看兼容的模型连接。',
  ],
  ['model connection states', 'managed.llm.configuration', 'Model Connection', '模型连接'],
  [
    'model connection states',
    'managed.llm.configurationLoadFailed',
    'Failed to load compatible Model Connections.',
    '加载兼容模型连接失败。',
  ],
  [
    'model connection states',
    'managed.llm.createConfiguration',
    'Create Model Connection',
    '创建模型连接',
  ],
  [
    'model connection states',
    'managed.llm.createDialogDescription',
    'Create a Model Connection or Service Credential for this project.',
    '为当前项目创建模型连接或服务凭据。',
  ],
  [
    'model connection states',
    'managed.llm.createFailed',
    'Failed to create the Model Connection.',
    '创建模型连接失败。',
  ],
  [
    'model connection states',
    'managed.llm.incompatibleWithSelectedEngine',
    'The current Model Connection does not support the selected engine.',
    '当前模型连接不支持所选引擎。',
  ],
  [
    'model connection states',
    'managed.llm.loadingConfigurations',
    'Loading compatible Model Connections...',
    '正在加载兼容模型连接...',
  ],
  [
    'model connection states',
    'managed.llm.noCompatibleConfigurations',
    'No compatible Model Connections',
    '暂无兼容的模型连接',
  ],
  [
    'model connection states',
    'managed.llm.previousConfigurationIncompatible',
    'The previous Model Connection is not compatible with this engine and was cleared. Choose another Model Connection or create one.',
    '原模型连接不兼容当前引擎，已为你清空。请选择其他模型连接或新建模型连接。',
  ],
  [
    'model connection states',
    'managed.llm.reselectConfiguration',
    'Choose another Model Connection',
    '重新选择模型连接',
  ],
  [
    'model connection states',
    'managed.llm.noConfigurationHint',
    'Do not bind a Model Connection. The agent will not receive model credentials from Connections & Credentials.',
    '不绑定模型连接；系统不会从连接与凭据中向该智能体注入模型凭据。',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.forbidden.title',
    'No access to this MCP credential set',
    '无权访问此 MCP 凭据组',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.forbidden.description',
    'MCP credential set access requires write-level project access. Ask an organization admin or owner to grant access.',
    '查看 MCP 凭据组需要项目写入权限。请联系组织管理员或所有者为你开通权限。',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.notFound.title',
    'MCP credential set not found',
    'MCP 凭据组未找到',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.notFound.description',
    'This MCP credential set may have been deleted, archived, or the link is no longer valid.',
    '此 MCP 凭据组可能已被删除、归档，或当前链接已失效。',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.unknown.title',
    'Could not load MCP credential set',
    '无法加载 MCP 凭据组',
  ],
  [
    'MCP credential set errors',
    'managed.errorStates.vault.unknown.description',
    'We could not load this MCP credential set right now. Please retry or check your connection.',
    '暂时无法加载此 MCP 凭据组。请重试，或检查网络连接。',
  ],
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
    'managed.vaults.subtitle',
    'Manage MCP credential sets that give agents access to MCP servers and other tools.',
    '管理 MCP 凭据组，为智能体提供访问 MCP 服务器和其他工具的权限。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.createTitle',
    'Create MCP Credential Set',
    '创建 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.createDescription',
    'Create a new MCP credential set.',
    '创建新的 MCP 凭据组。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.sharedWarning',
    'MCP credential sets are shared across this organization. Credentials added to this set can be used by anyone with Project Access Token access.',
    'MCP 凭据组在当前组织内共享。添加到此凭据组的凭据可供任何拥有项目访问令牌权限的成员使用。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.namePlaceholder',
    'Production MCP Credential Set',
    '生产 MCP 凭据组',
  ],
  [
    'MCP credential sets',
    'managed.vaults.createFailed',
    'Failed to create MCP credential set. Please try again.',
    '创建 MCP 凭据组失败，请重试。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.archiveDescription',
    'Are you sure you want to archive "{{name}}"? Credentials in this MCP credential set will no longer be available to agents.',
    '确定要归档 "{{name}}" 吗？此 MCP 凭据组中的凭据将不再对智能体可用。',
  ],
  [
    'MCP credential sets',
    'managed.vaults.noCredentials',
    'No MCP credentials in this credential set yet.',
    '此 MCP 凭据组暂无 MCP 凭据。',
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
    'managed.sessions.create.noVaults',
    'No MCP credential sets available',
    '暂无可用 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.noVaultMatch',
    'No matching MCP credential sets',
    '没有匹配的 MCP 凭据组',
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
  [
    'agent model connection',
    'agents.edit.selectSecret',
    'Select a Model Connection',
    '选择模型连接',
  ],
  [
    'agent model connection',
    'agents.edit.searchSecret',
    'Search Model Connections',
    '搜索模型连接',
  ],
  [
    'agent model connection',
    'agents.edit.noSecretMatch',
    'No matching Model Connections',
    '没有匹配的模型连接',
  ],
  [
    'agent model connection',
    'agents.edit.createSecret',
    'Create Model Connection…',
    '新建模型连接…',
  ],
  [
    'agent model connection',
    'managed.agents.edit.selectSecret',
    'Select a Model Connection',
    '选择模型连接',
  ],
  [
    'agent model connection',
    'managed.agents.edit.searchSecret',
    'Search Model Connections',
    '搜索模型连接',
  ],
  [
    'agent model connection',
    'managed.agents.edit.noSecretMatch',
    'No matching Model Connections',
    '没有匹配的模型连接',
  ],
  [
    'agent model connection',
    'managed.agents.edit.createSecret',
    'Create Model Connection…',
    '新建模型连接…',
  ],
  [
    'agent model connection',
    'managed.agents.basicSettingsDesc',
    'Set the agent name, model connection, engine, and system prompt.',
    '设置智能体名称、模型连接、引擎和系统提示词。',
  ],
  [
    'agent model connection',
    'managed.skills.aiAuthor.noSecrets',
    'No model connections available',
    '暂无可用模型连接',
  ],
  [
    'model connection states',
    'managed.llm.configurationName',
    'Name',
    '名称',
  ],
  ['model connection states', 'managed.llm.configurationType', 'Type', '类型'],
  ['model connection states', 'managed.llm.nameRequired', 'Enter a name.', '请输入名称。'],
  [
    'model connection states',
    'managed.llm.engineFilterHint',
    'Used only to filter compatible protocols; it does not bind this Model Connection to one engine.',
    '仅用于筛选兼容协议，不会把此模型连接绑定到单个引擎。',
  ],
  [
    'model connection states',
    'managed.llm.noCompatibleConfigurationsHint',
    'Create one here using a provider and protocol supported by this engine.',
    '可在此使用该引擎支持的供应商与协议创建模型连接。',
  ],
  [
    'model connection states',
    'managed.llm.setAsProtocolDefault',
    'Set as default for this protocol',
    '设为该协议的默认模型连接',
  ],
  [
    'service credential fields',
    'managed.llm.genericKey',
    'Credential Field',
    '凭据字段',
  ],
  [
    'service credential fields',
    'managed.llm.genericPairRequired',
    'Add at least one non-empty credential field and value.',
    '请至少添加一组非空凭据字段和值。',
  ],
  [
    'service credential fields',
    'managed.llm.genericValuePlaceholder',
    'Credential value',
    '凭据值',
  ],
  [
    'service credentials',
    'managed.environments.egressCreateSecretOption',
    'Create a service credential…',
    '去创建服务凭据…',
  ],
  [
    'service credentials',
    'managed.environments.egressAllowedPathsHint',
    'One path per line. A trailing / means prefix match (everything under it); otherwise exact match (that endpoint only). Leave empty = allow every endpoint under this address; for high-privilege service credentials, list paths explicitly to prevent unintended access.',
    '一行一个路径。以 / 结尾为前缀匹配（该目录下全部），否则为精确匹配（仅该接口）。留空 = 放行该地址下所有接口；高权限服务凭据建议逐条列出以防越权。',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.forbidden.title',
    'No access to this connection or credential',
    '无权访问此连接或凭据',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.forbidden.description',
    'Connection and credential values require write-level project access. Ask an organization admin or owner to grant access.',
    '查看连接或凭据内容需要项目写入权限。请联系组织管理员或所有者为你开通权限。',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.notFound.title',
    'Connection or credential not found',
    '连接或凭据未找到',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.notFound.description',
    'This connection or credential may have been deleted, archived, or the link is no longer valid.',
    '此连接或凭据可能已被删除、归档，或当前链接已失效。',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.unknown.title',
    'Could not load connection or credential',
    '无法加载连接或凭据',
  ],
  [
    'connections and credentials errors',
    'managed.errorStates.secret.unknown.description',
    'We could not load this connection or credential right now. Please retry or check your connection.',
    '暂时无法加载此连接或凭据。请重试，或检查网络连接。',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.forbidden.title',
    'No access to project access tokens',
    '无权访问项目访问令牌',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.forbidden.description',
    'You do not have permission to view or manage project access tokens. Ask an organization admin or owner for access.',
    '你没有权限查看或管理项目访问令牌，请联系组织管理员或所有者。',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.notFound.title',
    'Project access token not found',
    '项目访问令牌未找到',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.notFound.description',
    'This project access token may have been deleted, or the link is no longer valid.',
    '该项目访问令牌可能已被删除，或当前链接已失效。',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.unknown.title',
    'Could not load project access tokens',
    '无法加载项目访问令牌',
  ],
  [
    'project access token errors',
    'managed.errorStates.apiKey.unknown.description',
    'We could not load project access tokens right now. Please retry or check your connection.',
    '暂时无法加载项目访问令牌，请稍后重试。',
  ],
  [
    'project access tokens',
    'manage.apiKeys.namePlaceholder',
    'Enter token name',
    '输入令牌名称',
  ],
  [
    'project access tokens',
    'manage.apiKeys.newKeyWarning',
    "Copy this project access token now. You won't be able to see it again.",
    '请立即复制此项目访问令牌，关闭后将无法再次查看。',
  ],
  [
    'project access tokens',
    'manage.apiKeys.revokeDesc',
    'This project access token will be immediately invalidated. All requests using it will be rejected. This cannot be undone.',
    '撤销后此项目访问令牌将立即失效，使用该令牌的所有请求将被拒绝。此操作不可撤销。',
  ],
  [
    'sessions',
    'managed.sessions.credentials',
    'MCP Credentials',
    'MCP 凭据',
  ],
  [
    'sessions',
    'managed.sessions.noCredentials',
    'No MCP credentials configured.',
    '未配置 MCP 凭据。',
  ],
  [
    'sessions',
    'managed.sessions.mcpCredentialSetCount_one',
    '{{count}} MCP credential set',
    '{{count}} 个 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.mcpCredentialSetCount_other',
    '{{count}} MCP credential sets',
    '{{count}} 个 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.stepComplete.secretSelected',
    'Model Connection Selected',
    '模型连接已选择',
  ],
  [
    'quickstart',
    'managed.quickstart.stepDesc.1',
    'Model Connection selected. The Agent will use this connection for model, endpoint, and API key settings at runtime.',
    '模型连接已选择。这个 Agent 运行时会从该模型连接读取模型、接口地址和 API Key 设置。',
  ],
  [
    'quickstart',
    'managed.quickstart.autoIntro.mcpCredentialSetQuestion',
    'What MCP credential set does my agent need for MCP server credentials?',
    '我的智能体需要怎样的 MCP 凭据组来保存 MCP 服务器凭据？',
  ],
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

const frontendRoot = path.resolve(process.cwd())
const productionSourceRoots = ['app', 'components', 'hooks'].map((directory) =>
  path.join(frontendRoot, directory),
)
const excludedSourcePath = /(?:^|\/)(?:__generated__|generated)(?:\/|$)/
const excludedSourceFile = /\.(?:test|spec|stories)\.[cm]?[jt]sx?$/
const sourceFilePattern = /\.[cm]?[jt]sx?$/
const legacySourcePatterns = [
  /\bmodel secrets?\b/i,
  /\bmodel configurations?\b/i,
  /\bagent secrets?\b/i,
  /模型配置|模型密钥|智能体密钥|Agent 密钥/u,
  /\bvault configuration\b/i,
  /^\$\{…\}\s+vaults?$/i,
] as const

function collectProductionSourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const absolutePath = path.join(directory, entry)
    const relativePath = path.relative(frontendRoot, absolutePath)
    if (excludedSourcePath.test(relativePath)) return []
    if (statSync(absolutePath).isDirectory()) return collectProductionSourceFiles(absolutePath)
    if (!sourceFilePattern.test(entry) || excludedSourceFile.test(entry)) return []
    return [absolutePath]
  })
}

function templateLiteralText(node: ts.TemplateExpression): string {
  return node.templateSpans.reduce(
    (value, span) => `${value}\${…}${span.literal.text}`,
    node.head.text,
  )
}

function findHardCodedLegacyCredentialCopy(): string[] {
  const violations: string[] = []
  for (const file of productionSourceRoots.flatMap(collectProductionSourceFiles)) {
    const source = readFileSync(file, 'utf8')
    const sourceFile = ts.createSourceFile(
      file,
      source,
      ts.ScriptTarget.Latest,
      true,
      file.endsWith('x') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    )

    function visit(node: ts.Node) {
      let text: string | undefined
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) text = node.text
      if (ts.isTemplateExpression(node)) text = templateLiteralText(node)
      if (ts.isJsxText(node)) text = node.getText(sourceFile).trim()
      if (text && legacySourcePatterns.some((pattern) => pattern.test(text))) {
        const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile))
        violations.push(
          `${path.relative(frontendRoot, file)}:${position.line + 1}:${position.character + 1} ${JSON.stringify(text)}`,
        )
      }
      ts.forEachChild(node, visit)
    }

    visit(sourceFile)
  }
  return violations
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

  it('interpolates singular and plural MCP Credential Set counts in both locales', async () => {
    const instance = createInstance()
    await instance.init({
      lng: 'en',
      fallbackLng: false,
      resources: { en, zh },
      interpolation: { escapeValue: false },
    })

    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 1 })).toBe(
      '1 MCP credential set',
    )
    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 2 })).toBe(
      '2 MCP credential sets',
    )

    await instance.changeLanguage('zh')
    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 1 })).toBe(
      '1 个 MCP 凭据组',
    )
    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 2 })).toBe(
      '2 个 MCP 凭据组',
    )
  })

  it('keeps hard-coded production copy free of legacy credential nouns', () => {
    expect(findHardCodedLegacyCredentialCopy()).toEqual([])
  })
})
