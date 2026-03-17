/**
 * Contract tests for ActionProcessor.processActions.
 * Uses shared fixtures from docs/schemas/copilot-apply-fixtures.json so that
 * frontend apply logic stays consistent with backend (and with the contract).
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import type { GraphAction } from '@/types/copilot'
import type { Node, Edge } from 'reactflow'

import { ActionProcessor } from '../actionProcessor'

const FIXTURES_PATH = resolve(
  __dirname,
  '../../../../docs/schemas/copilot-apply-fixtures.json'
)

interface ApplyCase {
  name: string
  initial_nodes: Node[]
  initial_edges: Edge[]
  actions: GraphAction[]
  expected_nodes: Node[]
  expected_edges: Edge[]
}

function loadFixtures(): ApplyCase[] {
  try {
    const raw = readFileSync(FIXTURES_PATH, 'utf-8')
    return JSON.parse(raw) as ApplyCase[]
  } catch {
    return []
  }
}

const FIXTURES = loadFixtures()

function normalizeNodes(nodes: Node[]): Node[] {
  return [...nodes].sort((a, b) => (a.id || '').localeCompare(b.id || ''))
}

function normalizeEdges(edges: Edge[]): Edge[] {
  return [...edges].sort((a, b) => (a.id || '').localeCompare(b.id || ''))
}

function nodeContractMatch(got: Node, want: Node): boolean {
  if (got.id !== want.id) return false
  if (got.type !== want.type) return false
  if (JSON.stringify(got.position) !== JSON.stringify(want.position)) return false
  const gotData = got.data as Record<string, unknown> | undefined
  const wantData = want.data as Record<string, unknown> | undefined
  if ((gotData?.label as string) !== (wantData?.label as string)) return false
  if ((gotData?.type as string) !== (wantData?.type as string)) return false
  const wantConfig = (wantData?.config as Record<string, unknown>) || {}
  const gotConfig = (gotData?.config as Record<string, unknown>) || {}
  for (const [k, v] of Object.entries(wantConfig)) {
    if (gotConfig[k] !== v) return false
  }
  return true
}

function edgeContractMatch(got: Edge, want: Edge): boolean {
  return got.id === want.id && got.source === want.source && got.target === want.target
}

describe('ActionProcessor contract', () => {
  if (FIXTURES.length === 0) {
    it.skip('skips when fixtures not found', () => {})
    return
  }

  FIXTURES.forEach((data, caseIndex) => {
    it(data.name, () => {
      const { initial_nodes, initial_edges, actions, expected_nodes, expected_edges } = data
      const { nodes: gotNodes, edges: gotEdges } = ActionProcessor.processActions(
        actions,
        initial_nodes as Node[],
        initial_edges as Edge[]
      )
      const gotN = normalizeNodes(gotNodes)
      const gotE = normalizeEdges(gotEdges)
      const expN = normalizeNodes(expected_nodes as Node[])
      const expE = normalizeEdges(expected_edges as Edge[])

      expect(gotN.length).toBe(expN.length)
      expect(gotE.length).toBe(expE.length)
      gotN.forEach((g, i) => {
        expect(nodeContractMatch(g, expN[i])).toBe(true)
      })
      gotE.forEach((g, i) => {
        expect(edgeContractMatch(g, expE[i])).toBe(true)
      })
    })
  })
})
