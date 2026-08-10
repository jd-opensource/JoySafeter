import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import i18n from '@/lib/i18n/config'

import {
  QUICKSTART_COMPLETION_STEPS,
  QuickstartCompletionDescription,
  QuickstartCompletionTitle,
  type QuickstartCompletionStep,
} from './quickstart-completion-copy'

const completionCopy = {
  en: [
    [
      3,
      'Agent Created',
      'Agent created! An agent is a reusable, versioned configuration -- it defines the role, model, and tools, but does not run on its own; you start a session from it each time you need it to work.',
    ],
    [
      4,
      'Environment Created',
      'Environment created! An environment defines the sandbox where the agent runs -- network rules, packages, and resource limits. Attach it to a session to enforce those constraints.',
    ],
    [
      5,
      'MCP Credential Set Configured',
      'MCP Credential Set configured! This project-scoped MCP credential set securely stores MCP server credentials for sessions in the current project.',
    ],
    [
      6,
      'Session Started',
      'Session started and the trial run completed successfully. The Agent ran in its selected Environment, and you can continue sending messages and observing its work in real time.',
    ],
  ],
  zh: [
    [
      3,
      '智能体已创建',
      '智能体已创建！智能体是可复用的版本化配置 —— 它定义了角色、模型和工具，但不会自行运行；你每次需要它工作时都从中启动会话。',
    ],
    [
      4,
      '环境已创建',
      '环境已创建！环境定义了智能体运行的沙箱 —— 网络规则、软件包和资源限制。将其附加到会话以强制执行这些约束。',
    ],
    [
      5,
      'MCP 凭据组已配置',
      'MCP 凭据组已配置！这个项目级 MCP 凭据组为当前项目中的会话安全存储 MCP 服务器凭据。',
    ],
    [
      6,
      '会话已启动',
      '会话已启动，试运行也已成功完成。Agent 已在所选环境中运行，你可以继续发送消息并实时观察其工作。',
    ],
  ],
} as const

afterEach(() => cleanup())

it('limits semantic completion copy to production description steps', () => {
  expect(QUICKSTART_COMPLETION_STEPS).toEqual([3, 4, 5, 6])
})

describe.each(['en', 'zh'] as const)('Quickstart completion copy in %s', (locale) => {
  it.each(completionCopy[locale])(
    'renders completion step %i without leaking a translation key',
    async (step, title, description) => {
      await i18n.changeLanguage(locale)
      const view = render(
        <div>
          <QuickstartCompletionTitle step={step as QuickstartCompletionStep} />
          <QuickstartCompletionDescription step={step as QuickstartCompletionStep} />
        </div>,
      )

      expect(view.getByText(title)).toBeInTheDocument()
      expect(view.getByText(description)).toBeInTheDocument()
      expect(view.container.textContent).not.toContain('managed.quickstart.stepDesc.')
    },
  )
})
