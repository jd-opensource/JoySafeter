/**
 * Execution Store - 兼容层
 *
 * 从新的模块化结构重新导出
 * 保持向后兼容，现有代码无需修改
 */

export { useExecutionStore } from './execution/executionStore'
export type { InterruptInfo } from './execution/types'
