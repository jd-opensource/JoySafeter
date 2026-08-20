import { describe, expect, it } from 'vitest'

import type { LlmEngineCapability } from '@/types/llm'
import type { Secret } from '@/types/managed'

import { buildQuickstartEngineOptions } from './quickstart-engine-recommendation'

const engines: LlmEngineCapability[] = [
  {
    id: 'claude_code',
    display_name: 'Claude Code',
    enabled: true,
    supported_protocol_ids: ['anthropic_messages'],
    preferred_protocol_ids: ['anthropic_messages'],
  },
  {
    id: 'codex',
    display_name: 'Codex',
    enabled: true,
    supported_protocol_ids: ['openai_responses'],
    preferred_protocol_ids: ['openai_responses'],
  },
  {
    id: 'native',
    display_name: 'Native',
    enabled: true,
    supported_protocol_ids: ['openai_responses', 'anthropic_messages'],
    preferred_protocol_ids: ['openai_responses'],
  },
]

function connection(id: string, compatibleEngineIds: string[], isDefault = false): Secret {
  return {
    id: id as Secret['id'],
    name: id,
    kind: 'model',
    provider: 'test',
    protocol: 'test',
    model: 'test-model',
    compatible_engine_ids: compatibleEngineIds,
    is_default: isDefault,
    archived_at: null,
    created_at: '2030-01-01T00:00:00Z',
    updated_at: '2030-01-01T00:00:00Z',
  }
}

describe('buildQuickstartEngineOptions', () => {
  it('prefers an immediately usable coding runtime over a setup-only coding runtime', () => {
    const options = buildQuickstartEngineOptions({
      enabledEngines: engines,
      modelConnections: [connection('claude-prod', ['claude_code'], true)],
      intentText: 'Audit this repository and fix the TypeScript security bugs',
    })

    expect(options[0]).toMatchObject({
      engineId: 'claude_code',
      readiness: 'ready',
      recommended: true,
    })
    expect(options.find((option) => option.engineId === 'codex')).toMatchObject({
      readiness: 'setup_required',
      compatibleConnectionCount: 0,
    })
  })

  it('prefers any usable runtime before an intent match that requires setup', () => {
    const options = buildQuickstartEngineOptions({
      enabledEngines: engines,
      modelConnections: [connection('native-prod', ['native'])],
      intentText: 'Debug a Rust repository',
    })

    expect(options[0]).toMatchObject({
      engineId: 'native',
      readiness: 'ready',
      recommended: true,
    })
  })

  it('falls back to semantic priority when no runtime has a compatible connection', () => {
    const options = buildQuickstartEngineOptions({
      enabledEngines: engines,
      modelConnections: [],
      intentText: 'Review this Python code',
    })

    expect(options[0]).toMatchObject({
      engineId: 'claude_code',
      readiness: 'setup_required',
      recommended: true,
    })
  })

  it('ignores archived connections and reports default readiness metadata', () => {
    const archived = connection('archived', ['codex'], true)
    archived.archived_at = '2030-02-01T00:00:00Z'
    const options = buildQuickstartEngineOptions({
      enabledEngines: engines,
      modelConnections: [archived, connection('active', ['native'], true)],
      intentText: 'Create a general assistant',
    })

    expect(options.find((option) => option.engineId === 'codex')).toMatchObject({
      readiness: 'setup_required',
      compatibleConnectionCount: 0,
      hasDefaultConnection: false,
    })
    expect(options.find((option) => option.engineId === 'native')).toMatchObject({
      readiness: 'ready',
      compatibleConnectionCount: 1,
      hasDefaultConnection: true,
    })
  })

  it('keeps disabled runtimes visible as unavailable without recommending them', () => {
    const options = buildQuickstartEngineOptions({
      enabledEngines: [{ ...engines[0], enabled: false }, engines[1]],
      modelConnections: [connection('disabled-runtime-connection', ['claude_code'], true)],
      intentText: 'Review this TypeScript repository',
    })

    expect(options.find((option) => option.engineId === 'claude_code')).toMatchObject({
      readiness: 'unavailable',
      recommended: false,
    })
    expect(options.find((option) => option.engineId === 'codex')).toMatchObject({
      readiness: 'setup_required',
      recommended: true,
    })
  })
})
