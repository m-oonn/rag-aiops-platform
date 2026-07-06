/**
 * 统一的确认框封装。消除各组件重复的 ElMessageBox.confirm 选项与
 * `catch (e) { if (e !== 'cancel') ... }` 模式。
 *
 * 返回布尔值：用户确认为 true，取消为 false（取消不再当作错误抛出）。
 */
import { ElMessageBox } from 'element-plus'

const DEFAULT_OPTIONS = {
  type: 'warning',
  confirmButtonText: '确定',
  cancelButtonText: '取消',
}

/**
 * @param {string} message 提示内容
 * @param {string} [title='提示'] 标题
 * @param {object} [options] 覆盖默认的 ElMessageBox 选项
 * @returns {Promise<boolean>} 确认 true / 取消 false
 */
export async function confirmAction(message, title = '提示', options = {}) {
  try {
    await ElMessageBox.confirm(message, title, { ...DEFAULT_OPTIONS, ...options })
    return true
  } catch {
    return false
  }
}
