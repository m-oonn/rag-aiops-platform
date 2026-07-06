import { marked } from 'marked'
import DOMPurify from 'dompurify'

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

// 配置 marked：GFM 支持、不换行模式（保留原始换行）
marked.setOptions({
  gfm: true,
  breaks: true,
})

/**
 * 将 Markdown 文本渲染为 HTML，并用 DOMPurify 净化。
 * 用于 Chat.vue / Assistant.vue 中通过 v-html 渲染 LLM 回答；
 * LLM 输出来自模型生成内容与检索文档，不可信任，必须净化后才能进 DOM。
 * @param {string} text - Markdown 格式的原始文本
 * @returns {string} - 净化后的安全 HTML 字符串
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    return DOMPurify.sanitize(marked.parse(text))
  } catch (e) {
    // 降级：返回原始文本
    return text
  }
}
