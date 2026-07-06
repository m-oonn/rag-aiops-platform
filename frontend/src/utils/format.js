/**
 * 通用格式化工具：日期、文件大小。消除各组件的重复定义。
 */

/**
 * 格式化日期时间为本地字符串。
 * 后端返回的时间戳可能缺少时区标记(视为 UTC),这里统一补 Z 再解析,
 * 避免不同组件对同一时间显示不一致。
 * @param {string} dateStr
 */
function normalizeToUtc(dateStr) {
  return dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`
}

export function formatDate(dateStr) {
  if (!dateStr) return ''
  return new Date(normalizeToUtc(dateStr)).toLocaleString()
}

/** 仅日期(不含时间),用于卡片等紧凑展示场景 */
export function formatDateOnly(dateStr) {
  if (!dateStr) return ''
  return new Date(normalizeToUtc(dateStr)).toLocaleDateString()
}

const SIZE_UNITS = ['B', 'KB', 'MB', 'GB']
const BYTES_PER_KB = 1024

/**
 * 将字节数格式化为带单位的可读字符串。
 * @param {number} bytes
 */
export function formatSize(bytes) {
  if (!bytes) return '0 B'
  const i = Math.floor(Math.log(bytes) / Math.log(BYTES_PER_KB))
  const size = parseFloat((bytes / Math.pow(BYTES_PER_KB, i)).toFixed(2))
  return `${size} ${SIZE_UNITS[i]}`
}
