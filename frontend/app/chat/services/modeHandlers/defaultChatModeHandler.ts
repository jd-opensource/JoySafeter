import { MessageSquare } from 'lucide-react'

import { createTemplateHandler } from './templateHandlerFactory'

export const defaultChatModeHandler = createTemplateHandler({
  modeId: 'default-chat',
  graphName: 'Default Chat',
  metadata: {
    id: 'default-chat',
    label: 'chat.defaultChat',
    description: 'chat.defaultChatDescription',
    icon: MessageSquare,
    type: 'template',
  },
})
