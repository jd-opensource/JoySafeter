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
