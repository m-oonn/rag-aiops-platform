/**
 * 状态码 → Element Plus Tag 类型 / 显示文本 的集中映射。
 * 消除各组件手写重复,并让 magic number 有语义命名。
 *
 * 注意:数值状态 0-3 的 Tag 类型在文档处理与评测任务间一致,
 * 但显示文本按领域不同(文档：上传中/处理中；评测：待处理/运行中),故分开导出。
 */

// 文档处理状态(KnowledgeBaseDetail)
export const DOC_STATUS = { UPLOADING: 0, PROCESSING: 1, SUCCESS: 2, FAILED: 3 }

// 评测任务状态(Evaluation);DATASET_READY 为该模块特有,语义不同于其它模块的 0-3
export const EVAL_STATUS = { PENDING: 0, RUNNING: 1, SUCCESS: 2, FAILED: 3, DATASET_READY: 4 }

// 队列任务状态(Monitor),字符串枚举
export const QUEUE_STATUS = {
  PENDING: 'PENDING',
  PROCESSING: 'PROCESSING',
  SUCCESS: 'SUCCESS',
  FAILURE: 'FAILURE',
}

const NUMERIC_TYPE_MAP = { 0: 'info', 1: 'warning', 2: 'success', 3: 'danger' }

/** 数值状态(0-3)→ Tag 类型,文档与评测共用 */
export function getNumericStatusType(status) {
  return NUMERIC_TYPE_MAP[status] || 'info'
}

const DOC_TEXT_MAP = { 0: '上传中', 1: '处理中', 2: '已完成', 3: '失败' }

export function getDocStatusText(status) {
  return DOC_TEXT_MAP[status] || '未知'
}

const EVAL_TEXT_MAP = { 0: '待处理', 1: '运行中', 2: '已完成', 3: '失败' }

export function getEvalStatusText(status) {
  return EVAL_TEXT_MAP[status] || '未知'
}

/** 队列状态(字符串)→ Tag 类型 */
export function getQueueStatusType(status) {
  if (status === QUEUE_STATUS.SUCCESS) return 'success'
  if (status === QUEUE_STATUS.FAILURE) return 'danger'
  if (status === QUEUE_STATUS.PROCESSING) return 'warning'
  return 'info'
}

const QUEUE_TEXT_MAP = {
  PENDING: '待处理',
  PROCESSING: '处理中',
  SUCCESS: '成功',
  FAILURE: '失败',
}

export function getQueueStatusText(status) {
  return QUEUE_TEXT_MAP[status] || status
}
