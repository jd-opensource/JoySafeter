import { describe, expect, it } from 'vitest'

import { minimaxModelRank, recommendedModelOptions } from './model-options'

const models = [
  { provider_name: 'other', name: 'first' },
  { provider_name: 'minimax', name: 'MiniMax-M2.7' },
  { provider_name: 'minimax', name: 'MiniMax-M3' },
  { provider_name: 'other', name: 'second' },
  { provider_name: 'minimax', name: 'MiniMax-M3.1-Flash' },
  { provider_name: 'minimax', name: 'saved-custom-id' },
]

describe('MiniMax model options', () => {
  it('recommends Flash then M3 while preserving other providers and input data', () => {
    const snapshot = JSON.stringify(models)
    expect(recommendedModelOptions(models).map((model) => model.name)).toEqual([
      'first',
      'MiniMax-M3.1-Flash',
      'second',
      'MiniMax-M3',
    ])
    expect(JSON.stringify(models)).toBe(snapshot)
  })

  it.each(['MiniMax-M2.7', 'saved-custom-id'])(
    'keeps the explicit saved selection %s visible',
    (name) => {
      const options = recommendedModelOptions(models, `minimax:${name}`)
      expect(
        options.filter((model) => model.provider_name === 'minimax').map((model) => model.name),
      ).toEqual(['MiniMax-M3.1-Flash', 'MiniMax-M3', name])
    },
  )

  it('keeps Flash first when a picker also sorts labels', () => {
    const options = recommendedModelOptions(models)
      .filter((model) => model.provider_name === 'minimax')
      .sort((a, b) => minimaxModelRank(a) - minimaxModelRank(b) || a.name.localeCompare(b.name))
    expect(options[0].name).toBe('MiniMax-M3.1-Flash')
  })
})
