import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'

import { createInstance } from 'i18next'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import { buildActiveTranslationInventory } from './active-translation-inventory.test-support'
import en from './locales/en'
import zh from './locales/zh'

type TerminologyExpectation = readonly [
  category: string,
  path: string,
  english: string,
  chinese: string,
]

const terminologyExpectations: readonly TerminologyExpectation[] = [
  ['navigation', 'nav.vaults', 'MCP Credential Groups', 'MCP 凭据组'],
  ['navigation', 'nav.apiKeys', 'Project Access Tokens', '项目访问令牌'],
  [
    'connections and credentials',
    'managed.secrets.new',
    'New Connection or Credential',
    '新建连接或凭据',
  ],
  ['connections and credentials', 'managed.secrets.dataLabel', 'Credential Fields', '凭据字段'],
  [
    'connections and credentials',
    'managed.secrets.deleteTitle',
    'Delete Connection or Credential',
    '删除连接或凭据',
  ],
  [
    'connections and credentials',
    'managed.search.secrets',
    'Search credentials by name or ID',
    '按名称或 ID 搜索凭据',
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
  ['agent model connection', 'managed.agents.edit.secretRef', 'Model Connection', '模型连接'],
  [
    'model connection states',
    'managed.llm.catalogIdentityUnavailable',
    'The provider or protocol used by this Model Connection is no longer supported, so it is read-only. Create a new Model Connection to replace it.',
    '该模型连接使用的供应商或协议已不再受支持，当前仅可查看、无法编辑。请新建一条模型连接来替换它。',
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
    'Do not bind a Model Connection. The agent will not receive model credentials.',
    '不绑定模型连接；系统不会向该智能体注入模型凭据。',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.forbidden.title',
    'No access to this MCP credential group',
    '无权访问此 MCP 凭据组',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.forbidden.description',
    'MCP credential group access requires write-level project access. Ask an organization admin or owner to grant access.',
    '查看 MCP 凭据组需要项目写入权限。请联系组织管理员或所有者为你开通权限。',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.notFound.title',
    'MCP credential group not found',
    'MCP 凭据组未找到',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.notFound.description',
    'This MCP credential group may have been deleted, archived, or the link is no longer valid.',
    '此 MCP 凭据组可能已被删除、归档，或当前链接已失效。',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.unknown.title',
    'Could not load MCP credential group',
    '无法加载 MCP 凭据组',
  ],
  [
    'MCP credential group errors',
    'managed.errorStates.vault.unknown.description',
    'We could not load this MCP credential group right now. Please retry or check your connection.',
    '暂时无法加载此 MCP 凭据组。请重试，或检查网络连接。',
  ],
  ['MCP credential groups', 'managed.vaults.title', 'MCP Credential Groups', 'MCP 凭据组'],
  ['MCP credential groups', 'managed.vaults.new', 'New MCP Credential Group', '新建 MCP 凭据组'],
  ['MCP credential groups', 'managed.vaults.credentials', 'MCP Credentials', 'MCP 凭据'],
  [
    'MCP credential groups',
    'managed.vaults.addCredential',
    'Add MCP Bearer Credential',
    '添加 MCP Bearer 凭据',
  ],
  [
    'MCP credential groups',
    'managed.vaults.empty',
    'No MCP credential groups yet.',
    '暂无 MCP 凭据组。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.archiveVault',
    'Archive MCP Credential Group',
    '归档 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.archiveTitle',
    'Archive MCP Credential Group',
    '归档 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.deleteTitle',
    'Delete MCP Credential Group',
    '删除 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.backToVaults',
    'Back to MCP Credential Groups',
    '返回 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.subtitle',
    'Manage MCP credential groups that give agents access to MCP servers and other tools.',
    '管理 MCP 凭据组，为智能体提供访问 MCP 服务器和其他工具的权限。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.createTitle',
    'Create MCP Credential Group',
    '创建 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.createDescription',
    'Create a new MCP credential group.',
    '创建新的 MCP 凭据组。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.sharedWarning',
    'MCP credential groups are shared within the current project. Access and management require appropriate project permissions.',
    'MCP 凭据组在当前项目内共享，访问和管理需要相应的项目权限。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.namePlaceholder',
    'Production MCP Credential Group',
    '生产 MCP 凭据组',
  ],
  [
    'MCP credential groups',
    'managed.vaults.createFailed',
    'Failed to create MCP credential group. Please try again.',
    '创建 MCP 凭据组失败，请重试。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.archiveDescription',
    'Are you sure you want to archive "{{name}}"? Credentials in this MCP credential group will no longer be available to agents.',
    '确定要归档 "{{name}}" 吗？此 MCP 凭据组中的凭据将不再对智能体可用。',
  ],
  [
    'MCP credential groups',
    'managed.vaults.noCredentials',
    'No MCP credentials in this credential group yet.',
    '此 MCP 凭据组暂无 MCP 凭据。',
  ],
  [
    'MCP credential groups',
    'managed.search.vaults',
    'Search MCP credential groups by name, ID, or status',
    '按名称、ID 或状态搜索 MCP 凭据组',
  ],
  ['project access tokens', 'managed.apiKeys.title', 'Project Access Tokens', '项目访问令牌'],
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
  ['project access tokens', 'manage.apiKeys.title', 'Project Access Tokens', '项目访问令牌'],
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
  ['triggers', 'managed.triggers.serviceCredential', 'Service Credential', '服务凭据'],
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
    'managed.environments.envVarsHint',
    'Non-sensitive environment variables injected into the sandbox. Format: KEY=value, separated by commas or new lines. Do not enter tokens, cookies, API keys, or other sensitive values; store them in a Service Credential instead.',
    '注入到沙箱的非敏感环境变量。格式：KEY=value，逗号或换行分隔。不要填写 token、cookie、API key 等敏感值；请改存到服务凭据中。',
  ],
  [
    'environments',
    'managed.environments.egressServicesHint',
    'Skills call the real service URL directly; authentication values derived from the selected Service Credential are applied automatically and never exposed to the sandbox.',
    'Skill 直接使用真实服务地址访问；平台会自动应用基于所选服务凭据生成的认证值，且不会将这些值暴露给沙箱。',
  ],
  [
    'environments',
    'managed.environments.egressBaseUrlHint',
    'The real third-party endpoint (with https). In your skill use http:// for the same address; the platform authenticates the request at the gateway using the selected Service Credential, then re-originates to https.',
    '填写第三方接口的真实地址（含 https）。skill 内改用 http 访问同一地址；平台会在网关使用所选服务凭据对请求进行认证，然后回源到 https。',
  ],
  [
    'environments',
    'managed.environments.egressSectionCredential',
    'Service Credential',
    '服务凭据',
  ],
  [
    'environments',
    'managed.environments.egressSkillExampleHint',
    'Use this address in your skill; authentication derived from the selected Service Credential is applied automatically.',
    '在 skill 中使用此地址访问；平台会自动应用基于所选服务凭据生成的认证信息。',
  ],
  ['environments', 'managed.environments.egressCredential', 'Service Credential', '服务凭据'],
  [
    'environments',
    'managed.environments.egressCredentialTooltip',
    'Name of the saved service credential. The real token or cookie never enters the sandbox.',
    '平台里保存的服务凭据名称；真实 token 或 cookie 不会进入沙箱。',
  ],
  ['environments', 'managed.environments.egressAuthType', 'Authentication Method', '认证方式'],
  [
    'environments',
    'managed.environments.egressAuthHint',
    'How the platform uses a credential field to authenticate the outbound request.',
    '平台如何使用凭据字段为出站请求生成认证信息。',
  ],
  ['environments', 'managed.environments.egressSecretKey', 'Credential Field', '凭据字段'],
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
    'Runtime environment, MCP credential groups, resources, memory, Git',
    '运行环境、MCP 凭据组、文件资源、Memory、Git',
  ],
  ['sessions', 'managed.sessions.create.vaults', 'MCP Credential Groups', 'MCP 凭据组'],
  [
    'sessions',
    'managed.sessions.create.manageVaults',
    'Manage MCP Credential Groups',
    '管理 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.createVault',
    'Create MCP credential group…',
    '新建 MCP 凭据组…',
  ],
  [
    'sessions',
    'managed.sessions.create.searchVault',
    'Search MCP credential groups by name or ID',
    '按名称或 ID 搜索 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.noVaults',
    'No MCP credential groups available',
    '暂无可用 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.create.noVaultMatch',
    'No matching MCP credential groups',
    '没有匹配的 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.goToCredentialGroup',
    'Go to MCP Credential Group',
    '前往 MCP 凭据组',
  ],
  ['quickstart', 'managed.quickstart.resourceKindEnvironment', 'Environment', '环境'],
  [
    'quickstart',
    'managed.quickstart.resourceKindMcpCredentialSet',
    'MCP Credential Group',
    'MCP 凭据组',
  ],
  ['quickstart', 'managed.quickstart.resourceKindAgent', 'Agent', '智能体'],
  ['quickstart', 'managed.quickstart.step.chooseSecret', 'Secure Model Connection', '安全模型连接'],
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
    'Step 2: Secure Model Connection',
    '第二步：安全模型连接',
  ],
  [
    'quickstart',
    'managed.quickstart.templateAppliedMessage',
    'Template ready. JoySafeter recommended a runtime and security defaults; confirm the secure Model Connection, then create the agent.',
    '模板已准备好。JoySafeter 已推荐运行时和安全默认值；确认安全模型连接后即可创建智能体。',
  ],
  [
    'quickstart',
    'managed.quickstart.engineHint',
    'The runtime engine determines how the agent runs. Choosing one opens Model Connection next.',
    '运行引擎决定智能体由哪种运行时执行。选择后会进入模型连接。',
  ],
  [
    'quickstart',
    'managed.quickstart.engineRecommendation.title',
    'Choose a runtime before JoySafeter continues',
    '继续前请选择运行引擎',
  ],
  [
    'quickstart',
    'managed.quickstart.engineRecommendation.description',
    'Based on your description, JoySafeter recommends one runtime. Confirm it or pick another option before we create the Model Connection flow.',
    'JoySafeter 会根据你的描述给出推荐，但不会替你确认。确认推荐或改选其他引擎后，再进入模型连接流程。',
  ],
  [
    'quickstart',
    'managed.quickstart.engineRecommendation.useRecommended',
    'Use {{engine}}',
    '使用 {{engine}}',
  ],
  [
    'quickstart',
    'managed.quickstart.secretHint',
    'A Model Connection stores model credentials securely and injects them at runtime by project policy.',
    '模型连接会安全保存模型凭据，并按项目策略在运行时注入。',
  ],
  [
    'quickstart',
    'managed.quickstart.useSelectedModelConnection',
    'Use selected Model Connection',
    '使用已选模型连接',
  ],
  [
    'quickstart safety',
    'managed.quickstart.safety.sandbox.title',
    'Controlled sandbox',
    '受控沙箱',
  ],
  [
    'quickstart safety',
    'managed.quickstart.safety.credentials.title',
    'Credential isolation',
    '凭据隔离',
  ],
  [
    'quickstart safety',
    'managed.quickstart.safety.permissions.title',
    'Least privilege',
    '最小权限',
  ],
  ['quickstart safety', 'managed.quickstart.safety.audit.title', 'Auditable session', '可审计会话'],
  [
    'quickstart safety',
    'managed.quickstart.templateSecurityHint',
    'Secure defaults: sandbox, credential isolation, least privilege, audit.',
    '安全默认值：沙箱、凭据隔离、最小权限、审计。',
  ],
  [
    'quickstart recommendation',
    'managed.quickstart.modelRecommendation.title',
    'JoySafeter recommends this secure Model Connection',
    'JoySafeter 推荐这个安全模型连接',
  ],
  [
    'quickstart recommendation',
    'managed.quickstart.modelRecommendation.reason.preferredProtocolDefault',
    "It is the protocol default and matches this runtime's preferred protocol.",
    '它是协议默认连接，并匹配当前运行时的首选协议。',
  ],
  [
    'quickstart',
    'managed.quickstart.step.configureVault',
    'Authorize External Tools',
    '授权外部工具',
  ],
  ['quickstart', 'managed.quickstart.createThisVault', 'Authorize external tools', '授权外部工具'],
  [
    'quickstart',
    'managed.quickstart.nextConfigureVault',
    'Next: Authorize External Tools',
    '下一步：授权外部工具 →',
  ],
  [
    'quickstart',
    'managed.quickstart.nextConfigureEnv',
    'Next: Configure Security Environment',
    '下一步：配置安全环境 →',
  ],
  [
    'quickstart',
    'managed.quickstart.nextStartSession',
    'Next: Secure Launch',
    '下一步：安全启动 →',
  ],
  [
    'quickstart',
    'managed.quickstart.readyToStart',
    'Agent ready -- review the JoySafeter safety plan before launch.',
    '智能体已就绪 — 启动前请确认 JoySafeter 安全计划。',
  ],
  [
    'quickstart',
    'managed.quickstart.envIntro',
    'A security environment is the controlled sandbox where JoySafeter runs agent tools. Use it to limit network egress to the services this agent actually needs.',
    '安全环境是 JoySafeter 运行智能体工具的受控沙箱。你可以用它把网络出口限制在此智能体真正需要访问的服务上。',
  ],
  [
    'quickstart',
    'managed.quickstart.createEnvironment',
    'Create Security Environment',
    '创建安全环境',
  ],
  [
    'quickstart smart defaults',
    'managed.quickstart.smartDefaults.allowlist.title',
    'JoySafeter suggested allowlist',
    'JoySafeter 推荐 allowlist',
  ],
  [
    'quickstart smart defaults',
    'managed.quickstart.smartDefaults.allowlist.reason.knownServices',
    'Detected common services from your intent and translated them into narrow host rules.',
    '已从你的意图中识别常见服务，并转换成更窄的主机规则。',
  ],
  [
    'quickstart smart defaults',
    'managed.quickstart.smartDefaults.externalTools.title',
    'JoySafeter external tool recommendation',
    'JoySafeter 外部工具建议',
  ],
  [
    'quickstart smart defaults',
    'managed.quickstart.smartDefaults.externalTools.reason.mcpServers',
    'This Agent configuration includes MCP servers, so authorize only the credential group it needs.',
    '这个智能体配置包含 MCP Server，因此只应授权它需要的凭据组。',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.title',
    'JoySafeter Safety Plan',
    'JoySafeter 安全计划',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.description',
    'Review and adjust these controls before the first session starts.',
    '首次会话启动前，请确认并按需调整这些控制项。',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.externalTools',
    'External tool credentials',
    '外部工具凭据',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.hint.modelConnection',
    'Changing the Model Connection rebuilds the Agent with new model credentials.',
    '更换模型连接会用新的模型凭据重新创建智能体。',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.hint.noExternalTools',
    'Launch stays isolated from MCP tools until you authorize a credential group.',
    '未授权凭据组前，会话不会接入 MCP 外部工具。',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.action.changeModelConnection',
    'Change Model Connection',
    '更换模型连接',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.action.authorizeTools',
    'Authorize',
    '授权',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.summary.hardening',
    'Hardening recommended',
    '建议加固',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.summary.hardeningDescription',
    'Add a controlled security environment to enforce network egress before the first run.',
    '建议在首次运行前添加受控安全环境，以强制执行网络出口控制。',
  ],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.status.recommended',
    'Recommended',
    '建议',
  ],
  ['quickstart safety plan', 'managed.quickstart.safetyPlan.status.isolated', 'Isolated', '隔离中'],
  [
    'quickstart safety plan',
    'managed.quickstart.safetyPlan.launchHint.hardening',
    'You can still launch, but JoySafeter recommends adding a security environment for stronger network control.',
    '仍可继续启动，但 JoySafeter 建议添加安全环境以获得更强的网络控制。',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultIntro',
    'Authorize external tools only when this agent needs MCP servers with credentials. JoySafeter stores those MCP credentials in a credential group and attaches the group by ID at launch.',
    '仅当这个智能体需要带凭据的 MCP Server 时才授权外部工具。JoySafeter 会把这些 MCP 凭据保存在凭据组中，并在启动时按 ID 附加。',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultReuseOrCreate',
    'Which MCP credential group should JoySafeter authorize for this agent?',
    'JoySafeter 应该为这个智能体授权哪个 MCP 凭据组？',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultCreateNew',
    'Authorize New MCP Credential Group',
    '授权新 MCP 凭据组',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultNameQuestion',
    'What should we call this external tool authorization group?',
    '这个外部工具授权组应该叫什么？',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultNamePlaceholder',
    'e.g. production-mcp-credential-vault',
    '例如 production-mcp-credential-vault',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultCredentialTitle',
    'Add the MCP credential now',
    '现在添加 MCP 凭据',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultCredentialHint',
    'Quickstart will create the credential group and add one MCP credential member so the launch can actually use it.',
    'Quickstart 会创建凭据组，并添加一个 MCP 凭据成员，确保启动后真的可以使用该授权。',
  ],
  [
    'quickstart',
    'managed.quickstart.vaultMcpServerUrlPlaceholder',
    'MCP server URL, e.g. https://api.github.com/mcp',
    'MCP Server URL，例如 https://api.github.com/mcp',
  ],
  ['quickstart', 'managed.quickstart.createVault', 'Authorize External Tools', '授权外部工具'],
  [
    'quickstart',
    'managed.quickstart.errors.createVaultFailed',
    'Failed to create MCP credential group',
    '创建 MCP 凭据组失败',
  ],
  [
    'quickstart',
    'managed.quickstart.errors.vaultConfigMissing',
    'MCP credential group configuration not found',
    '未找到 MCP 凭据组配置',
  ],
  [
    'quickstart',
    'managed.quickstart.stepComplete.vaultCreated',
    'MCP Credential Group Configured',
    'MCP 凭据组已配置',
  ],
  [
    'quickstart',
    'managed.quickstart.stepDesc.mcpCredentialSet',
    'MCP Credential Group configured! This project-scoped MCP credential group securely stores MCP server credentials for sessions in the current project.',
    'MCP 凭据组已配置！这个项目级 MCP 凭据组为当前项目中的会话安全存储 MCP 服务器凭据。',
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
    'Store a Bearer token for one MCP server in this credential group.',
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
  ['MCP credentials', 'managed.vaults.credArchiveTitle', 'Archive MCP Credential', '归档 MCP 凭据'],
  [
    'MCP credentials',
    'managed.vaults.cred.createFailed',
    'Failed to create MCP credential. Please try again.',
    '创建 MCP 凭据失败，请重试。',
  ],
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
  ['model connection states', 'managed.llm.configurationName', 'Name', '名称'],
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
    'managed.llm.compatibilityScope',
    'Model Connection options',
    '模型连接选项',
  ],
  [
    'model connection states',
    'managed.llm.filteredByEngine',
    'Current runtime engine',
    '当前运行引擎',
  ],
  ['model connection states', 'managed.llm.availableProtocols', 'Available protocols', '可用协议'],
  [
    'model connection states',
    'managed.llm.catalogBackedOnlyHint',
    'JoySafeter only shows model protocols this runtime can connect to safely. Credentials are injected at the controlled egress boundary, not placed in prompts.',
    'JoySafeter 只展示当前运行引擎可安全接入的模型协议；凭据会在受控出网边界注入，不写入提示词。',
  ],
  [
    'model connection states',
    'managed.llm.singleProtocolSelected',
    'This provider has one matching protocol for the current runtime',
    '该供应商对当前运行引擎只有一个匹配协议',
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
    'model connection states',
    'managed.llm.protocolDefaultHint',
    'Protocol default only preselects a compatible Model Connection when creating agents or quickstarts. Running agents use their saved Model Connection.',
    '协议默认仅用于创建智能体或快速开始时预选兼容的模型连接；运行中的智能体使用自己已保存的模型连接。',
  ],
  ['service credential fields', 'managed.llm.genericKey', 'Credential Field', '凭据字段'],
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
  ['project access tokens', 'manage.apiKeys.namePlaceholder', 'Enter token name', '输入令牌名称'],
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
  ['sessions', 'managed.sessions.credentials', 'MCP Credentials', 'MCP 凭据'],
  [
    'sessions',
    'managed.sessions.noCredentials',
    'No MCP credentials configured.',
    '未配置 MCP 凭据。',
  ],
  [
    'sessions',
    'managed.sessions.mcpCredentialSetCount_one',
    '{{count}} MCP credential group',
    '{{count}} 个 MCP 凭据组',
  ],
  [
    'sessions',
    'managed.sessions.mcpCredentialSetCount_other',
    '{{count}} MCP credential groups',
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
    'managed.quickstart.autoIntro.mcpCredentialSetQuestion',
    'What MCP credential group does my agent need for MCP server credentials?',
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
  /包含 OPENAI_API_KEY 的密钥(?:\s*\(Secret\))?/u,
  /敏感凭证|敏感凭据字段|凭证自动注入|注入凭证/u,
  /\bvault configuration\b/i,
  /^\$\{…\}\s+vaults?$/i,
] as const
const activeLegacyCatalogPatterns = [
  /\bmodel secrets?\b/i,
  /\bmodel configurations?\b/i,
  /\bagent secrets?\b/i,
  /模型配置|模型密钥|智能体密钥|Agent 密钥|凭证/u,
] as const

let activeTranslationInventory: ReturnType<typeof buildActiveTranslationInventory> | undefined

function getActiveTranslationInventory() {
  activeTranslationInventory ??= buildActiveTranslationInventory(en.translation, zh.translation)
  return activeTranslationInventory
}

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
  it('inventories direct, template, and finite active translation leaves', () => {
    const inventory = getActiveTranslationInventory()

    expect(inventory.sourceFileCount).toBe(273)
    expect(inventory.sourceFiles).toContain('lib/managed/errors.ts')
    expect(inventory.sourceFiles).not.toContain('lib/i18n/locales/en.ts')
    expect(inventory.sourceFiles).not.toContain(
      'lib/i18n/active-translation-inventory.test-support.ts',
    )
    expect(inventory.sourceFiles.every((file) => !/(?:^|\/)fixtures(?:\/|$)/.test(file))).toBe(true)
    expect(inventory.directLeaves).toContain('managed.errors.writeRequired')
    expect(inventory.directLeaves).not.toContain('JOYSAFETER_WRITE_REQUIRED')
    const templateAdditions =
      new Set([...inventory.directLeaves, ...inventory.templateDynamicLeaves]).size -
      inventory.directLeaves.size
    const finiteAdditions = Object.values(inventory.finiteFamilyAdditions).reduce(
      (total, count) => total + count,
      0,
    )

    expect(inventory.counts).toEqual({ direct: 1401, dynamic: 452, total: 1853 })
    expect(templateAdditions).toBe(425)
    expect(finiteAdditions).toBe(27)
    expect(inventory.templateDynamicLeaves).toContain(
      'managed.skills.aiAuthor.scan.status.not_scanned',
    )
    expect(inventory.finiteFamilies.status).toHaveLength(21)
    expect(inventory.finiteFamilies.alerts).toHaveLength(6)
    expect(inventory.finiteFamilies.suggestions).toHaveLength(4)
    expect(inventory.finiteFamilies.skillImport).toHaveLength(15)
    expect(inventory.finiteFamilyAdditions.status).toBe(0)
    expect(inventory.finiteFamilyAdditions.alerts).toBe(6)
    expect(inventory.finiteFamilyAdditions.suggestions).toBe(4)
    expect(inventory.finiteFamilyAdditions.skillImport).toBe(0)
    expect(inventory.missingEnglishLeaves).toEqual([])
    expect(inventory.missingChineseLeaves).toEqual([])
  })

  it('reports presenter runtime keys removed from both catalogs', () => {
    const englishWithoutRuntimeKeys = structuredClone(en.translation)
    const chineseWithoutRuntimeKeys = structuredClone(zh.translation)
    const englishAlertDetails = englishWithoutRuntimeKeys.analytics.alerts.detail as Record<
      string,
      unknown
    >
    const chineseAlertDetails = chineseWithoutRuntimeKeys.analytics.alerts.detail as Record<
      string,
      unknown
    >
    const englishSuggestionMessages = englishWithoutRuntimeKeys.analytics.tokenSummary
      .suggestionMessages as Record<string, unknown>
    const chineseSuggestionMessages = chineseWithoutRuntimeKeys.analytics.tokenSummary
      .suggestionMessages as Record<string, unknown>
    delete englishAlertDetails.slowAgent
    delete chineseAlertDetails.slowAgent
    delete englishSuggestionMessages.highQueueWait
    delete chineseSuggestionMessages.highQueueWait

    const inventory = buildActiveTranslationInventory(
      englishWithoutRuntimeKeys,
      chineseWithoutRuntimeKeys,
    )

    expect(inventory.missingEnglishLeaves).toEqual(
      expect.arrayContaining([
        'analytics.alerts.detail.slowAgent',
        'analytics.tokenSummary.suggestionMessages.highQueueWait',
      ]),
    )
    expect(inventory.missingChineseLeaves).toEqual(
      expect.arrayContaining([
        'analytics.alerts.detail.slowAgent',
        'analytics.tokenSummary.suggestionMessages.highQueueWait',
      ]),
    )
  })

  it('reports a literal lib translation call removed from both catalogs', () => {
    const englishWithoutWriteRequired = structuredClone(en.translation)
    const chineseWithoutWriteRequired = structuredClone(zh.translation)
    delete englishWithoutWriteRequired.managed.errors.writeRequired
    delete chineseWithoutWriteRequired.managed.errors.writeRequired

    const inventory = buildActiveTranslationInventory(
      englishWithoutWriteRequired,
      chineseWithoutWriteRequired,
    )

    expect(inventory.directLeaves).toContain('managed.errors.writeRequired')
    expect(inventory.missingEnglishLeaves).toContain('managed.errors.writeRequired')
    expect(inventory.missingChineseLeaves).toContain('managed.errors.writeRequired')
  })

  it('reports a skill-import runtime mapping key removed from both catalogs', () => {
    const englishWithoutPathUnsafe = structuredClone(en.translation)
    const chineseWithoutPathUnsafe = structuredClone(zh.translation)
    delete englishWithoutPathUnsafe.managed.skills.zipErrors.pathUnsafe
    delete chineseWithoutPathUnsafe.managed.skills.zipErrors.pathUnsafe

    const inventory = buildActiveTranslationInventory(
      englishWithoutPathUnsafe,
      chineseWithoutPathUnsafe,
    )

    expect(inventory.missingEnglishLeaves).toContain('managed.skills.zipErrors.pathUnsafe')
    expect(inventory.missingChineseLeaves).toContain('managed.skills.zipErrors.pathUnsafe')
  })

  it('keeps all active catalog values free of legacy credential vocabulary', () => {
    const inventory = getActiveTranslationInventory()
    const violations = [...inventory.activeLeaves].flatMap((key) => {
      const values = [
        ['en', getTranslationValue(en.translation, key)],
        ['zh', getTranslationValue(zh.translation, key)],
      ] as const
      return values.flatMap(([locale, value]) =>
        typeof value === 'string' &&
        activeLegacyCatalogPatterns.some((pattern) => pattern.test(value))
          ? [`${locale}:${key}:${value}`]
          : [],
      )
    })

    expect(violations).toEqual([])
  })

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

  it.each(apiKeyFields)(
    'keeps managed and production API token copy synchronized for %s',
    (field) => {
      expect(en.translation.managed.apiKeys[field]).toBe(en.translation.manage.apiKeys[field])
      expect(zh.translation.managed.apiKeys[field]).toBe(zh.translation.manage.apiKeys[field])
    },
  )

  it.each(quickstartModelConnectionPaths)(
    'removes legacy model-configuration nouns from Quickstart %s',
    (path) => {
      expect(getTranslationValue(en.translation, path)).not.toMatch(/\bmodel configurations?\b/i)
      expect(getTranslationValue(zh.translation, path)).not.toMatch(/模型配置/)
    },
  )

  it('interpolates singular and plural MCP Credential Group counts in both locales', async () => {
    const instance = createInstance()
    await instance.init({
      lng: 'en',
      fallbackLng: false,
      resources: { en, zh },
      interpolation: { escapeValue: false },
    })

    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 1 })).toBe(
      '1 MCP credential group',
    )
    expect(instance.t('managed.sessions.mcpCredentialSetCount', { count: 2 })).toBe(
      '2 MCP credential groups',
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

describe('unified credentials surface vocabulary (P1, §3.12)', () => {
  it('lands the merged menu + tab labels as Model Connection (not 模型接入)', () => {
    expect(en.translation.nav.credentials).toBe('Credentials')
    expect(zh.translation.nav.credentials).toBe('凭据')
    expect(en.translation.managed.credentials.tabs.models).toBe('Model Connections')
    expect(zh.translation.managed.credentials.tabs.models).toBe('模型连接')
    expect(zh.translation.managed.llm.modelConfiguration).toBe('模型连接')
  })
  it('uses a neutral create action, not a "credential" umbrella', () => {
    expect(en.translation.managed.credentials.new).toBe('New')
    expect(en.translation.managed.credentials.searchModels).toBe(
      'Search model connections by name or ID',
    )
    expect(zh.translation.managed.credentials.searchServices).toBe('按名称或 ID 搜索服务凭据')
    expect(en.translation.managed.credentials.filters.label).toBe('Filters')
    expect(zh.translation.managed.credentials.emptyMcpTitle).toBe('尚未创建 MCP 凭据组')
    expect(en.translation.managed.credentials.chooser.description).toBe('Choose what to create.')
    expect(en.translation.managed.credentials.chooser.model).toBe('Model Connection')
    expect(en.translation.managed.credentials.chooser.credentialGroup).toBe('MCP Credential Group')
  })
})

describe('credential domain closure terminology guards', () => {
  const frontendRoot = path.resolve(import.meta.dirname, '../..')
  const read = (relativePath: string) =>
    readFileSync(path.resolve(frontendRoot, relativePath), 'utf8')

  it('uses Credential Group in active types and parsers', () => {
    const types = read('types/managed.ts')
    const groupParser = read('lib/managed/credential-group-response-parsers.ts')
    const compatibilityParser = read('lib/managed/vault-response-parsers.ts')

    expect(types).toContain('export interface CredentialGroup')
    expect(types).toContain('export interface CredentialGroupCredential')
    expect(types).not.toMatch(/export interface Vault\b/)
    expect(groupParser).not.toContain('Vault')
    expect(compatibilityParser).toContain('as parseVaultResponse')
  })

  it('keeps active Environment language canonical', () => {
    const types = read('types/managed.ts')
    const editor = read('components/managed/environments-egress-editor.tsx')

    expect(types).toContain('environment_credential_ids?: CredentialId[]')
    expect(types).toContain('credential_field?: string')
    expect(types).not.toContain('secret_refs?: CredentialId[]')
    expect(types).not.toContain('secret_key?: string')
    expect(editor).not.toContain('.secret_key')
  })

  it('keeps active Credential Group component identifiers canonical', () => {
    const activeFiles = [
      'components/managed/credentials/credential-management-shell.tsx',
      'components/managed/credentials/mcp-vault-list.tsx',
      'components/managed/credentials/mcp-vault-detail.tsx',
      'app/managed/credentials/mcp/[credentialGroupId]/page.tsx',
      'app/managed/vaults/components/create-vault-dialog.tsx',
      'app/managed/vaults/components/create-credential-dialog.tsx',
      'hooks/managed/use-quickstart-chat.ts',
      'app/managed/sessions/[sessionId]/page.tsx',
    ]

    for (const relativePath of activeFiles) {
      expect(read(relativePath)).not.toMatch(
        /\b(?:McpVault\w*|CreateVaultDialog|VaultDetailActionVariables|VaultActionVariables|VaultDrawer|vaultId|vaultDetail|vaultCredentials|vaultDialogOpen)\b/,
      )
    }

    expect(read('components/managed/credentials/credential-kind-chooser.tsx')).toContain(
      "'credential-group'",
    )
    expect(read('lib/managed/credential-redirects.ts')).toContain('create=credential-group')
    expect(read('lib/i18n/locales/en.ts')).not.toMatch(/(?:newMcpVault|searchMcpVaults|goToVault)/)
  })

  it('does not expose Vault wording in localized UI copy', () => {
    expect(read('lib/i18n/locales/en.ts')).not.toMatch(/credential vault/i)
    expect(read('lib/i18n/locales/zh.ts')).not.toContain('凭据库')
  })
})
