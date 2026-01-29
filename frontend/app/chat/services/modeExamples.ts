export interface ModeExample {
  id: string
  promptKey: string
}

export const modeExamples: Record<string, ModeExample[]> = {
  chat: [
    {
      id: 'chat-1',
      promptKey: 'chat.examples.chat1',
    },
    {
      id: 'chat-2',
      promptKey: 'chat.examples.chat2',
    },
    {
      id: 'chat-3',
      promptKey: 'chat.examples.chat3',
    },
    {
      id: 'chat-4',
      promptKey: 'chat.examples.chat4',
    },
  ],
  ctf: [
    {
      id: 'ctf-1',
      promptKey: 'chat.examples.ctf1',
    },
    {
      id: 'ctf-2',
      promptKey: 'chat.examples.ctf2',
    },
    {
      id: 'ctf-3',
      promptKey: 'chat.examples.ctf3',
    },
    {
      id: 'ctf-4',
      promptKey: 'chat.examples.ctf4',
    },
  ],
  'enterprise-scan': [
    {
      id: 'enterprise-scan-1',
      promptKey: 'chat.examples.enterpriseScan1',
    },
    {
      id: 'enterprise-scan-2',
      promptKey: 'chat.examples.enterpriseScan2',
    },
    {
      id: 'enterprise-scan-3',
      promptKey: 'chat.examples.enterpriseScan3',
    },
    {
      id: 'enterprise-scan-4',
      promptKey: 'chat.examples.enterpriseScan4',
    },
  ],
  'whitebox-scanner': [
    {
      id: 'whitebox-scanner-1',
      promptKey: 'chat.examples.whiteboxScanner1',
    },
    {
      id: 'whitebox-scanner-2',
      promptKey: 'chat.examples.whiteboxScanner2',
    },
    {
      id: 'whitebox-scanner-3',
      promptKey: 'chat.examples.whiteboxScanner3',
    },
    {
      id: 'whitebox-scanner-4',
      promptKey: 'chat.examples.whiteboxScanner4',
    },
  ],
  'mcp-scan': [
    {
      id: 'mcp-scan-1',
      promptKey: 'chat.examples.mcpScan1',
    },
    {
      id: 'mcp-scan-2',
      promptKey: 'chat.examples.mcpScan2',
    },
    {
      id: 'mcp-scan-3',
      promptKey: 'chat.examples.mcpScan3',
    },
    {
      id: 'mcp-scan-4',
      promptKey: 'chat.examples.mcpScan4',
    },
  ],
}
