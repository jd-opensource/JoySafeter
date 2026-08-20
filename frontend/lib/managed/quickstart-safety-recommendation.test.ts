import { describe, expect, it } from 'vitest'

import {
  normalizeQuickstartAllowedHosts,
  recommendQuickstartSafetyDefaults,
} from './quickstart-safety-recommendation'

describe('recommendQuickstartSafetyDefaults', () => {
  it('extracts explicit hosts from user intent and agent config', () => {
    const recommendation = recommendQuickstartSafetyDefaults({
      messages: [
        { role: 'user', content: 'Monitor https://status.example.org and api.vendor.com' },
      ],
      agentConfig: { mcp_servers: { docs: { url: 'https://docs.vendor.com/mcp' } } },
    })

    expect(recommendation.recommendedHosts).toEqual(
      expect.arrayContaining(['status.example.org', 'api.vendor.com', 'docs.vendor.com']),
    )
    expect(recommendation.hostReason).toBe('explicitHosts')
    expect(recommendation.externalToolsRecommended).toBe(true)
    expect(recommendation.externalToolsReason).toBe('mcpServers')
    expect(recommendation.recommendedMcpServerUrls).toEqual(['https://docs.vendor.com/mcp'])
  })

  it('infers common service allowlist hosts from coding intent', () => {
    const recommendation = recommendQuickstartSafetyDefaults({
      messages: [{ role: 'user', content: 'Build a GitHub repo triage agent' }],
    })

    expect(recommendation.recommendedHosts).toEqual(['github.com', 'api.github.com'])
    expect(recommendation.hostReason).toBe('knownServices')
    expect(recommendation.externalToolsRecommended).toBe(false)
  })

  it('keeps egress closed when no specific host or service is detected', () => {
    const recommendation = recommendQuickstartSafetyDefaults({
      messages: [{ role: 'user', content: 'Summarize pasted support conversations' }],
      agentConfig: { tools: [] },
    })

    expect(recommendation.recommendedHosts).toEqual([])
    expect(recommendation.hostReason).toBe('none')
    expect(recommendation.externalToolsReason).toBe('none')
  })

  it('normalizes allowlist hosts before environment creation', () => {
    expect(
      normalizeQuickstartAllowedHosts(
        'https://www.github.com/org/repo, api.github.com, github.com',
      ),
    ).toEqual(['github.com', 'api.github.com'])
  })
})
