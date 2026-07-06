/**
 * 轮询 composable：按固定间隔调用 fn，并在组件卸载时自动清理。
 * 消除各组件重复的 setInterval + onUnmounted(clearInterval) 模式。
 */
import { onUnmounted } from 'vue'

// 轮询间隔常量
export const POLL_FAST = 3000
export const POLL_SLOW = 5000

/**
 * @param {() => void} fn 每次轮询执行的函数
 * @param {number} interval 间隔毫秒
 * @returns {{ start: () => void, stop: () => void }}
 */
export function usePolling(fn, interval) {
  let timer = null

  const stop = () => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  const start = () => {
    stop()
    timer = setInterval(fn, interval)
  }

  onUnmounted(stop)

  return { start, stop }
}
