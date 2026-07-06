/**
 * 通用 fetch 鉴权与错误处理工具。
 * 用于 native fetch 场景（SSE 流式接口），与 axios 拦截器保持一致行为。
 */

export function getAuthHeaders() {
  const headers = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('token')
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return headers
}

export function handleAuthError(status, options = {}) {
  if (status === 401) {
    localStorage.removeItem('token')
    const message = options.message || '登录已过期，请重新登录'
    if (options.showMessage) {
      options.showMessage(message)
    }
    window.location.href = options.loginUrl || '/login'
    return true
  }
  return false
}

export async function parseFetchError(res) {
  const text = await res.text()
  let detail = text
  try {
    const data = JSON.parse(text)
    detail = data.detail || text
  } catch {
    detail = text || res.statusText || ''
  }
  return { status: res.status, detail }
}
