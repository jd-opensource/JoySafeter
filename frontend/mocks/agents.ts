export interface MockAgent {
  id: string
  name: string
  description: string
  status: 'active' | 'draft' | 'deployed'
  lastModified: string
  workspaceId: string
  workspaceName: string
  nodeCount: number
}

export const mockAgents: MockAgent[] = [
  {
    id: 'agent-001',
    name: 'SQL Injection Scanner',
    description: 'Detects and analyzes SQL injection vulnerabilities in web applications',
    status: 'deployed',
    lastModified: '2026-03-17T10:30:00Z',
    workspaceId: 'ws-001',
    workspaceName: 'Security Testing',
    nodeCount: 8,
  },
  {
    id: 'agent-002',
    name: 'Prompt Guard',
    description: 'Protects LLM applications from prompt injection attacks',
    status: 'deployed',
    lastModified: '2026-03-16T15:20:00Z',
    workspaceId: 'ws-001',
    workspaceName: 'Security Testing',
    nodeCount: 12,
  },
  {
    id: 'agent-003',
    name: 'Vulnerability Classifier',
    description: 'Classifies vulnerabilities by severity and type using CVSS scoring',
    status: 'active',
    lastModified: '2026-03-15T09:00:00Z',
    workspaceId: 'ws-002',
    workspaceName: 'Analysis',
    nodeCount: 6,
  },
  {
    id: 'agent-004',
    name: 'Threat Intel Aggregator',
    description: 'Aggregates and correlates threat intelligence from multiple sources',
    status: 'draft',
    lastModified: '2026-03-14T11:30:00Z',
    workspaceId: 'ws-002',
    workspaceName: 'Analysis',
    nodeCount: 15,
  },
  {
    id: 'agent-005',
    name: 'Compliance Auditor',
    description: 'Automated compliance checking against SOC2, ISO 27001, NIST',
    status: 'active',
    lastModified: '2026-03-13T16:45:00Z',
    workspaceId: 'ws-003',
    workspaceName: 'Compliance',
    nodeCount: 10,
  },
]

export interface MockWorkspace {
  id: string
  name: string
  agentCount: number
  workflowCount: number
}

export const mockWorkspaces: MockWorkspace[] = [
  { id: 'ws-001', name: 'Security Testing', agentCount: 8, workflowCount: 3 },
  { id: 'ws-002', name: 'Analysis', agentCount: 6, workflowCount: 2 },
  { id: 'ws-003', name: 'Compliance', agentCount: 4, workflowCount: 1 },
  { id: 'ws-004', name: 'Research', agentCount: 6, workflowCount: 4 },
]
