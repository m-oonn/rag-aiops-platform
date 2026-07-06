/**
 * 通用 SSE 流式传输层（native fetch + ReadableStream 解析）。
 * 供后端 POST 端点的 SSE 接口复用（原生 EventSource 只支持 GET）。
 * 鉴权与错误处理复用 axios 拦截器的等价逻辑（见 ./auth）。
 *
 * 说明：不吞 AbortError —— 用户主动中断时向上抛出，由调用方决定文案与后续处理。
 */
import { getAuthHeaders, handleAuthError, parseFetchError } from './auth'

/**
 * 发起一次 SSE 流式请求，逐帧解析并回调 onEvent。
 * @param {string} url 目标端点（相对路径，走 Vite 代理）
 * @param {object} body 请求体，将被 JSON 序列化
 * @param {object} opts
 * @param {AbortSignal} opts.signal 中断信号
 * @param {(evt: any) => void} opts.onEvent 单条已解析事件的回调
 * @param {(msg: string) => void} [opts.showMessage] 401 时的提示回调
 */
export async function streamSSE(url, body, { signal, onEvent, showMessage } = {}) {
  const res = await fetch(url, {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify(body),
    signal,
  })

  if (!res.ok) {
    const err = await parseFetchError(res)
    handleAuthError(err.status, showMessage ? { showMessage } : {})
    throw new Error(`请求失败: HTTP ${err.status} - ${err.detail}`)
  }

  if (!res.body) {
    throw new Error('服务器未返回数据流')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    // sse_starlette 用 \r\n 作行分隔,统一成 \n 再按空行分帧
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const dataLine = frame.split('\n').find((l) => l.startsWith('data:'))
      if (!dataLine) continue
      const payload = dataLine.slice(5).trim()
      if (!payload) continue
      try {
        onEvent(JSON.parse(payload))
      } catch (e) {
        console.warn('无法解析 SSE 帧:', payload)
      }
    }
  }
}
