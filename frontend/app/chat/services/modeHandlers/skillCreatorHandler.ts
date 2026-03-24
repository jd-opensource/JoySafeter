import { Wand2 } from 'lucide-react'

import { createTemplateHandler } from './templateHandlerFactory'

export const skillCreatorHandler = createTemplateHandler({
  modeId: 'skill-creator',
  graphName: 'Skill Creator',
  metadata: {
    id: 'skill-creator',
    label: 'chat.skillCreator',
    description: 'chat.skillCreatorDescription',
    icon: Wand2,
    type: 'template',
  },
})
