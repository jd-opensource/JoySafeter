export const dashboardStats = {
  totalAgents: 24,
  knowledgeBases: 8,
  evaluationCompletionRate: 87.5,
  activeContainers: 3,
}

export interface ActivityItem {
  id: string
  type: 'agent_created' | 'evaluation_completed' | 'dataset_imported' | 'deployment' | 'openclaw_session'
  title: string
  description: string
  timestamp: string
  icon: 'bot' | 'chart' | 'database' | 'rocket' | 'terminal'
}

export const recentActivities: ActivityItem[] = [
  {
    id: '1',
    type: 'agent_created',
    title: 'New Agent Created',
    description: 'SQL Injection Scanner agent was created in Security workspace',
    timestamp: '2026-03-17T10:30:00Z',
    icon: 'bot',
  },
  {
    id: '2',
    type: 'evaluation_completed',
    title: 'Evaluation Completed',
    description: 'Prompt injection benchmark passed with 92% accuracy',
    timestamp: '2026-03-17T09:15:00Z',
    icon: 'chart',
  },
  {
    id: '3',
    type: 'dataset_imported',
    title: 'Dataset Imported',
    description: 'OWASP Top 10 knowledge base - 1,247 documents indexed',
    timestamp: '2026-03-17T08:00:00Z',
    icon: 'database',
  },
  {
    id: '4',
    type: 'deployment',
    title: 'Agent Deployed',
    description: 'Vulnerability Assessment Agent deployed to production',
    timestamp: '2026-03-16T18:45:00Z',
    icon: 'rocket',
  },
  {
    id: '5',
    type: 'openclaw_session',
    title: 'OpenClaw Session',
    description: 'Penetration test sandbox session completed (45 min)',
    timestamp: '2026-03-16T16:20:00Z',
    icon: 'terminal',
  },
  {
    id: '6',
    type: 'agent_created',
    title: 'Workflow Created',
    description: 'Automated threat analysis pipeline with 6 steps',
    timestamp: '2026-03-16T14:10:00Z',
    icon: 'bot',
  },
  {
    id: '7',
    type: 'evaluation_completed',
    title: 'Evaluation Completed',
    description: 'Jailbreak resistance test - 96% defense rate',
    timestamp: '2026-03-16T11:30:00Z',
    icon: 'chart',
  },
]

export const systemStatus = {
  api: 'healthy' as const,
  database: 'healthy' as const,
  sandbox: 'healthy' as const,
  models: 'degraded' as const,
}

export const quickActions = [
  { id: 'create-agent', label: 'Create Agent', href: '/build', icon: 'bot' as const },
  { id: 'import-dataset', label: 'Import Dataset', href: '/knowledge/datasets', icon: 'database' as const },
  { id: 'run-evaluation', label: 'Run Evaluation', href: '/evaluate', icon: 'chart' as const },
  { id: 'start-openclaw', label: 'Start OpenClaw', href: '/openclaw', icon: 'terminal' as const },
]
