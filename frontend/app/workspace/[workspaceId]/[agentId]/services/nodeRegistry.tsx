'use client'

import {
  Bot,
  Split,
  GitBranch,
  MessageSquare,
  Globe,
  UserRound,
  LucideIcon,
  Wrench,
  Route,
  Repeat2,
  Code,
  Layers,
  FileJson,
  Globe2,
  BrainCircuit,
} from 'lucide-react'

// --- Types ---

export type FieldType =
  | 'text'
  | 'textarea'
  | 'select'
  | 'number'
  | 'modelSelect'
  | 'toolSelector'
  | 'skillSelector'
  | 'kvList'
  | 'boolean'
  | 'routeList'        // Route rule list
  | 'conditionExpr'    // Conditional expression editor
  | 'stringArray'      // String array input
  | 'dockerConfig'     // Docker configuration editor
  | 'stateSelect'      // State variable selector
  | 'stateMapper'      // Visual input mapper
  | 'code'             // Code editor

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  placeholder?: string
  options?: string[] // For static select
  required?: boolean
  description?: string
  // For number type
  min?: number
  max?: number
  step?: number
  // For conditionExpr type
  variables?: string[]  // Available variable hints
  // Conditional display: only show when a field equals certain values
  showWhen?: {
    field: string                    // Dependent field key
    values: (string | boolean | number)[]  // Show when field value is in this array
  }
}

export interface NodeDefinition {
  type: string
  label: string
  subLabel?: string
  icon: LucideIcon
  hidden?: boolean
  style: {
    color: string // text-color class
    bg: string // bg-color class
  }
  defaultConfig: Record<string, unknown>
  schema: FieldSchema[]
  /** State fields this node reads from */
  stateReads?: string[]
  /** State fields this node writes to */
  stateWrites?: string[]
}

// --- Registry Definitions ---

const REGISTRY: NodeDefinition[] = [
  {
    type: 'agent',
    label: 'Agent',
    subLabel: 'LLM Process',
    icon: Bot,
    style: { color: 'text-blue-600', bg: 'bg-blue-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'current_node'],
    defaultConfig: {
      model: 'DeepSeek-Chat',
      temp: 0.7,
      systemPrompt: '',
      enableMemory: false,
      memoryModel: 'DeepSeek-Chat',
      memoryPrompt:
        'Summarize the interaction highlights and key facts learned about the user.',
      useDeepAgents: false,
      description: '',
      backend_type: 'docker',
      workspace_dir: '', // Custom workspace subdirectory (defaults to graph name)
      docker_config: {
        image: 'python:3.12-slim',
        working_dir: '/workspace',
        auto_remove: true,
        max_output_size: 100000,
        command_timeout: 30,
      },
    },
    schema: [
      { key: 'model', label: 'Inference Model', type: 'modelSelect', required: true },
      {
        key: 'systemPrompt',
        label: 'System Instruction',
        type: 'textarea',
        placeholder: 'You are a helpful assistant...',
      },
      { key: 'tools', label: 'Connected Tools', type: 'toolSelector' },
      {
        key: 'useDeepAgents',
        label: 'Use DeepAgents Mode',
        type: 'boolean',
        description: 'Enable DeepAgents mode for advanced agent capabilities.',
      },
      {
        key: 'skills',
        label: 'Connected Skills',
        type: 'skillSelector',
        description: 'Skills provide specialized instructions that the agent can load on-demand.',
        showWhen: {
          field: 'useDeepAgents',
          values: [true, 'true', 'True'],
        },
      },
      {
        key: 'description',
        label: 'SubAgent Description',
        type: 'textarea',
        placeholder: 'Describe the capabilities of this subAgent...',
        description:
          'Required when DeepAgents mode is enabled. Describes what this subAgent can do.',
      },
      {
        key: 'backend_type',
        label: 'Backend Type',
        type: 'select',
        options: ['filesystem', 'docker'],
        description:
          'Backend type for agent execution. Docker provides isolated sandbox environment.',
        showWhen: {
          field: 'useDeepAgents',
          values: ['true', 'True', true],
        },
      },
      {
        key: 'workspace_dir',
        label: 'Workspace Directory',
        type: 'text',
        placeholder: 'Leave empty to use graph name',
        description:
          'Custom subdirectory name for filesystem backend workspace. If empty, uses the current graph name. Only used when backend_type is "filesystem".',
        showWhen: {
          field: 'backend_type',
          values: ['filesystem'],
        },
      },
      {
        key: 'docker_config',
        label: 'Docker Configuration',
        type: 'dockerConfig',
        description:
          'Docker sandbox configuration. Only used when backend_type is "docker".',
        showWhen: {
          field: 'backend_type',
          values: ['docker'],
        },
      },
      // Memory Section is separated in UI but defined here
      {
        key: 'enableMemory',
        label: 'Enable Long-term Memory',
        type: 'boolean',
        description: 'Save context across different sessions.',
      },
      {
        key: 'memoryModel',
        label: 'Memory Processing Model',
        type: 'modelSelect',
        description: 'Model used to summarize and update memory.',
      },
      {
        key: 'memoryPrompt',
        label: 'Memory Update Prompt',
        type: 'textarea',
        placeholder: 'How should memory be updated?',
      },
    ],
  },
  {
    type: 'condition',
    label: 'Condition',
    subLabel: 'If/Else Split',
    icon: Split,
    style: { color: 'text-amber-500', bg: 'bg-amber-50' },
    stateReads: ['*'],
    stateWrites: ['route_decision', 'route_history'],
    defaultConfig: {
      expression: '',
      trueLabel: 'Yes',
      falseLabel: 'No',
    },
    schema: [
      {
        key: 'expression',
        label: 'Condition Expression',
        type: 'conditionExpr',
        placeholder: "len(state.get('messages', [])) > 5",
        description: 'Python expression that evaluates to True or False',
        required: true,
        variables: ['state', 'messages', 'context', 'current_node'],
      },
    ],
  },
  {
    type: 'condition_agent',
    label: 'Condition Agent',
    subLabel: 'AI Decision Split',
    icon: GitBranch,
    style: { color: 'text-pink-500', bg: 'bg-pink-50' },
    stateReads: ['*'],
    stateWrites: ['route_decision', 'route_history'],
    defaultConfig: { instruction: 'Analyze and route', options: ['Option A', 'Option B'] },
    schema: [
      {
        key: 'instruction',
        label: 'Routing Instruction',
        type: 'textarea',
        placeholder: 'Example: If user sentiment is positive, route to positive branch; otherwise route to negative branch',
        description: 'Tell AI how to make routing decisions based on current context. AI will analyze message content and state, then select the corresponding route branch.',
        required: true,
      },
      {
        key: 'options',
        label: 'Route Options',
        type: 'stringArray',
        placeholder: '输入选项名称（如：positive）',
        description: '定义可用的路由分支列表。每个选项对应一个从该节点出发的连接。例如：positive, negative, neutral',
      },
    ],
  },
  {
    type: 'custom_function',
    label: 'Custom Tool',
    subLabel: 'Function Definition',
    icon: Wrench,
    hidden: true,
    style: { color: 'text-purple-600', bg: 'bg-purple-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: { name: 'my_tool', description: '', parameters: [] },
    schema: [
      {
        key: 'name',
        label: 'Tool Name',
        type: 'text',
        placeholder: 'e.g. get_weather',
        required: true,
      },
      {
        key: 'description',
        label: 'Description',
        type: 'textarea',
        placeholder: 'Describe what this tool does...',
        required: true,
      },
      {
        key: 'parameters',
        label: 'Parameters',
        type: 'kvList',
        description: 'Define arguments (Name : Type)',
      },
    ],
  },
  {
    type: 'direct_reply',
    label: 'Direct Reply',
    subLabel: 'Send Message',
    icon: MessageSquare,
    style: { color: 'text-emerald-500', bg: 'bg-emerald-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'current_node'],
    defaultConfig: { template: 'Hello user' },
    schema: [
      {
        key: 'template',
        label: 'Message Template',
        type: 'textarea',
        placeholder: 'Hello {{username}}...',
      },
    ],
  },
  {
    type: 'human_input',
    label: 'Human Input',
    subLabel: 'Interrupt Gate',
    icon: UserRound,
    style: { color: 'text-indigo-500', bg: 'bg-indigo-50' },
    stateReads: ['messages'],
    stateWrites: ['messages', 'current_node'],
    defaultConfig: {},
    schema: [],
  },
  // ==================== New Node Types ====================
  {
    type: 'router_node',
    label: 'Router',
    subLabel: 'Multi-Rule Routing',
    icon: Route,
    style: { color: 'text-orange-600', bg: 'bg-orange-50' },
    stateReads: ['*'],
    stateWrites: ['route_decision', 'route_history'],
    defaultConfig: {
      routes: [
        {
          id: `route_${Date.now()}_1`,
          condition: "state.get('value', 0) > 10",
          targetEdgeKey: 'high',
          label: 'High Score',
          priority: 0,
        },
        {
          id: `route_${Date.now()}_2`,
          condition: "state.get('value', 0) > 5",
          targetEdgeKey: 'medium',
          label: 'Medium Score',
          priority: 1,
        },
      ],
      defaultRoute: 'default',
    },
    schema: [
      {
        key: 'routes',
        label: 'Route Rules',
        type: 'routeList',
        description: 'Define conditions for each outgoing edge. Rules are evaluated in priority order.',
        required: true,
      },
      {
        key: 'defaultRoute',
        label: 'Default Route Key',
        type: 'text',
        placeholder: 'default',
        description: 'Route key when no conditions match',
      },
    ],
  },
  {
    type: 'loop_condition_node',
    label: 'Loop Condition',
    subLabel: 'Loop Control',
    icon: Repeat2,
    style: { color: 'text-cyan-600', bg: 'bg-cyan-50' },
    stateReads: ['loop_count', 'loop_condition_met', 'context', 'loop_states'],
    stateWrites: ['loop_count', 'loop_condition_met', 'loop_states'],
    defaultConfig: {
      conditionType: 'while',
      listVariable: 'items',
      condition: 'loop_count < 3',
      maxIterations: 5,
    },
    schema: [
      {
        key: 'conditionType',
        label: 'Loop Type',
        type: 'select',
        options: ['forEach', 'while', 'doWhile'],
        description: 'forEach: iterate list, while: check first, doWhile: execute first',
        required: true,
      },
      {
        key: 'listVariable',
        label: 'List Variable',
        type: 'stateSelect',
        placeholder: 'Select list variable',
        description: 'For forEach: state key containing the list to iterate',
        showWhen: { field: 'conditionType', values: ['forEach'] },
      },
      {
        key: 'condition',
        label: 'Loop Condition',
        type: 'conditionExpr',
        placeholder: 'loop_count < 3 and state.get("has_error") == False',
        description: 'For while/doWhile: expression returning True to continue, False to exit',
        variables: ['state', 'loop_count', 'loop_state', 'context'],
        showWhen: { field: 'conditionType', values: ['while', 'doWhile'] },
      },
      {
        key: 'maxIterations',
        label: 'Max Iterations',
        type: 'number',
        min: 1,
        max: 100,
        step: 1,
        description: 'Maximum number of loop iterations (safety limit)',
        required: true,
      },
    ],
  },
  {
    type: 'tool_node',
    label: 'Tool',
    subLabel: 'Tool Execution',
    icon: Wrench,
    style: { color: 'text-green-600', bg: 'bg-green-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: {
      tool_name: '',
      input_mapping: {},
    },
    schema: [
      {
        key: 'tool_name',
        label: 'Tool Name',
        type: 'text',
        placeholder: 'search_google',
        description: 'Name of the tool to execute',
        required: true,
      },
      {
        key: 'input_mapping',
        label: 'Input Mapping',
        type: 'stateMapper',
        placeholder: 'Map tool arguments to state variables',
        description: 'Define how state variables map to tool parameters',
      },
    ],
  },
  {
    type: 'function_node',
    label: 'Function',
    subLabel: 'Custom Function',
    icon: Code,
    style: { color: 'text-indigo-600', bg: 'bg-indigo-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: {
      execution_mode: 'custom',
      function_name: '',
      function_code: '',
    },
    schema: [
      {
        key: 'execution_mode',
        label: 'Execution Mode',
        type: 'select',
        options: ['custom', 'predefined'],
        required: true,
        description: 'Choose between custom Python code or a predefined function',
      },
      {
        key: 'function_name',
        label: 'Predefined Function',
        type: 'select',
        options: ['math_add', 'math_multiply', 'string_concat', 'dict_get', 'dict_set'],
        description: 'Select a predefined function',
        showWhen: { field: 'execution_mode', values: ['predefined'] },
      },
      {
        key: 'input_mapping',
        label: 'Variables',
        type: 'stateMapper',
        placeholder: 'Map state variables to local variables',
        description: 'Define input variables. Mapped variables will be directly available in your custom code as local variables.',
        showWhen: { field: 'execution_mode', values: ['custom'] },
      },
      {
        key: 'function_code',
        label: 'Custom Code',
        type: 'code',
        placeholder: 'result = {"output": input_var * 2}',
        description: 'Python code to execute (sandboxed). Use "result" variable for output.',
        showWhen: { field: 'execution_mode', values: ['custom'] },
      },
      {
        key: 'output_mapping',
        label: 'Output Mapping',
        type: 'stateMapper',
        placeholder: 'Map function result to state variables',
        description: 'Define how the function result maps to state variables. E.g., if result={"a": 1}, map "a" to a state variable.',
        showWhen: { field: 'execution_mode', values: ['custom', 'predefined'] },
      },
    ],
  },
  {
    type: 'aggregator_node',
    label: 'Aggregator',
    subLabel: 'Fan-In Aggregation',
    icon: Layers,
    style: { color: 'text-teal-600', bg: 'bg-teal-50' },
    stateReads: ['task_results', 'parallel_results', 'task_states'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: {
      error_strategy: 'best_effort',
      target_variable: 'aggregated_results',
      source_variables: ['task_results'],
      method: 'append',
    },
    schema: [
      {
        key: 'source_variables',
        label: 'Source Variables',
        type: 'stringArray',
        placeholder: 'task_results, other_var',
        description: 'State variables to collect from (comma separated)',
        required: true,
      },
      {
        key: 'target_variable',
        label: 'Target Variable',
        type: 'stateSelect',
        placeholder: 'Select variable to store result',
        description: 'Where to save the aggregated result',
        required: true,
      },
      {
        key: 'method',
        label: 'Aggregation Method',
        type: 'select',
        options: ['append', 'merge', 'sum', 'latest'],
        description: 'How to combine values: Append (List), Merge (Dict), Sum (Number), Latest (Last Value)',
        required: true,
      },
      {
        key: 'error_strategy',
        label: 'Error Strategy',
        type: 'select',
        options: ['fail_fast', 'best_effort'],
        description: 'fail_fast: one failure fails all | best_effort: collect successes',
        required: true,
      },
    ],
  },
  {
    type: 'json_parser_node',
    label: 'JSON Parser',
    subLabel: 'Parse & Transform',
    icon: FileJson,
    style: { color: 'text-yellow-600', bg: 'bg-yellow-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: {
      jsonpath_query: '',
      json_schema: {},
    },
    schema: [
      {
        key: 'jsonpath_query',
        label: 'JSONPath Query',
        type: 'text',
        placeholder: '$.data.items[*].name',
        description: 'JSONPath expression to extract data',
      },
      {
        key: 'json_schema',
        label: 'JSON Schema',
        type: 'textarea',
        placeholder: '{"type": "object", "properties": {...}}',
        description: 'JSON Schema for validation (optional)',
      },
    ],
  },
  {
    type: 'http_request_node',
    label: 'HTTP Request',
    subLabel: 'Enhanced API Call',
    icon: Globe2,
    style: { color: 'text-red-600', bg: 'bg-red-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'context', 'current_node'],
    defaultConfig: {
      method: 'GET',
      url: 'https://api.example.com/endpoint',
      headers: {},
      auth: { type: 'none' },
      max_retries: 3,
      timeout: 30.0,
    },
    schema: [
      {
        key: 'method',
        label: 'Method',
        type: 'select',
        options: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
        required: true,
      },
      { key: 'url', label: 'URL', type: 'text', placeholder: 'https://api...', required: true },
      {
        key: 'headers',
        label: 'Headers',
        type: 'kvList',
        description: 'HTTP headers as key-value pairs',
      },
      {
        key: 'auth',
        label: 'Authentication',
        type: 'select',
        options: ['none', 'bearer', 'basic'],
        description: 'Authentication type',
      },
      {
        key: 'max_retries',
        label: 'Max Retries',
        type: 'number',
        placeholder: '3',
        description: 'Maximum number of retry attempts',
      },
      {
        key: 'timeout',
        label: 'Timeout (seconds)',
        type: 'number',
        placeholder: '30.0',
        description: 'Request timeout in seconds',
      },
    ],
  },
  // ==================== State Management Nodes ====================
  {
    type: 'get_state_node',
    label: 'Get State',
    subLabel: 'Read Global State',
    icon: FileJson, // Using FileJson for now
    style: { color: 'text-sky-600', bg: 'bg-sky-50' },
    stateReads: ['*'], // Reads from global state
    stateWrites: ['current_node'], // Outputs a local payload, doesn't mutate global state structurally
    defaultConfig: {
      keys_to_fetch: [],
      error_on_missing: false,
    },
    schema: [
      {
        key: 'keys_to_fetch',
        label: 'State Variables to Fetch',
        type: 'stringArray',
        placeholder: 'user_preferences, session_id',
        description: 'List of global state variable names to load into the local execution payload.',
        required: true,
      },
      {
        key: 'error_on_missing',
        label: 'Error on Missing',
        type: 'boolean',
        description: 'If true, execution fails if a requested variable is not found in the global state.',
      },
    ],
  },
  {
    type: 'set_state_node',
    label: 'Set State',
    subLabel: 'Write Global State',
    icon: Layers, // Using Layers for now
    style: { color: 'text-fuchsia-600', bg: 'bg-fuchsia-50' },
    stateReads: ['current_node'], // Reads from local payload to write to global
    stateWrites: ['*'], // Mutates global state
    defaultConfig: {
      input_mapping: {},
    },
    schema: [
      {
        key: 'input_mapping',
        label: 'State Mapping',
        type: 'stateMapper',
        placeholder: 'Map payload values to global state variables',
        description: 'Explicitly map values from the local execution payload (or upstream outputs) into the global GraphState.',
      },
    ],
  },
  // ==================== Code Agent ====================
  {
    type: 'code_agent',
    label: 'Code Agent',
    subLabel: 'Python Code Execution',
    icon: BrainCircuit,
    style: { color: 'text-violet-600', bg: 'bg-violet-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'current_node', 'context'],
    defaultConfig: {
      model: 'DeepSeek-Chat',
      executor_type: 'local',
      agent_mode: 'autonomous',
      max_steps: 20,
      enable_planning: false,
      enable_data_analysis: true,
      additional_imports: [],
      docker_image: 'python:3.11-slim',
      description: '',
    },
    schema: [
      // === Basic Configuration ===
      {
        key: 'model',
        label: 'Inference Model',
        type: 'modelSelect',
        required: true,
        description: 'LLM model for code generation and reasoning',
      },
      {
        key: 'agent_mode',
        label: 'Agent Mode',
        type: 'select',
        options: ['autonomous', 'tool_executor'],
        required: true,
        description: 'autonomous: Self-planning agent | tool_executor: Passive code executor',
      },
      // === Executor Configuration ===
      {
        key: 'executor_type',
        label: 'Executor Type',
        type: 'select',
        options: ['local', 'docker', 'auto'],
        required: true,
        description: 'local: Secure AST interpreter | docker: Docker sandbox | auto: Smart routing',
      },
      {
        key: 'docker_image',
        label: 'Docker Image',
        type: 'text',
        placeholder: 'python:3.11-slim',
        description: 'Docker image for the executor sandbox',
        showWhen: {
          field: 'executor_type',
          values: ['docker', 'auto'],
        },
      },
      {
        key: 'additional_imports',
        label: 'Additional Imports',
        type: 'stringArray',
        placeholder: 'requests, beautifulsoup4',
        description: 'Additional Python modules to allow',
      },
      // === Execution Parameters ===
      {
        key: 'max_steps',
        label: 'Max Steps',
        type: 'number',
        min: 1,
        max: 100,
        step: 1,
        description: 'Maximum Thought-Code-Observation iterations',
      },
      {
        key: 'enable_planning',
        label: 'Enable Planning',
        type: 'boolean',
        description: 'Enable multi-step task planning for complex tasks',
      },
      {
        key: 'enable_data_analysis',
        label: 'Data Analysis Mode',
        type: 'boolean',
        description: 'Enable pandas, numpy, matplotlib modules',
      },
      // === Tools (displayed in Tools section) ===
      {
        key: 'tools',
        label: 'Connected Tools',
        type: 'toolSelector',
        description: 'External tools the Code Agent can use',
      },
      // === SubAgent Description ===
      {
        key: 'description',
        label: 'SubAgent Description',
        type: 'textarea',
        placeholder: 'Describe what this Code Agent specializes in...',
        description: 'Description when used as a SubAgent in DeepAgents mode',
      },
    ],
  },
  // ==================== A2A Agent ====================
  {
    type: 'a2a_agent',
    label: 'A2A Agent',
    subLabel: 'Remote A2A Protocol',
    icon: Globe2,
    style: { color: 'text-amber-600', bg: 'bg-amber-50' },
    stateReads: ['messages', 'context'],
    stateWrites: ['messages', 'current_node'],
    defaultConfig: {
      a2a_url: '',
      agent_card_url: '',
      a2a_auth_headers: {},
      description: '',
    },
    schema: [
      {
        key: 'a2a_url',
        label: 'A2A Server URL',
        type: 'text',
        placeholder: 'https://agent.example.com/a2a/v1',
        description: 'Base URL of the A2A-compliant agent (e.g. from Agent Card url field)',
      },
      {
        key: 'agent_card_url',
        label: 'Agent Card URL',
        type: 'text',
        placeholder: 'https://agent.example.com/.well-known/agent.json',
        description: 'Optional: Agent Card URL; if set, A2A Server URL is resolved from the card',
      },
      {
        key: 'a2a_auth_headers',
        label: 'Authentication Headers',
        type: 'kvList',
        placeholder: 'Authorization: Bearer xxx',
        description: 'Optional HTTP headers for authentication (e.g. Authorization, X-API-Key)',
      },
      {
        key: 'description',
        label: 'SubAgent Description',
        type: 'textarea',
        placeholder: 'Describe what this remote A2A agent does...',
        description: 'Description when used as a SubAgent in DeepAgents mode',
      },
    ],
  },
]

// === Registry API ===

export const nodeRegistry = {
  getAll: () => REGISTRY.filter((n) => !n.hidden),

  get: (type: string): NodeDefinition | undefined => {
    return REGISTRY.find((n) => n.type === type)
  },

  /**
   * Group definitions for the sidebar UI
   */
  getGrouped: () => {
    const visibleRegistry = REGISTRY.filter((n) => !n.hidden);
    return {
      Agents: visibleRegistry.filter((n) => ['agent', 'code_agent', 'a2a_agent'].includes(n.type)),
      'Flow Control': visibleRegistry.filter((n) =>
        ['condition', 'condition_agent', 'router_node', 'loop_condition_node'].includes(n.type)
      ),
      'State Management': visibleRegistry.filter((n) =>
        ['get_state_node', 'set_state_node'].includes(n.type)
      ),
      Actions: visibleRegistry.filter((n) =>
        ['custom_function', 'http_request_node', 'human_input', 'direct_reply', 'tool_node', 'function_node', 'json_parser_node'].includes(n.type)
      ),
      Aggregation: visibleRegistry.filter((n) =>
        ['aggregator_node'].includes(n.type)
      ),
    }
  },
}
