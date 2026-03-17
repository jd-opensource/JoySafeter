export interface Dataset {
  id: string
  name: string
  description: string
  documentCount: number
  chunkCount: number
  status: 'ready' | 'indexing' | 'error'
  lastUpdated: string
  size: string
  embeddingModel: string
}

export const datasets: Dataset[] = [
  {
    id: 'ds-001',
    name: 'OWASP Top 10 2025',
    description: 'Comprehensive knowledge base covering OWASP Top 10 web application security risks',
    documentCount: 1247,
    chunkCount: 8934,
    status: 'ready',
    lastUpdated: '2026-03-15T10:00:00Z',
    size: '256 MB',
    embeddingModel: 'text-embedding-3-large',
  },
  {
    id: 'ds-002',
    name: 'CVE Database 2024-2026',
    description: 'Common Vulnerabilities and Exposures database with detailed analysis',
    documentCount: 5621,
    chunkCount: 42150,
    status: 'ready',
    lastUpdated: '2026-03-14T16:30:00Z',
    size: '1.2 GB',
    embeddingModel: 'text-embedding-3-large',
  },
  {
    id: 'ds-003',
    name: 'Prompt Injection Patterns',
    description: 'Collection of known prompt injection techniques and defenses',
    documentCount: 342,
    chunkCount: 2156,
    status: 'ready',
    lastUpdated: '2026-03-12T09:15:00Z',
    size: '48 MB',
    embeddingModel: 'text-embedding-3-small',
  },
  {
    id: 'ds-004',
    name: 'Security Compliance Frameworks',
    description: 'SOC2, ISO 27001, NIST, and GDPR compliance documentation',
    documentCount: 890,
    chunkCount: 6723,
    status: 'indexing',
    lastUpdated: '2026-03-17T08:00:00Z',
    size: '180 MB',
    embeddingModel: 'text-embedding-3-large',
  },
  {
    id: 'ds-005',
    name: 'Malware Analysis Reports',
    description: 'Threat intelligence reports and malware analysis documentation',
    documentCount: 2103,
    chunkCount: 15890,
    status: 'ready',
    lastUpdated: '2026-03-10T14:20:00Z',
    size: '520 MB',
    embeddingModel: 'text-embedding-3-large',
  },
  {
    id: 'ds-006',
    name: 'API Security Best Practices',
    description: 'REST/GraphQL API security guidelines and vulnerability patterns',
    documentCount: 156,
    chunkCount: 1024,
    status: 'error',
    lastUpdated: '2026-03-09T11:45:00Z',
    size: '32 MB',
    embeddingModel: 'text-embedding-3-small',
  },
]

export interface Document {
  id: string
  name: string
  type: 'pdf' | 'md' | 'txt' | 'html' | 'json'
  chunks: number
  size: string
  addedAt: string
}

export const datasetDocuments: Record<string, Document[]> = {
  'ds-001': [
    { id: 'doc-1', name: 'A01-Broken-Access-Control.pdf', type: 'pdf', chunks: 24, size: '1.2 MB', addedAt: '2026-03-10' },
    { id: 'doc-2', name: 'A02-Cryptographic-Failures.pdf', type: 'pdf', chunks: 18, size: '890 KB', addedAt: '2026-03-10' },
    { id: 'doc-3', name: 'A03-Injection.md', type: 'md', chunks: 32, size: '156 KB', addedAt: '2026-03-10' },
    { id: 'doc-4', name: 'A04-Insecure-Design.pdf', type: 'pdf', chunks: 15, size: '720 KB', addedAt: '2026-03-11' },
    { id: 'doc-5', name: 'A05-Security-Misconfiguration.html', type: 'html', chunks: 21, size: '340 KB', addedAt: '2026-03-11' },
    { id: 'doc-6', name: 'A06-Vulnerable-Components.txt', type: 'txt', chunks: 12, size: '98 KB', addedAt: '2026-03-12' },
    { id: 'doc-7', name: 'A07-Auth-Failures.pdf', type: 'pdf', chunks: 28, size: '1.1 MB', addedAt: '2026-03-12' },
    { id: 'doc-8', name: 'A08-Software-Data-Integrity.md', type: 'md', chunks: 19, size: '145 KB', addedAt: '2026-03-13' },
  ],
}

export interface SearchResult {
  documentName: string
  chunkContent: string
  score: number
  chunkIndex: number
}

export const mockSearchResults: SearchResult[] = [
  {
    documentName: 'A03-Injection.md',
    chunkContent: 'SQL injection occurs when untrusted data is sent to an interpreter as part of a command or query. The attacker\'s hostile data can trick the interpreter into executing unintended commands or accessing data without proper authorization.',
    score: 0.95,
    chunkIndex: 3,
  },
  {
    documentName: 'A01-Broken-Access-Control.pdf',
    chunkContent: 'Access control enforces policy such that users cannot act outside of their intended permissions. Failures typically lead to unauthorized information disclosure, modification, or destruction of all data.',
    score: 0.88,
    chunkIndex: 7,
  },
  {
    documentName: 'A07-Auth-Failures.pdf',
    chunkContent: 'Confirmation of the user\'s identity, authentication, and session management is critical to protect against authentication-related attacks. Weak authentication mechanisms are one of the most common security vulnerabilities.',
    score: 0.82,
    chunkIndex: 12,
  },
]
