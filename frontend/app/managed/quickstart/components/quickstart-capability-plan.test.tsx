import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import i18n from '@/lib/i18n/config'

import { QuickstartCapabilityPlan } from './quickstart-capability-plan'

afterEach(() => cleanup())

describe('QuickstartCapabilityPlan', () => {
  it('separates Skills, Tools, and MCP and attaches a real available Skill', async () => {
    await i18n.changeLanguage('en')
    const onSkillsChange = vi.fn()
    render(
      <QuickstartCapabilityPlan
        agentConfig={{
          tools: [{ type: 'agent_toolset_20260401' }],
          blueprint: {
            capability_plan: {
              skills: [
                {
                  name: 'Secure Review',
                  purpose: 'Apply the approved review workflow',
                  when_used: 'Before ranking findings',
                  skill_id: 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
                },
              ],
              tools: [{ name: 'Repository tools', purpose: 'Inspect source code' }],
              mcp_servers: [{ name: 'GitHub', purpose: 'Read pull request context' }],
            },
          },
        }}
        availableSkills={[
          {
            id: 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111',
            name: 'secure-review',
            display_title: 'Secure Review',
            description: 'Review code safely',
            latest_version: '1.2.0',
          },
        ]}
        disabled={false}
        onSkillsChange={onSkillsChange}
      />,
    )

    expect(screen.getByText('Capability plan')).toBeInTheDocument()
    expect(screen.getByText('Skills')).toBeInTheDocument()
    expect(screen.getByText('Built-in tools')).toBeInTheDocument()
    expect(screen.getByText('MCP connections')).toBeInTheDocument()
    expect(screen.getByText('Needs selection')).toBeInTheDocument()
    expect(screen.getByText('Needs authorization')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Add Secure Review' }))
    expect(onSkillsChange).toHaveBeenCalledWith(['skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111'])
  })

  it('marks an MCP server Ready only when a matching credential URL is authorized', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartCapabilityPlan
        agentConfig={{
          blueprint: {
            capability_plan: {
              skills: [],
              tools: [],
              mcp_servers: [
                { name: 'GitHub', purpose: 'Read PRs', server_url: 'https://mcp.github.example/' },
                { name: 'Jira', purpose: 'Read issues', server_url: 'https://mcp.jira.example' },
              ],
            },
          },
        }}
        availableSkills={[]}
        disabled={false}
        authorizedMcpServerUrls={new Set(['https://mcp.github.example'])}
        onSkillsChange={vi.fn()}
      />,
    )

    // GitHub URL is in the authorized set (trailing slash normalized) -> Ready
    expect(screen.getByText('Ready')).toBeInTheDocument()
    // Jira URL is not authorized -> still Needs authorization
    expect(screen.getByText('Needs authorization')).toBeInTheDocument()
  })

  it('explains why a recommended Skill is unavailable instead of a dead-end chip', async () => {
    await i18n.changeLanguage('en')
    render(
      <QuickstartCapabilityPlan
        agentConfig={{
          blueprint: {
            capability_plan: {
              skills: [
                {
                  name: 'Ghost Skill',
                  purpose: 'A Skill the model invented',
                  when_used: 'Never',
                  skill_id: 'skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f999',
                },
              ],
              tools: [],
              mcp_servers: [],
            },
          },
        }}
        availableSkills={[]}
        disabled={false}
        onSkillsChange={vi.fn()}
      />,
    )

    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(
      screen.getByText(
        'This Skill is not available in this project and will not be attached. Publish it or choose another Skill.',
      ),
    ).toBeInTheDocument()
  })
})
