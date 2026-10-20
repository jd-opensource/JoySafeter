interface NamedModel {
  provider_name: string
  name: string
}

const MINIMAX_MODELS = ['MiniMax-M3.1-Flash', 'MiniMax-M3']

/** Keep a saved selection visible without recommending legacy MiniMax models. */
export function recommendedModelOptions<T extends NamedModel>(
  models: T[],
  selectedId?: string,
): T[] {
  const options = models.filter(
    (model) =>
      model.provider_name !== 'minimax' ||
      MINIMAX_MODELS.includes(model.name) ||
      `${model.provider_name}:${model.name}` === selectedId,
  )
  // Reorder only MiniMax's slots; other providers keep their existing order.
  const minimax = options
    .filter((model) => model.provider_name === 'minimax')
    .sort((a, b) => minimaxModelRank(a) - minimaxModelRank(b))
  let index = 0
  return options.map((model) => (model.provider_name === 'minimax' ? minimax[index++] : model))
}

export function minimaxModelRank(model: NamedModel): number {
  if (model.provider_name !== 'minimax') return 0
  const index = MINIMAX_MODELS.indexOf(model.name)
  return index < 0 ? MINIMAX_MODELS.length : index
}
