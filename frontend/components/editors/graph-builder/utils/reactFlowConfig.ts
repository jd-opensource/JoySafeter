import BuilderNode from '../components/BuilderNode'
import { DefaultEdge } from '../components/DefaultEdge'

export const nodeTypes = Object.freeze({
  custom: BuilderNode,
})

export const edgeTypes = Object.freeze({
  default: DefaultEdge,
})
