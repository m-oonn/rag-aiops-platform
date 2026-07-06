/**
 * 获取纯聊天流式接口的 URL。
 * 使用相对路径，让 Vite dev server 代理到后端，避免硬编码 localhost:8200。
 */
export function getChatStreamUrl() {
  return '/api/v1/chat/stream'
}

/**
 * 获取 AIOps 诊断流式接口的 URL。
 * 同样使用相对路径，走 Vite 代理，避免硬编码 localhost。
 */
export function getAiopsStreamUrl() {
  return '/api/v1/aiops'
}
