'use client'

import {
  Bot,
  LucideIcon,
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
  | 'boolean'
  | 'stringArray'
  | 'kvList'

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  placeholder?: string
  options?: string[]
  required?: boolean
  description?: string
  min?: number
  max?: number
  step?: number
  showWhen?: {
    field: string
    values: (string | boolean | number)[]
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
}

// --- Registry Definitions ---

const REGISTRY: NodeDefinition[] = [
  {
    type: 'agent',
    label: 'Agent',
    subLabel: 'LLM Process',
    icon: Bot,
    style: { color: 'text-[var(--brand-500)]', bg: 'bg-[var(--brand-50)]' },
    defaultConfig: {
      model: '',
      temp: 0.7,
      systemPrompt: '',
      enableMemory: false,
      memoryModel: '',
      memoryPrompt: 'Summarize the interaction highlights and key facts learned about the user.',
      useDeepAgents: false,
      description: '',
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
      // Memory Section
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
  // ==================== Code Agent ====================
  {
    type: 'code_agent',
    label: 'Code Agent',
    subLabel: 'Python Code Execution',
    icon: BrainCircuit,
    style: { color: 'text-[var(--brand-600)]', bg: 'bg-[var(--brand-50)]' },
    defaultConfig: {
      model: '',
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
    style: { color: 'text-[var(--status-warning)]', bg: 'bg-[var(--status-warning-bg)]' },
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
    const visibleRegistry = REGISTRY.filter((n) => !n.hidden)
    return {
      Agents: visibleRegistry.filter((n) => ['agent', 'code_agent', 'a2a_agent'].includes(n.type)),
    }
  },
}
