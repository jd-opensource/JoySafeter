import { Node, Edge } from 'reactflow'
import BuilderNode from '../components/BuilderNode'
import { DefaultEdge } from '../components/DefaultEdge'
import { LoopBackEdge } from '../components/LoopBackEdge'

export const nodeTypes = Object.freeze({
  custom: BuilderNode,
})

export const edgeTypes = Object.freeze({
  default: DefaultEdge,
  loop_back: LoopBackEdge,
})
